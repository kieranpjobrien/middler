"""Tests for the odds-api.io client + normaliser against its LIVE response shape."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from middler.config import DetectionConfig, StakingConfig
from middler.detection.engine import detect_opportunities
from middler.ingest.oddsapi_io import OddsApiIoClient, normalise_io_event

# Real markets: "ML" (h2h), "Spread" (hdp+home/away), "Totals" (hdp+over/under).
SAMPLE = {
    "id": 123456,
    "home": "Guatemala",
    "away": "El Salvador",
    "date": "2025-10-15T15:00:00Z",
    "status": "pending",
    "bookmakers": {
        "Bet365": [
            {"name": "ML", "odds": [{"home": "2.10", "draw": "3.40", "away": "3.20"}]},
            {"name": "Spread", "odds": [{"hdp": -0.5, "home": "1.95", "away": "1.85"}]},
            {"name": "Totals", "odds": [{"hdp": 2.5, "over": "1.90", "under": "1.90"}]},
        ]
    },
}


def test_normalise_io_event_maps_real_markets() -> None:
    event = normalise_io_event(SAMPLE, sport_key="soccer_epl")
    assert event.id == "123456"
    assert event.home_team == "Guatemala"
    assert event.commence_time == datetime(2025, 10, 15, 15, 0, tzinfo=UTC)

    by_market = {bm.market_key: bm for bm in event.book_markets}
    assert set(by_market) == {"h2h", "totals", "spreads"}

    h2h = {o.name: o.price for o in by_market["h2h"].outcomes}
    assert h2h == {"Guatemala": 2.10, "El Salvador": 3.20, "Draw": 3.40}

    # spreads: home carries hdp, away carries -hdp.
    spreads = {o.name: (o.price, o.point) for o in by_market["spreads"].outcomes}
    assert spreads["Guatemala"] == (1.95, -0.5)
    assert spreads["El Salvador"] == (1.85, 0.5)

    # totals: the line is in `hdp` (not `max`), per the live API.
    totals = {o.name: (o.price, o.point) for o in by_market["totals"].outcomes}
    assert totals["Over"] == (1.90, 2.5)
    assert totals["Under"] == (1.90, 2.5)


def test_totals_line_falls_back_to_max_for_legacy_docs_shape() -> None:
    raw = {
        "id": 1,
        "home": "A",
        "away": "B",
        "date": "2026-06-12T09:00:00Z",
        "bookmakers": {"BookA": [{"name": "Over/Under", "odds": [{"max": 2.5, "over": "1.9", "under": "1.9"}]}]},
    }
    event = normalise_io_event(raw, sport_key="soccer")
    totals = {o.name: o.point for o in event.book_markets[0].outcomes}
    assert totals == {"Over": 2.5, "Under": 2.5}


def test_io_event_flows_into_engine() -> None:
    # Two books straddling the goals line → a 1-goal middle (Over 2.5 / Under 3.5).
    raw = {
        "id": 999,
        "home": "A",
        "away": "B",
        "date": "2026-06-12T09:00:00Z",
        "bookmakers": {
            "BookA": [{"name": "Totals", "odds": [{"hdp": 2.5, "over": "1.95", "under": "1.87"}]}],
            "BookB": [{"name": "Totals", "odds": [{"hdp": 3.5, "over": "1.85", "under": "1.95"}]}],
        },
    }
    event = normalise_io_event(raw, sport_key="soccer")
    opps = detect_opportunities(
        event,
        detection=DetectionConfig(),
        staking=StakingConfig(),
        sharp_books=[],
        hit_rate_prior={"totals": 0.06},
        observed_at=datetime(2026, 6, 11, tzinfo=UTC),
    )
    middles = [o for o in opps if o.kind == "middle"]
    assert len(middles) == 1
    assert middles[0].width == pytest.approx(1.0)


def test_normalise_skips_unknown_markets_and_bad_prices() -> None:
    raw = {
        "id": 1,
        "home": "A",
        "away": "B",
        "date": "2026-06-12T09:00:00Z",
        "bookmakers": {
            "BookA": [
                {"name": "Corners", "odds": [{"over": "1.9", "under": "1.9", "hdp": 9.5}]},  # unknown market
                {"name": "ML", "odds": [{"home": "0", "away": "2.0"}]},  # bad home price dropped
            ]
        },
    }
    event = normalise_io_event(raw, sport_key="soccer")
    assert {bm.market_key for bm in event.book_markets} == {"h2h"}
    h2h = event.book_markets[0].outcomes
    assert len(h2h) == 1 and h2h[0].name == "B"


def test_betfair_lay_prices_extracted() -> None:
    raw = {
        "id": 5,
        "home": "A",
        "away": "B",
        "date": "2026-06-12T09:00:00Z",
        "bookmakers": {
            "Betfair Exchange": [
                {
                    "name": "ML",
                    "odds": [
                        {
                            "home": "2.0",
                            "draw": "3.5",
                            "away": "4.0",
                            "layHome": "2.1",
                            "layAway": "4.2",
                            "layDraw": "3.6",
                        }
                    ],
                },
                {
                    "name": "Totals",
                    "odds": [{"hdp": 2.5, "over": "1.9", "under": "1.9", "layOver": "1.95", "layUnder": "1.97"}],
                },
            ]
        },
    }
    event = normalise_io_event(raw, sport_key="soccer")
    markets = {bm.market_key for bm in event.book_markets}
    assert {"h2h", "h2h_lay", "totals", "totals_lay"} <= markets
    lay_h2h = next(bm for bm in event.book_markets if bm.market_key == "h2h_lay")
    assert {o.name: o.price for o in lay_h2h.outcomes} == {"A": 2.1, "B": 4.2, "Draw": 3.6}
    lay_tot = next(bm for bm in event.book_markets if bm.market_key == "totals_lay")
    assert {o.name: (o.price, o.point) for o in lay_tot.outcomes} == {"Over": (1.95, 2.5), "Under": (1.97, 2.5)}


def test_get_odds_requires_bookmakers_and_handles_empty_ids() -> None:
    client = OddsApiIoClient(api_key="x")  # no network on construction
    with pytest.raises(ValueError):
        client.get_odds(["evt1"], [])  # bookmakers required by the API
    assert client.get_odds([], ["Bet365"]) == []  # nothing to fetch, no call
    client.close()
