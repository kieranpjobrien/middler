"""Tests for the odds-api.io normaliser against its verified response shape."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from middler.config import DetectionConfig, StakingConfig
from middler.detection.engine import detect_opportunities
from middler.ingest.oddsapi_io import normalise_io_event

SAMPLE = {
    "id": 123456,
    "home": "Manchester United",
    "away": "Liverpool",
    "date": "2025-10-15T15:00:00Z",
    "status": "pending",
    "bookmakers": {
        "Bet365": [
            {"name": "ML", "odds": [{"home": "2.10", "draw": "3.40", "away": "3.20"}]},
            {"name": "Asian Handicap", "odds": [{"hdp": -0.5, "home": "1.95", "away": "1.85"}]},
            {"name": "Over/Under", "odds": [{"max": 2.5, "over": "1.90", "under": "1.90"}]},
        ]
    },
}


def test_normalise_io_event_maps_all_markets() -> None:
    event = normalise_io_event(SAMPLE, sport_key="soccer_epl")
    assert event.id == "123456"
    assert event.home_team == "Manchester United"
    assert event.commence_time == datetime(2025, 10, 15, 15, 0, tzinfo=UTC)

    by_market = {bm.market_key: bm for bm in event.book_markets}
    assert set(by_market) == {"h2h", "totals", "spreads"}

    # h2h: team names + Draw, prices parsed from strings.
    h2h = {o.name: o.price for o in by_market["h2h"].outcomes}
    assert h2h == {"Manchester United": 2.10, "Liverpool": 3.20, "Draw": 3.40}

    # spreads: home carries hdp, away carries -hdp.
    spreads = {o.name: (o.price, o.point) for o in by_market["spreads"].outcomes}
    assert spreads["Manchester United"] == (1.95, -0.5)
    assert spreads["Liverpool"] == (1.85, 0.5)

    # totals: Over/Under at the `max` line.
    totals = {o.name: (o.price, o.point) for o in by_market["totals"].outcomes}
    assert totals["Over"] == (1.90, 2.5)
    assert totals["Under"] == (1.90, 2.5)


def test_io_event_flows_into_engine() -> None:
    # Two books straddling the goals line → a 1-goal middle (Over 2.5 / Under 3.5).
    raw = {
        "id": 999,
        "home": "A",
        "away": "B",
        "date": "2026-06-12T09:00:00Z",
        "bookmakers": {
            "BookA": [{"name": "Over/Under", "odds": [{"max": 2.5, "over": "1.95", "under": "1.87"}]}],
            "BookB": [{"name": "Over/Under", "odds": [{"max": 3.5, "over": "1.85", "under": "1.95"}]}],
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
                {"name": "Corners", "odds": [{"over": "1.9", "under": "1.9", "max": 9.5}]},  # unknown market
                {"name": "ML", "odds": [{"home": "0", "away": "2.0"}]},  # bad home price dropped
            ]
        },
    }
    event = normalise_io_event(raw, sport_key="soccer")
    assert {bm.market_key for bm in event.book_markets} == {"h2h"}
    h2h = event.book_markets[0].outcomes
    assert len(h2h) == 1 and h2h[0].name == "B"
