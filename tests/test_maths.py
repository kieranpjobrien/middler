"""Hand-worked correctness tests for the sacred detection maths.

Every expected value below is computed by hand in the comments so a reviewer can
check the arithmetic without trusting the implementation. If one of these fails,
the engine must not place a cent.
"""

from __future__ import annotations

import math

import pytest

from middler.detection.maths import (
    arbitrage,
    balanced_split,
    equal_split,
    evaluate_middle,
    fractional_kelly_stake,
    implied_prob,
    implied_sum,
)


# ── implied probability ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("odds", "expected"),
    [(2.0, 0.5), (4.0, 0.25), (1.0, 1.0), (1.25, 0.8)],
)
def test_implied_prob(odds: float, expected: float) -> None:
    assert implied_prob(odds) == pytest.approx(expected)


def test_implied_prob_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        implied_prob(0.0)
    with pytest.raises(ValueError):
        implied_prob(-1.5)


def test_implied_sum() -> None:
    # 1/2 + 1/4 = 0.75
    assert implied_sum([2.0, 4.0]) == pytest.approx(0.75)
    with pytest.raises(ValueError):
        implied_sum([])


# ── arbitrage ────────────────────────────────────────────────────────────────
def test_two_way_arbitrage_present() -> None:
    # d1 = d2 = 2.10, S = 2 * (1/2.1) = 0.9523809..., margin = 0.0476190...
    # stakes = 100 * (1/2.1) / 0.95238 = 50 each; return = 50 * 2.1 = 105; profit = 5.
    r = arbitrage([2.10, 2.10], total_stake=100.0)
    assert r.is_arbitrage
    assert r.implied_sum == pytest.approx(0.9523809524)
    assert r.margin == pytest.approx(0.0476190476)
    assert r.stakes == pytest.approx((50.0, 50.0))
    assert sum(r.stakes) == pytest.approx(100.0)
    assert r.guaranteed_return == pytest.approx(105.0)
    assert r.profit == pytest.approx(5.0)
    assert r.roi == pytest.approx(0.05)


def test_two_way_no_arbitrage() -> None:
    # d = 1.90 each, S = 1.0526 > 1 → no arb, negative margin.
    r = arbitrage([1.90, 1.90], total_stake=100.0)
    assert not r.is_arbitrage
    assert r.implied_sum == pytest.approx(1.0526315789)
    assert r.margin < 0


def test_asymmetric_arbitrage_locks_equal_return() -> None:
    # Whatever wins, the return is total_stake / S. Verify each leg returns it.
    odds = [2.05, 2.10]
    r = arbitrage(odds, total_stake=200.0)
    assert r.is_arbitrage
    for d, stake in zip(odds, r.stakes, strict=True):
        assert stake * d == pytest.approx(r.guaranteed_return)
    assert sum(r.stakes) == pytest.approx(200.0)


def test_three_way_arbitrage() -> None:
    # S = 1/3 + 1/3.4 + 1/3.5 = 0.33333 + 0.29412 + 0.28571 = 0.91317 < 1 → arb.
    odds = [3.0, 3.4, 3.5]
    r = arbitrage(odds, total_stake=100.0)
    assert r.is_arbitrage
    assert r.implied_sum == pytest.approx(1 / 3 + 1 / 3.4 + 1 / 3.5)
    assert sum(r.stakes) == pytest.approx(100.0)
    for d, stake in zip(odds, r.stakes, strict=True):
        assert stake * d == pytest.approx(r.guaranteed_return)


def test_arbitrage_requires_two_outcomes() -> None:
    with pytest.raises(ValueError):
        arbitrage([2.0])


# ── stake splits ─────────────────────────────────────────────────────────────
def test_equal_split() -> None:
    assert equal_split(100.0) == (50.0, 50.0)


def test_balanced_split_equalises_returns() -> None:
    # over_odds = 2.00, under_odds = 1.80:
    # stake_over = 100 * 1.80 / 3.80 = 47.3684; stake_under = 100 * 2.00 / 3.80 = 52.6316
    stake_over, stake_under = balanced_split(100.0, over_odds=2.00, under_odds=1.80)
    assert stake_over == pytest.approx(47.3684210526)
    assert stake_under == pytest.approx(52.6315789474)
    assert stake_over + stake_under == pytest.approx(100.0)
    # The defining property: both legs return the same amount.
    assert stake_over * 2.00 == pytest.approx(stake_under * 1.80)


# ── middles ──────────────────────────────────────────────────────────────────
def test_classic_middle_balanced_symmetric() -> None:
    # Proposal's example: Under 72.5 @ 1.91, Over 71.5 @ 1.91, $100 total.
    # Symmetric odds → balanced split is 50/50.
    #   return per leg = 50 * 1.91 = 95.5
    #   pl_low = pl_high = 95.5 - 100 = -4.5
    #   pl_middle = 95.5 + 95.5 - 100 = 91.0
    #   ev at 6% = 0.06 * 91 + 0.94 * (-4.5) = 5.46 - 4.23 = 1.23
    m = evaluate_middle(
        over_point=71.5,
        over_odds=1.91,
        under_point=72.5,
        under_odds=1.91,
        total_stake=100.0,
        hit_rate=0.06,
    )
    assert m.has_middle
    assert m.width == pytest.approx(1.0)
    assert m.stake_over == pytest.approx(50.0)
    assert m.stake_under == pytest.approx(50.0)
    assert m.pl_low == pytest.approx(-4.5)
    assert m.pl_high == pytest.approx(-4.5)
    assert m.pl_middle == pytest.approx(91.0)
    assert m.worst_non_middle == pytest.approx(-4.5)
    assert m.ev == pytest.approx(1.23)
    assert not m.is_risk_free


def test_risk_free_middle_is_also_an_arb() -> None:
    # Under 72.5 @ 2.05, Over 71.5 @ 2.05: S = 2/2.05 = 0.9756 < 1.
    #   50/50 → return per leg 102.5 → pl_low = pl_high = 2.5 (>= 0, risk-free)
    #   pl_middle = 205 - 100 = 105
    m = evaluate_middle(
        over_point=71.5,
        over_odds=2.05,
        under_point=72.5,
        under_odds=2.05,
        total_stake=100.0,
        hit_rate=0.06,
    )
    assert m.is_risk_free
    assert m.pl_low == pytest.approx(2.5)
    assert m.pl_high == pytest.approx(2.5)
    assert m.pl_middle == pytest.approx(105.0)
    assert m.ev == pytest.approx(0.06 * 105.0 + 0.94 * 2.5)


def test_balanced_equalises_non_middle_outcomes() -> None:
    # Asymmetric odds: under 1.80, over 2.00. Balanced must make pl_low == pl_high.
    m = evaluate_middle(
        over_point=71.5,
        over_odds=2.00,
        under_point=72.5,
        under_odds=1.80,
        total_stake=100.0,
        hit_rate=0.05,
        mode="balanced",
    )
    assert m.pl_low == pytest.approx(m.pl_high)
    # Under balanced staking, EV uses an exact (not conservative) non-middle P/L.
    assert m.ev == pytest.approx(0.05 * m.pl_middle + 0.95 * m.pl_low)


def test_equal_mode_leaves_non_middle_outcomes_asymmetric() -> None:
    # Same odds as above but equal stakes → the two misses differ.
    #   50/50: pl_low = 50*1.80 - 100 = -10 ; pl_high = 50*2.00 - 100 = 0
    #   pl_middle = 90 + 100 - 100 = 90 ; worst = -10
    m = evaluate_middle(
        over_point=71.5,
        over_odds=2.00,
        under_point=72.5,
        under_odds=1.80,
        total_stake=100.0,
        hit_rate=0.05,
        mode="equal",
    )
    assert m.pl_low == pytest.approx(-10.0)
    assert m.pl_high == pytest.approx(0.0)
    assert m.pl_middle == pytest.approx(90.0)
    assert m.worst_non_middle == pytest.approx(-10.0)
    # EV uses the worst (conservative) leg here.
    assert m.ev == pytest.approx(0.05 * 90.0 + 0.95 * -10.0)


def test_no_overlap_is_not_a_middle() -> None:
    # over_point above under_point → no window.
    m = evaluate_middle(
        over_point=73.5,
        over_odds=1.91,
        under_point=72.5,
        under_odds=1.91,
        total_stake=100.0,
        hit_rate=0.06,
    )
    assert not m.has_middle
    assert m.width == pytest.approx(-1.0)


def test_spread_middle_maps_to_same_abstraction() -> None:
    # Team A -3.5 @ 1.95 (wins when margin > 3.5 → over leg, over_point=3.5)
    # Team B +4.5 @ 1.95 (wins when margin < 4.5 → under leg, under_point=4.5)
    # Middle = A wins by exactly 4. Width 1.0, symmetric → 50/50.
    m = evaluate_middle(
        over_point=3.5,
        over_odds=1.95,
        under_point=4.5,
        under_odds=1.95,
        total_stake=100.0,
        hit_rate=0.05,
    )
    assert m.has_middle
    assert m.width == pytest.approx(1.0)
    assert m.pl_middle == pytest.approx(2 * 50 * 1.95 - 100)


def test_middle_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        evaluate_middle(
            over_point=71.5,
            over_odds=0.0,
            under_point=72.5,
            under_odds=1.9,
            total_stake=100.0,
            hit_rate=0.05,
        )
    with pytest.raises(ValueError):
        evaluate_middle(
            over_point=71.5,
            over_odds=1.9,
            under_point=72.5,
            under_odds=1.9,
            total_stake=100.0,
            hit_rate=1.5,
        )
    with pytest.raises(ValueError):
        evaluate_middle(
            over_point=71.5,
            over_odds=1.9,
            under_point=72.5,
            under_odds=1.9,
            total_stake=100.0,
            hit_rate=0.05,
            mode="martingale",
        )


# ── fractional Kelly sizing ──────────────────────────────────────────────────
def test_fractional_kelly_scales_with_edge() -> None:
    # edge_per_unit 0.0123, fraction 0.25 → min(0.25, 0.25*0.0123) = 0.003075
    # stake = 1000 * 0.003075 = 3.075
    assert fractional_kelly_stake(1000.0, 0.25, 0.0123) == pytest.approx(3.075)


def test_fractional_kelly_zero_on_non_positive_edge() -> None:
    assert fractional_kelly_stake(1000.0, 0.25, 0.0) == 0.0
    assert fractional_kelly_stake(1000.0, 0.25, -0.5) == 0.0
    assert fractional_kelly_stake(0.0, 0.25, 0.5) == 0.0


def test_fractional_kelly_capped_at_fraction() -> None:
    # Huge edge must never risk more than kelly_fraction of bankroll.
    stake = fractional_kelly_stake(1000.0, 0.25, 100.0)
    assert stake <= 0.25 * 1000.0 + 1e-9
    assert math.isclose(stake, 250.0)
