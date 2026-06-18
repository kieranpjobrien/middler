"""Tests for the OddsPapi normaliser against its verified reference-driven shape."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from middler.config import DetectionConfig, StakingConfig
from middler.detection.engine import detect_opportunities
from middler.ingest.oddspapi import normalise_oddspapi_fixture

# The /markets reference shape (verified live): marketType + explicit outcome labels.
MARKET_REF = {
    311: {"market_type": "moneyline", "handicap": 0, "outcomes": {311: "1", 312: "2"}},
    313: {"market_type": "1x2", "handicap": 0, "outcomes": {313: "1", 314: "X", 315: "2"}},
    999: {"market_type": "total", "handicap": 0, "outcomes": {999: "over", 1000: "under"}},  # not h2h → ignored
}


def _odds_market(outcome_prices: dict[str, float]) -> dict:
    return {"outcomes": {oid: {"players": {"0": {"price": str(p)}}} for oid, p in outcome_prices.items()}}


def _fixture(bookmaker_odds: dict) -> dict:
    return {
        "fixtureId": "fx1",
        "participant1Name": "Carlton",
        "participant2Name": "Collingwood",
        "startTime": "2026-06-20T09:00:00Z",
        "bookmakerOdds": bookmaker_odds,
    }


def test_normalise_maps_winner_outcomes_to_team_names() -> None:
    raw = _fixture({"sportsbet": {"markets": {"311": _odds_market({"311": 1.80, "312": 2.05})}}})
    event = normalise_oddspapi_fixture(raw, MARKET_REF, sport_key="aussierules_afl")
    assert event.id == "fx1" and event.home_team == "Carlton"
    assert event.commence_time == datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
    assert len(event.book_markets) == 1
    h2h = {o.name: o.price for o in event.book_markets[0].outcomes}
    assert h2h == {"Carlton": 1.80, "Collingwood": 2.05}  # "1"→p1, "2"→p2


def test_1x2_maps_draw() -> None:
    raw = _fixture({"tab": {"markets": {"313": _odds_market({"313": 2.0, "314": 3.4, "315": 3.2})}}})
    event = normalise_oddspapi_fixture(raw, MARKET_REF, sport_key="rugbyleague_nrl")
    names = {o.name: o.price for o in event.book_markets[0].outcomes}
    assert names == {"Carlton": 2.0, "Draw": 3.4, "Collingwood": 3.2}


def test_non_h2h_markets_ignored() -> None:
    raw = _fixture({"book": {"markets": {"999": _odds_market({"999": 1.9, "1000": 1.9})}}})
    event = normalise_oddspapi_fixture(raw, MARKET_REF, sport_key="s")
    assert event.book_markets == []  # "total" market type not normalised here


def test_oddspapi_h2h_arbitrage_across_books() -> None:
    # sportsbet best on Carlton (2.10), tab best on Collingwood (2.10) → arb.
    raw = _fixture(
        {
            "sportsbet": {"markets": {"311": _odds_market({"311": 2.10, "312": 1.80})}},
            "tab": {"markets": {"311": _odds_market({"311": 1.80, "312": 2.10})}},
        }
    )
    event = normalise_oddspapi_fixture(raw, MARKET_REF, sport_key="aussierules_afl")
    arbs = [
        o
        for o in detect_opportunities(
            event,
            detection=DetectionConfig(),
            staking=StakingConfig(),
            sharp_books=[],
            hit_rate_prior={},
            observed_at=datetime(2026, 6, 19, tzinfo=UTC),
        )
        if o.kind == "arb"
    ]
    assert len(arbs) == 1
    assert arbs[0].margin == pytest.approx(0.0476190476)
    books = {leg.outcome_name: leg.bookmaker for leg in arbs[0].legs}
    assert books["Carlton"] == "sportsbet" and books["Collingwood"] == "tab"


def test_bad_price_dropped() -> None:
    raw = _fixture({"book": {"markets": {"311": _odds_market({"311": 0, "312": 2.0})}}})
    event = normalise_oddspapi_fixture(raw, MARKET_REF, sport_key="s")
    # Only one valid outcome → fewer than 2 → no h2h market kept.
    assert event.book_markets == []
