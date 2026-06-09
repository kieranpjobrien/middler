"""Cross-feed canonicalisation, fixture matching, and event merging."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from middler.books import canonical_book
from middler.config import DetectionConfig, StakingConfig
from middler.detection.engine import detect_opportunities
from middler.ingest.merge import align_and_merge, best_fixture_match, merge_events
from middler.match.entity import EntityMatcher
from middler.models import BookMarket, Event, Outcome

COMMENCE = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)


def _event(
    event_id: str, books: list[BookMarket], home: str = "Carlton", away: str = "Collingwood", offset_min: int = 0
) -> Event:
    return Event(
        id=event_id,
        sport_key="aussierules_afl",
        commence_time=COMMENCE + timedelta(minutes=offset_min),
        home_team=home,
        away_team=away,
        book_markets=books,
    )


def _totals(book: str, name: str, point: float, price: float) -> BookMarket:
    return BookMarket(bookmaker=book, market_key="totals", outcomes=[Outcome(name=name, price=price, point=point)])


def test_canonical_book_unifies_feed_spellings() -> None:
    assert canonical_book("betfair_ex_au") == "betfair"
    assert canonical_book("Betfair") == "betfair"
    assert canonical_book("pointsbetau") == "pointsbet"
    assert canonical_book("PointsBet") == "pointsbet"
    assert canonical_book("sportsbet") == "sportsbet"


def test_merge_dedups_same_book_across_feeds() -> None:
    # Same physical book from two feeds must collapse to one (no fake arb).
    a = _event("A", [_totals("betfair_ex_au", "Over", 71.5, 1.95)])
    b = _event("B", [_totals("Betfair", "Over", 71.5, 1.96)])
    merged = merge_events([a, b])
    books = [bm.bookmaker for bm in merged.book_markets]
    assert books == ["betfair"]
    assert merged.id == "A"  # primary identity retained


def test_merge_unions_different_books() -> None:
    a = _event("A", [_totals("sportsbet", "Over", 71.5, 1.95)])
    b = _event("B", [_totals("tab", "Under", 72.5, 1.95)])
    merged = merge_events([a, b])
    assert {bm.bookmaker for bm in merged.book_markets} == {"sportsbet", "tab"}


def test_best_fixture_match_requires_both_teams_and_kickoff() -> None:
    matcher = EntityMatcher()
    target = _event("A", [])
    same = _event("B", [], offset_min=30)  # within tolerance, same teams
    other = _event("C", [], home="Sydney", away="Geelong")  # different fixture
    far = _event("D", [], offset_min=200)  # too far in time
    assert best_fixture_match(target, [other, far, same], matcher) is same
    assert best_fixture_match(target, [other, far], matcher) is None


def test_align_and_merge_completes_a_cross_feed_middle() -> None:
    # Primary feed sees only one side; the secondary feed supplies the other →
    # together they form a middle the primary alone could never detect.
    primary = [_event("A", [_totals("sportsbet", "Over", 71.5, 1.95)])]
    secondary = [_event("B", [_totals("tab", "Under", 72.5, 1.95)])]
    merged = align_and_merge(primary, secondary, EntityMatcher())
    assert len(merged) == 1

    opps = detect_opportunities(
        merged[0],
        detection=DetectionConfig(),
        staking=StakingConfig(),
        sharp_books=[],
        hit_rate_prior={"totals": 0.06},
        observed_at=COMMENCE,
    )
    middles = [o for o in opps if o.kind == "middle"]
    assert len(middles) == 1
    assert middles[0].width == pytest.approx(1.0)


def test_align_passes_through_unmatched_primary() -> None:
    primary = [_event("A", [_totals("sportsbet", "Over", 71.5, 1.95)])]
    secondary = [_event("B", [_totals("tab", "Under", 72.5, 1.95)], home="Sydney", away="Geelong")]
    merged = align_and_merge(primary, secondary, EntityMatcher())
    assert len(merged) == 1
    assert [bm.bookmaker for bm in merged[0].book_markets] == ["sportsbet"]  # unchanged
