"""Engine tests over hand-built multi-book events.

These exercise the market→over/under mapping and the threshold/sanity filters,
on top of the already-proven maths.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from middler.config import DetectionConfig, StakingConfig
from middler.detection.engine import detect_opportunities
from middler.models import BookMarket, Event, Outcome

NOW = datetime(2026, 6, 9, 0, 0, tzinfo=UTC)
COMMENCE = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
PRIOR = {"totals": 0.06, "spreads": 0.05}


def _event(book_markets: list[BookMarket]) -> Event:
    return Event(
        id="evt1",
        sport_key="aussierules_afl",
        sport_title="AFL",
        commence_time=COMMENCE,
        home_team="Team A",
        away_team="Team B",
        book_markets=book_markets,
    )


def _detect(event: Event, sharp_books: list[str] | None = None, det: DetectionConfig | None = None):
    return detect_opportunities(
        event,
        detection=det or DetectionConfig(),
        staking=StakingConfig(default_total_stake=100.0),
        sharp_books=sharp_books or [],
        hit_rate_prior=PRIOR,
        observed_at=NOW,
    )


def test_totals_middle_picks_best_cross_book_lines() -> None:
    # bookA Over 71.5 @ 1.95 ; bookB Under 72.5 @ 1.95 → a 1-point middle.
    event = _event(
        [
            BookMarket(
                bookmaker="sportsbet",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.95, point=71.5), Outcome(name="Under", price=1.87, point=71.5)],
            ),
            BookMarket(
                bookmaker="tab",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.85, point=72.5), Outcome(name="Under", price=1.95, point=72.5)],
            ),
        ]
    )
    opps = _detect(event)
    middles = [o for o in opps if o.kind == "middle"]
    assert len(middles) == 1
    m = middles[0]
    assert m.width == pytest.approx(1.0)
    over_leg = next(leg for leg in m.legs if leg.side == "over")
    under_leg = next(leg for leg in m.legs if leg.side == "under")
    assert over_leg.bookmaker == "sportsbet" and over_leg.point == pytest.approx(71.5)
    assert under_leg.bookmaker == "tab" and under_leg.point == pytest.approx(72.5)
    assert sum(leg.stake for leg in m.legs) == pytest.approx(100.0, abs=0.05)
    assert m.ev is not None


def test_h2h_arbitrage_across_books() -> None:
    event = _event(
        [
            BookMarket(
                bookmaker="sportsbet",
                market_key="h2h",
                outcomes=[Outcome(name="Team A", price=2.10), Outcome(name="Team B", price=1.80)],
            ),
            BookMarket(
                bookmaker="tab",
                market_key="h2h",
                outcomes=[Outcome(name="Team A", price=1.80), Outcome(name="Team B", price=2.10)],
            ),
        ]
    )
    arbs = [o for o in _detect(event) if o.kind == "arb"]
    assert len(arbs) == 1
    assert arbs[0].margin == pytest.approx(0.0476190476)
    # Best price for each side comes from a different book.
    books = {leg.outcome_name: leg.bookmaker for leg in arbs[0].legs}
    assert books["Team A"] == "sportsbet"
    assert books["Team B"] == "tab"


def test_spread_middle_maps_team_handicaps() -> None:
    # bookA Team A -3.5 ; bookB Team B +4.5 → middle when A wins by exactly 4.
    event = _event(
        [
            BookMarket(
                bookmaker="sportsbet",
                market_key="spreads",
                outcomes=[
                    Outcome(name="Team A", price=1.95, point=-3.5),
                    Outcome(name="Team B", price=1.87, point=3.5),
                ],
            ),
            BookMarket(
                bookmaker="tab",
                market_key="spreads",
                outcomes=[
                    Outcome(name="Team A", price=1.90, point=-4.5),
                    Outcome(name="Team B", price=1.95, point=4.5),
                ],
            ),
        ]
    )
    middles = [o for o in _detect(event) if o.kind == "middle"]
    assert len(middles) == 1
    m = middles[0]
    assert m.width == pytest.approx(1.0)
    over_leg = next(leg for leg in m.legs if leg.side == "over")
    under_leg = next(leg for leg in m.legs if leg.side == "under")
    assert over_leg.outcome_name == "Team A" and over_leg.point == pytest.approx(-3.5)
    assert under_leg.outcome_name == "Team B" and under_leg.point == pytest.approx(4.5)


def test_reverse_gap_is_not_flagged() -> None:
    # Over 72.5 + Under 71.5: between 71.5 and 72.5 NEITHER wins — must not flag.
    event = _event(
        [
            BookMarket(
                bookmaker="sportsbet",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.95, point=72.5)],
            ),
            BookMarket(
                bookmaker="tab",
                market_key="totals",
                outcomes=[Outcome(name="Under", price=1.95, point=71.5)],
            ),
        ]
    )
    assert _detect(event) == []


def test_sharp_reference_verifies_consistent_lines() -> None:
    event = _event(
        [
            BookMarket(
                bookmaker="sportsbet",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.95, point=71.5)],
            ),
            BookMarket(
                bookmaker="tab",
                market_key="totals",
                outcomes=[Outcome(name="Under", price=1.95, point=72.5)],
            ),
            BookMarket(
                bookmaker="pinnacle",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.95, point=71.5), Outcome(name="Under", price=1.95, point=72.5)],
            ),
        ]
    )
    middles = [o for o in _detect(event, sharp_books=["pinnacle"]) if o.kind == "middle"]
    assert middles and middles[0].reference_verified is True


def test_sharp_reference_flags_stale_line() -> None:
    # Our Over is priced far longer (1.95) than the sharp thinks (1.50) → suspicious.
    event = _event(
        [
            BookMarket(
                bookmaker="sportsbet",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.95, point=71.5)],
            ),
            BookMarket(
                bookmaker="tab",
                market_key="totals",
                outcomes=[Outcome(name="Under", price=1.95, point=72.5)],
            ),
            BookMarket(
                bookmaker="pinnacle",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.50, point=71.5), Outcome(name="Under", price=1.95, point=72.5)],
            ),
        ]
    )
    middles = [o for o in _detect(event, sharp_books=["pinnacle"]) if o.kind == "middle"]
    assert middles and middles[0].reference_verified is False


def test_outright_back_lay_detects_golf_value() -> None:
    # Real US-Open shape: TAB backs Fitzpatrick at 81 while Betfair lay is 34 →
    # a risk-free back-lay. Scheffler (back 7 < lay 8) is not value and is dropped.
    event = _event(
        [
            BookMarket(
                bookmaker="tab",
                market_key="outrights",
                outcomes=[Outcome(name="Fitzpatrick", price=81.0), Outcome(name="Scheffler", price=7.0)],
            ),
            BookMarket(
                bookmaker="betfair_ex_au",
                market_key="outrights_lay",
                outcomes=[Outcome(name="Fitzpatrick", price=34.0), Outcome(name="Scheffler", price=8.0)],
            ),
        ]
    )
    back_lays = [o for o in _detect(event) if o.kind == "back_lay"]
    assert len(back_lays) == 1
    o = back_lays[0]
    assert o.is_risk_free
    assert o.profit == pytest.approx(126.66, abs=0.05)  # $100 back, 5% commission
    back = next(leg for leg in o.legs if leg.side == "back")
    lay = next(leg for leg in o.legs if leg.side == "lay")
    assert back.bookmaker == "tab" and back.price == 81.0
    assert lay.bookmaker == "betfair_ex_au" and lay.price == 34.0


def test_team_back_lay_from_betfair_lay() -> None:
    # Bet365 backs Over 2.5 @ 2.10; Betfair lays the same line @ 2.00 → value back-lay.
    event = _event(
        [
            BookMarket(
                bookmaker="bet365",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=2.10, point=2.5)],
            ),
            BookMarket(
                bookmaker="betfair_ex_au",
                market_key="totals_lay",
                outcomes=[Outcome(name="Over", price=2.00, point=2.5)],
            ),
        ]
    )
    back_lays = [o for o in _detect(event) if o.kind == "back_lay"]
    assert len(back_lays) == 1
    o = back_lays[0]
    assert o.market_key == "totals" and o.is_risk_free
    back = next(leg for leg in o.legs if leg.side == "back")
    lay = next(leg for leg in o.legs if leg.side == "lay")
    assert back.bookmaker == "bet365" and back.point == pytest.approx(2.5)
    assert lay.bookmaker == "betfair_ex_au" and lay.price == pytest.approx(2.00)


def test_no_opportunity_on_vigged_market() -> None:
    # A single book with normal vig: no arb, and Over/Under at the same line is
    # not a middle.
    event = _event(
        [
            BookMarket(
                bookmaker="sportsbet",
                market_key="totals",
                outcomes=[Outcome(name="Over", price=1.91, point=72.5), Outcome(name="Under", price=1.91, point=72.5)],
            ),
        ]
    )
    assert _detect(event) == []
