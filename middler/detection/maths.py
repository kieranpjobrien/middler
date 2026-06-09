"""Pure betting arithmetic — arbitrage, middles, and stake sizing.

This module is **sacred** (proposal §3, §8). Every function here is deterministic
arithmetic on ``float`` inputs. It imports nothing beyond the standard library:
no probabilistic model, no RNG, no network, no LLM. A line is never auto-placed on
the strength of a number this module did not compute exactly.

Conventions
-----------
* Odds are **decimal** odds ``d`` (a winning $1 stake returns ``$d`` total).
* Implied probability of decimal odds ``d`` is ``1 / d``.
* A *middle* is modelled metric-agnostically as two overlapping legs:

  - the **over leg** wins when the result is **above** ``over_point``
    (e.g. "Over 71.5", or "Team A −3.5" in winning-margin space);
  - the **under leg** wins when the result is **below** ``under_point``
    (e.g. "Under 72.5", or "Team B +4.5").

  A middle exists only when ``over_point < under_point``; the *window* is
  ``(over_point, under_point)`` and both legs win when the result lands inside it.
  The detection engine is responsible for mapping each market type (totals,
  spreads) into this abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ArbResult",
    "BackLayResult",
    "MiddleResult",
    "arbitrage",
    "balanced_split",
    "equal_split",
    "evaluate_back_lay",
    "evaluate_middle",
    "fractional_kelly_stake",
    "implied_prob",
    "implied_sum",
    "lay_stake",
]


def implied_prob(decimal_odds: float) -> float:
    """Return the implied probability of decimal odds.

    Args:
        decimal_odds: Decimal odds ``d`` (must be > 1.0 for a real market price,
            but any positive value is accepted).

    Returns:
        ``1 / decimal_odds``.

    Raises:
        ValueError: If ``decimal_odds`` is not strictly positive.
    """
    if decimal_odds <= 0:
        raise ValueError(f"decimal_odds must be > 0, got {decimal_odds!r}")
    return 1.0 / decimal_odds


def implied_sum(odds: tuple[float, ...] | list[float]) -> float:
    """Return the sum of implied probabilities across a set of outcomes.

    For a complete set of mutually exclusive outcomes this is the "book sum":
    ``< 1`` means an arbitrage exists, ``> 1`` means the bookmaker's margin.

    Args:
        odds: Decimal odds for each outcome.

    Returns:
        ``sum(1 / d for d in odds)``.

    Raises:
        ValueError: If ``odds`` is empty.
    """
    if not odds:
        raise ValueError("odds must contain at least one price")
    return sum(implied_prob(d) for d in odds)


# ─────────────────────────────────────────────────────────────────────────────
#  Arbitrage
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ArbResult:
    """Outcome of an arbitrage evaluation across N opposing outcomes.

    Attributes:
        odds: The decimal odds considered, one per outcome.
        implied_sum: ``sum(1 / d)``. An arb exists iff this is ``< 1``.
        margin: ``1 - implied_sum``. Positive means a guaranteed profit.
        total_stake: The total stake distributed across the legs.
        stakes: Stake per outcome, in the same order as ``odds``. Sums to
            ``total_stake``.
        guaranteed_return: The return locked in regardless of which outcome wins
            (``total_stake / implied_sum``).
        profit: ``guaranteed_return - total_stake``.
    """

    odds: tuple[float, ...]
    implied_sum: float
    margin: float
    total_stake: float
    stakes: tuple[float, ...]
    guaranteed_return: float
    profit: float

    @property
    def is_arbitrage(self) -> bool:
        """True when the book sum is below 1 (a profit is locked in)."""
        return self.margin > 0.0

    @property
    def roi(self) -> float:
        """Profit as a fraction of total stake."""
        return self.profit / self.total_stake if self.total_stake else 0.0


def arbitrage(odds: tuple[float, ...] | list[float], total_stake: float = 1.0) -> ArbResult:
    """Evaluate an N-way arbitrage and compute the stake split.

    Backing every outcome with stakes proportional to its implied probability
    locks in the same return ``total_stake / S`` whatever the result, where
    ``S = sum(1 / d)``. This is profitable iff ``S < 1``.

    Args:
        odds: Decimal odds, one per mutually exclusive outcome (2-way for a
            head-to-head, but any N ≥ 2 is supported).
        total_stake: Total amount to distribute across the legs.

    Returns:
        An :class:`ArbResult`. Check :attr:`ArbResult.is_arbitrage` before acting.

    Raises:
        ValueError: If fewer than two odds are supplied or ``total_stake`` < 0.
    """
    if len(odds) < 2:
        raise ValueError("arbitrage needs at least two opposing outcomes")
    if total_stake < 0:
        raise ValueError(f"total_stake must be >= 0, got {total_stake!r}")
    s = implied_sum(odds)
    stakes = tuple(total_stake * implied_prob(d) / s for d in odds)
    guaranteed_return = total_stake / s
    return ArbResult(
        odds=tuple(odds),
        implied_sum=s,
        margin=1.0 - s,
        total_stake=total_stake,
        stakes=stakes,
        guaranteed_return=guaranteed_return,
        profit=guaranteed_return - total_stake,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Stake splits for a two-leg middle
# ─────────────────────────────────────────────────────────────────────────────
def equal_split(total_stake: float) -> tuple[float, float]:
    """Split a total stake equally between the two legs.

    Args:
        total_stake: Total amount to stake.

    Returns:
        ``(stake_over, stake_under)``, each ``total_stake / 2``.
    """
    half = total_stake / 2.0
    return half, half


def balanced_split(total_stake: float, over_odds: float, under_odds: float) -> tuple[float, float]:
    """Split a total stake so the two non-middle outcomes pay out equally.

    With this split, ``stake_over * over_odds == stake_under * under_odds``, so a
    miss on either side returns the same amount. This collapses the two
    non-middle results into a single number, which is why it is the default: the
    middle's expected value then depends only on the probability of landing in
    the window (see :func:`evaluate_middle`).

    Args:
        total_stake: Total amount to stake.
        over_odds: Decimal odds of the over leg.
        under_odds: Decimal odds of the under leg.

    Returns:
        ``(stake_over, stake_under)`` summing to ``total_stake``.

    Raises:
        ValueError: If either price is not strictly positive.
    """
    if over_odds <= 0 or under_odds <= 0:
        raise ValueError("odds must be > 0")
    denom = over_odds + under_odds
    stake_over = total_stake * under_odds / denom
    stake_under = total_stake * over_odds / denom
    return stake_over, stake_under


def fractional_kelly_stake(
    bankroll: float,
    kelly_fraction: float,
    edge_per_unit: float,
) -> float:
    """Size a *total* stake as an edge-proportional fraction of bankroll.

    This is a deliberately conservative, clearly-bounded interpretation of
    "fractional Kelly" rather than the full Kelly criterion (which needs a
    well-defined per-bet payoff distribution the two-leg middle does not cleanly
    provide). The stake scales linearly with the position's expected value per
    unit staked and is capped at ``kelly_fraction`` of bankroll. Negative-edge
    positions get zero stake.

    Args:
        bankroll: Available bankroll.
        kelly_fraction: Fraction of Kelly to apply (0..1); also the hard cap on
            the fraction of bankroll risked.
        edge_per_unit: Expected value per unit of total stake (i.e. ``ev /
            total_stake`` from a unit-stake evaluation). Typically small.

    Returns:
        The suggested total stake, in the same units as ``bankroll``. Never
        negative, never more than ``kelly_fraction * bankroll``.
    """
    if bankroll <= 0 or kelly_fraction <= 0 or edge_per_unit <= 0:
        return 0.0
    fraction = min(kelly_fraction, kelly_fraction * edge_per_unit)
    return max(0.0, bankroll * min(fraction, kelly_fraction))


# ─────────────────────────────────────────────────────────────────────────────
#  Middle evaluation
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class MiddleResult:
    """Outcome of evaluating a two-leg middle.

    All profit/loss figures are **net** (return minus total stake) in the same
    currency unit as ``total_stake``.

    Attributes:
        over_point: Threshold above which the over leg wins.
        under_point: Threshold below which the under leg wins.
        width: ``under_point - over_point``; the size of the middle window.
            Positive means a genuine middle.
        over_odds: Decimal odds of the over leg.
        under_odds: Decimal odds of the under leg.
        total_stake: Total amount staked across both legs.
        stake_over: Stake on the over leg.
        stake_under: Stake on the under leg.
        pl_low: Net P/L when the result falls **below** the window (only the
            under leg wins).
        pl_high: Net P/L when the result falls **above** the window (only the
            over leg wins).
        pl_middle: Net P/L when the result lands **inside** the window (both
            legs win).
        worst_non_middle: ``min(pl_low, pl_high)`` — the guaranteed worst case
            if the middle misses.
        hit_rate: Assumed probability of landing in the window.
        ev: Expected value, ``hit_rate * pl_middle + (1 - hit_rate) *
            worst_non_middle``. This uses the *worst* non-middle outcome, so it
            is a conservative lower bound in general and **exact** under a
            balanced split (where ``pl_low == pl_high``).
    """

    over_point: float
    under_point: float
    width: float
    over_odds: float
    under_odds: float
    total_stake: float
    stake_over: float
    stake_under: float
    pl_low: float
    pl_high: float
    pl_middle: float
    worst_non_middle: float
    hit_rate: float
    ev: float

    @property
    def has_middle(self) -> bool:
        """True when the legs actually overlap (a real middle window exists)."""
        return self.width > 0.0

    @property
    def is_risk_free(self) -> bool:
        """True when even the worst non-middle outcome breaks even or profits.

        Such a middle is simultaneously an arbitrage: you cannot lose, and you
        win extra whenever the result lands in the window.
        """
        return self.worst_non_middle >= 0.0

    @property
    def ev_roi(self) -> float:
        """Expected value as a fraction of total stake."""
        return self.ev / self.total_stake if self.total_stake else 0.0


def evaluate_middle(
    *,
    over_point: float,
    over_odds: float,
    under_point: float,
    under_odds: float,
    total_stake: float,
    hit_rate: float,
    mode: str = "balanced",
) -> MiddleResult:
    """Evaluate a two-leg middle and its stake split.

    The result is reported even when the legs do not overlap
    (``width <= 0``); callers should check :attr:`MiddleResult.has_middle`. This
    keeps the function total and side-effect free for the engine to filter.

    Args:
        over_point: Threshold above which the over leg wins (e.g. 71.5).
        over_odds: Decimal odds of the over leg.
        under_point: Threshold below which the under leg wins (e.g. 72.5).
        under_odds: Decimal odds of the under leg.
        total_stake: Total amount to stake across both legs.
        hit_rate: Probability the result lands inside the window, in ``[0, 1]``.
        mode: Stake-split strategy — ``"balanced"`` (default; equalise the two
            non-middle outcomes) or ``"equal"`` (split 50/50). Total-stake
            sizing (e.g. fractional Kelly) is a separate concern handled by the
            caller via :func:`fractional_kelly_stake`.

    Returns:
        A :class:`MiddleResult`.

    Raises:
        ValueError: If odds are not positive, ``mode`` is unknown, or
            ``hit_rate`` is outside ``[0, 1]``.
    """
    if over_odds <= 0 or under_odds <= 0:
        raise ValueError("odds must be > 0")
    if not 0.0 <= hit_rate <= 1.0:
        raise ValueError(f"hit_rate must be in [0, 1], got {hit_rate!r}")

    if mode == "equal":
        stake_over, stake_under = equal_split(total_stake)
    elif mode == "balanced":
        stake_over, stake_under = balanced_split(total_stake, over_odds, under_odds)
    else:
        raise ValueError(f"unknown stake mode {mode!r} (use 'balanced' or 'equal')")

    return_over = stake_over * over_odds
    return_under = stake_under * under_odds
    pl_low = return_under - total_stake
    pl_high = return_over - total_stake
    pl_middle = return_over + return_under - total_stake
    worst_non_middle = min(pl_low, pl_high)
    ev = hit_rate * pl_middle + (1.0 - hit_rate) * worst_non_middle

    return MiddleResult(
        over_point=over_point,
        under_point=under_point,
        width=under_point - over_point,
        over_odds=over_odds,
        under_odds=under_odds,
        total_stake=total_stake,
        stake_over=stake_over,
        stake_under=stake_under,
        pl_low=pl_low,
        pl_high=pl_high,
        pl_middle=pl_middle,
        worst_non_middle=worst_non_middle,
        hit_rate=hit_rate,
        ev=ev,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Back-and-lay (the exchange / "lay" strategy)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class BackLayResult:
    """Outcome of backing a selection at a bookmaker and laying it on an exchange.

    Backing at decimal odds ``back_odds`` for ``back_stake`` and laying the *same*
    selection on the exchange at ``lay_odds`` (with ``commission`` charged on net
    exchange winnings) at the equalising lay stake gives the **same** net profit
    whether the selection wins or loses — a market-neutral position. It is a
    genuine value position when that locked profit is ``>= 0`` (it happens when the
    bookmaker's back price is enough above the exchange lay price).

    Attributes:
        back_odds: Decimal odds taken at the bookmaker.
        lay_odds: Decimal odds laid on the exchange.
        commission: Exchange commission on net winnings, as a fraction in [0, 1).
        back_stake: Stake placed at the bookmaker.
        lay_stake: Equalising stake laid on the exchange.
        lay_liability: Amount risked on the lay (``lay_stake * (lay_odds - 1)``).
        profit_if_win: Net profit if the selection wins.
        profit_if_lose: Net profit if the selection loses (equals ``profit_if_win``).
    """

    back_odds: float
    lay_odds: float
    commission: float
    back_stake: float
    lay_stake: float
    lay_liability: float
    profit_if_win: float
    profit_if_lose: float

    @property
    def guaranteed_profit(self) -> float:
        """The locked-in profit (the worse of the two outcomes)."""
        return min(self.profit_if_win, self.profit_if_lose)

    @property
    def is_value(self) -> bool:
        """True when the position locks in a non-negative profit."""
        return self.guaranteed_profit >= 0.0

    @property
    def roi(self) -> float:
        """Guaranteed profit as a fraction of the back stake."""
        return self.guaranteed_profit / self.back_stake if self.back_stake else 0.0


def lay_stake(back_stake: float, back_odds: float, lay_odds: float, commission: float = 0.0) -> float:
    """Return the lay stake that equalises the win/lose outcomes.

    Args:
        back_stake: Stake placed at the bookmaker.
        back_odds: Decimal back odds.
        lay_odds: Decimal lay odds.
        commission: Exchange commission on net winnings, in ``[0, 1)``.

    Returns:
        ``back_stake * back_odds / (lay_odds - commission)``.

    Raises:
        ValueError: If ``lay_odds - commission`` is not positive.
    """
    denom = lay_odds - commission
    if denom <= 0:
        raise ValueError("lay_odds - commission must be > 0")
    return back_stake * back_odds / denom


def evaluate_back_lay(
    *,
    back_odds: float,
    lay_odds: float,
    back_stake: float,
    commission: float = 0.0,
) -> BackLayResult:
    """Evaluate a back-at-bookmaker / lay-on-exchange position.

    Args:
        back_odds: Decimal odds taken at the bookmaker (> 1).
        lay_odds: Decimal odds laid on the exchange (> 1).
        back_stake: Stake placed at the bookmaker.
        commission: Exchange commission on net winnings, in ``[0, 1)``.

    Returns:
        A :class:`BackLayResult`. Check :attr:`BackLayResult.is_value`.

    Raises:
        ValueError: If odds are not > 1 or commission is outside ``[0, 1)``.
    """
    if back_odds <= 1.0 or lay_odds <= 1.0:
        raise ValueError("decimal odds must be > 1")
    if not 0.0 <= commission < 1.0:
        raise ValueError("commission must be in [0, 1)")
    ls = lay_stake(back_stake, back_odds, lay_odds, commission)
    liability = ls * (lay_odds - 1.0)
    profit_if_win = back_stake * (back_odds - 1.0) - liability
    profit_if_lose = ls * (1.0 - commission) - back_stake
    return BackLayResult(
        back_odds=back_odds,
        lay_odds=lay_odds,
        commission=commission,
        back_stake=back_stake,
        lay_stake=ls,
        lay_liability=liability,
        profit_if_win=profit_if_win,
        profit_if_lose=profit_if_lose,
    )
