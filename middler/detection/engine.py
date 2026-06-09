"""The detection engine — find arbs and middles across books for one event.

This is the bridge between the multi-book :class:`~middler.models.Event` and the
sacred arithmetic in :mod:`middler.detection.maths`. Its job is purely to *map*
each market type into the over/under abstraction and to filter by the configured
thresholds and the sharp-reference sanity check (proposal §4.4). It computes no
probabilities of its own.

Market → over/under mapping
---------------------------
* **totals**: ``Over P`` is an over leg with ``over_point = P``; ``Under P`` is an
  under leg with ``under_point = P``. A middle needs ``over_point < under_point``
  (e.g. Over 71.5 + Under 72.5 → result of 72 wins both).
* **spreads**: work in *home-margin* space (``home_score − away_score``). The home
  outcome at handicap ``p_h`` wins when ``margin > −p_h`` → an over leg with
  ``over_point = −p_h``. The away outcome at handicap ``p_a`` wins when
  ``margin < p_a`` → an under leg with ``under_point = p_a``.
* **h2h**: arbitrage only — back the best price for every outcome across books.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from middler.books import canonical_book
from middler.config import DetectionConfig, StakingConfig
from middler.detection.maths import (
    arbitrage,
    evaluate_back_lay,
    evaluate_middle,
    fractional_kelly_stake,
    implied_prob,
)
from middler.models import BookMarket, Event, Opportunity, OpportunityLeg


@dataclass(frozen=True, slots=True)
class _Leg:
    """An internal, maths-space view of one priced selection."""

    bookmaker: str
    name: str  # original selection name shown to the human (e.g. "Over", "Team A")
    point: float | None  # original line shown to the human (e.g. 72.5, -3.5)
    price: float
    threshold: float  # transformed point in comparison space (totals/home-margin)


def detect_opportunities(
    event: Event,
    *,
    detection: DetectionConfig,
    staking: StakingConfig,
    sharp_books: list[str],
    hit_rate_prior: dict[str, float],
    observed_at: datetime,
) -> list[Opportunity]:
    """Find all qualifying middles and arbitrages on one event.

    Args:
        event: The event with every bookmaker's markets attached.
        detection: Thresholds and stake mode.
        staking: Stake sizing (default stake, bankroll for Kelly).
        sharp_books: Bookmaker keys treated as sharp references for the sanity filter.
        hit_rate_prior: Per-market prior probability a result lands in a middle.
        observed_at: Observation timestamp (UTC) to stamp on opportunities.

    Returns:
        Opportunities sorted by attractiveness (risk-free first, then EV/margin).
    """
    opps: list[Opportunity] = []
    sharp_set = {canonical_book(b) for b in sharp_books}
    for market_key in ("h2h", "totals", "spreads"):
        books = [bm for bm in event.book_markets if bm.market_key == market_key]
        if not books:
            continue
        if market_key == "h2h":
            opps.extend(_detect_h2h_arbs(event, books, detection, staking, sharp_set, observed_at))
        else:
            opps.extend(
                _detect_over_under(event, books, market_key, detection, staking, sharp_set, hit_rate_prior, observed_at)
            )
    if any(bm.market_key in ("outrights", "outrights_lay") for bm in event.book_markets):
        opps.extend(_detect_outright_back_lay(event, detection, staking, observed_at))
    opps.sort(key=lambda o: (o.is_risk_free, o.ev or 0.0, o.roi or 0.0, o.margin or 0.0), reverse=True)
    return opps


# ── outright back-lay (golf etc.: back at a bookie, lay on the exchange) ──────
def _detect_outright_back_lay(
    event: Event,
    detection: DetectionConfig,
    staking: StakingConfig,
    observed_at: datetime,
) -> list[Opportunity]:
    """Find back-at-bookie / lay-on-Betfair value on outright (winner) markets.

    The feed supplies bookie back prices (``outrights``) and the Betfair lay
    prices (``outrights_lay``) for each runner. For every runner present in both,
    the back-lay position is evaluated; a non-negative locked-in ROI (above
    ``min_back_lay_roi``) is flagged. The lay leg is on Betfair, so the position
    is inherently exchange-verified.
    """
    back: dict[str, _Leg] = {}
    lay: dict[str, float] = {}
    for bm in event.book_markets:
        is_exchange = canonical_book(bm.bookmaker) == "betfair"
        if bm.market_key == "outrights" and not is_exchange:
            for o in bm.outcomes:
                if o.name not in back or o.price > back[o.name].price:
                    back[o.name] = _Leg(bm.bookmaker, o.name, None, o.price, 0.0)
        elif bm.market_key == "outrights_lay" and is_exchange:
            for o in bm.outcomes:
                lay[o.name] = o.price

    opps: list[Opportunity] = []
    stake = staking.default_total_stake
    for player, leg in back.items():
        lay_odds = lay.get(player)
        if lay_odds is None or lay_odds <= 1.0 or leg.price <= 1.0:
            continue
        bl = evaluate_back_lay(
            back_odds=leg.price, lay_odds=lay_odds, back_stake=stake, commission=detection.betfair_commission
        )
        if bl.roi < detection.min_back_lay_roi:
            continue
        legs = [
            OpportunityLeg(
                bookmaker=leg.bookmaker,
                market_key="outrights",
                outcome_name=player,
                side="back",
                point=None,
                price=leg.price,
                stake=round(stake, 2),
            ),
            OpportunityLeg(
                bookmaker="betfair_ex_au",
                market_key="outrights_lay",
                outcome_name=player,
                side="lay",
                point=None,
                price=lay_odds,
                stake=round(bl.lay_stake, 2),
            ),
        ]
        opps.append(
            Opportunity(
                kind="back_lay",
                event_id=event.id,
                sport_key=event.sport_key,
                commence_time=event.commence_time,
                market_key="outrights",
                home_team=event.home_team,
                away_team=event.away_team,
                legs=legs,
                total_stake=round(stake, 2),
                profit=round(bl.guaranteed_profit, 2),
                roi=bl.roi,
                is_risk_free=bl.is_value,
                reference_verified=True,
                observed_at=observed_at,
            )
        )
    opps.sort(key=lambda o: o.roi or 0.0, reverse=True)
    return opps


# ── h2h arbitrage ────────────────────────────────────────────────────────────
def _detect_h2h_arbs(
    event: Event,
    books: list[BookMarket],
    detection: DetectionConfig,
    staking: StakingConfig,
    sharp_set: set[str],
    observed_at: datetime,
) -> list[Opportunity]:
    """Back the best price for each outcome across books; flag if it arbs."""
    best: dict[str, _Leg] = {}
    for bm in books:
        for o in bm.outcomes:
            leg = _Leg(bm.bookmaker, o.name, None, o.price, 0.0)
            if o.name not in best or o.price > best[o.name].price:
                best[o.name] = leg
    if len(best) < 2:
        return []
    legs = list(best.values())
    result = arbitrage([leg.price for leg in legs], total_stake=staking.default_total_stake)
    if not result.is_arbitrage or result.margin < detection.min_arb_margin:
        return []
    verified = _verify_against_sharp(legs, books, sharp_set, detection.sharp_tolerance)
    opp_legs = [
        OpportunityLeg(
            bookmaker=leg.bookmaker,
            market_key="h2h",
            outcome_name=leg.name,
            side="back",
            point=None,
            price=leg.price,
            stake=round(stake, 2),
        )
        for leg, stake in zip(legs, result.stakes, strict=True)
    ]
    return [
        Opportunity(
            kind="arb",
            event_id=event.id,
            sport_key=event.sport_key,
            commence_time=event.commence_time,
            market_key="h2h",
            home_team=event.home_team,
            away_team=event.away_team,
            legs=opp_legs,
            total_stake=staking.default_total_stake,
            margin=result.margin,
            profit=result.profit,
            roi=result.roi,
            reference_verified=verified,
            observed_at=observed_at,
        )
    ]


# ── totals / spreads: over-under legs → arbs + middles ───────────────────────
def _over_under_legs(event: Event, books: list[BookMarket], market_key: str) -> tuple[list[_Leg], list[_Leg]]:
    """Split a market's outcomes into over legs and under legs (maths space)."""
    over_legs: list[_Leg] = []
    under_legs: list[_Leg] = []
    for bm in books:
        for o in bm.outcomes:
            if market_key == "totals":
                if o.point is None:
                    continue
                leg = _Leg(bm.bookmaker, o.name, o.point, o.price, o.point)
                (over_legs if o.name.lower().startswith("over") else under_legs).append(leg)
            else:  # spreads — needs team identity to map into home-margin space
                if o.point is None or event.home_team is None or event.away_team is None:
                    continue
                if o.name == event.home_team:
                    over_legs.append(_Leg(bm.bookmaker, o.name, o.point, o.price, -o.point))
                elif o.name == event.away_team:
                    under_legs.append(_Leg(bm.bookmaker, o.name, o.point, o.price, o.point))
    return over_legs, under_legs


def _best_by_threshold(legs: list[_Leg]) -> dict[float, _Leg]:
    """Keep only the best-priced leg at each distinct threshold."""
    best: dict[float, _Leg] = {}
    for leg in legs:
        if leg.threshold not in best or leg.price > best[leg.threshold].price:
            best[leg.threshold] = leg
    return best


def _detect_over_under(
    event: Event,
    books: list[BookMarket],
    market_key: str,
    detection: DetectionConfig,
    staking: StakingConfig,
    sharp_set: set[str],
    hit_rate_prior: dict[str, float],
    observed_at: datetime,
) -> list[Opportunity]:
    over_legs, under_legs = _over_under_legs(event, books, market_key)
    best_over = _best_by_threshold(over_legs)
    best_under = _best_by_threshold(under_legs)
    hit_rate = hit_rate_prior.get(market_key, 0.05)
    opps: list[Opportunity] = []

    for op, over in best_over.items():
        for up, under in best_under.items():
            if op < up:
                opp = _build_middle(
                    event, market_key, over, under, detection, staking, sharp_set, books, hit_rate, observed_at
                )
                if opp is not None:
                    opps.append(opp)
            elif op == up:
                opp = _build_line_arb(event, market_key, over, under, detection, staking, sharp_set, books, observed_at)
                if opp is not None:
                    opps.append(opp)
            # op > up is a reverse-gap (a region where neither leg wins) — never flag.
    return opps


def _build_middle(
    event: Event,
    market_key: str,
    over: _Leg,
    under: _Leg,
    detection: DetectionConfig,
    staking: StakingConfig,
    sharp_set: set[str],
    books: list[BookMarket],
    hit_rate: float,
    observed_at: datetime,
) -> Opportunity | None:
    width = under.threshold - over.threshold
    if width < detection.min_middle_width:
        return None
    total_stake = _stake_for_middle(over, under, detection, staking, hit_rate)
    split_mode = "equal" if detection.stake_mode == "equal" else "balanced"
    m = evaluate_middle(
        over_point=over.threshold,
        over_odds=over.price,
        under_point=under.threshold,
        under_odds=under.price,
        total_stake=total_stake,
        hit_rate=hit_rate,
        mode=split_mode,
    )
    if m.ev < detection.min_middle_ev:
        return None
    verified = _verify_against_sharp([over, under], books, sharp_set, detection.sharp_tolerance)
    legs = [
        OpportunityLeg(
            bookmaker=over.bookmaker,
            market_key=market_key,
            outcome_name=over.name,
            side="over",
            point=over.point,
            price=over.price,
            stake=round(m.stake_over, 2),
        ),
        OpportunityLeg(
            bookmaker=under.bookmaker,
            market_key=market_key,
            outcome_name=under.name,
            side="under",
            point=under.point,
            price=under.price,
            stake=round(m.stake_under, 2),
        ),
    ]
    return Opportunity(
        kind="middle",
        event_id=event.id,
        sport_key=event.sport_key,
        commence_time=event.commence_time,
        market_key=market_key,
        home_team=event.home_team,
        away_team=event.away_team,
        legs=legs,
        total_stake=round(total_stake, 2),
        width=width,
        ev=m.ev,
        ev_roi=m.ev_roi,
        hit_rate=hit_rate,
        worst_case=m.worst_non_middle,
        pl_middle=m.pl_middle,
        is_risk_free=m.is_risk_free,
        reference_verified=verified,
        observed_at=observed_at,
    )


def _build_line_arb(
    event: Event,
    market_key: str,
    over: _Leg,
    under: _Leg,
    detection: DetectionConfig,
    staking: StakingConfig,
    sharp_set: set[str],
    books: list[BookMarket],
    observed_at: datetime,
) -> Opportunity | None:
    """An arbitrage on the same line across books (e.g. Over 72.5 + Under 72.5)."""
    if over.bookmaker == under.bookmaker:
        return None  # same book can't arb against itself
    result = arbitrage([over.price, under.price], total_stake=staking.default_total_stake)
    if not result.is_arbitrage or result.margin < detection.min_arb_margin:
        return None
    verified = _verify_against_sharp([over, under], books, sharp_set, detection.sharp_tolerance)
    legs = [
        OpportunityLeg(
            bookmaker=over.bookmaker,
            market_key=market_key,
            outcome_name=over.name,
            side="over",
            point=over.point,
            price=over.price,
            stake=round(result.stakes[0], 2),
        ),
        OpportunityLeg(
            bookmaker=under.bookmaker,
            market_key=market_key,
            outcome_name=under.name,
            side="under",
            point=under.point,
            price=under.price,
            stake=round(result.stakes[1], 2),
        ),
    ]
    return Opportunity(
        kind="arb",
        event_id=event.id,
        sport_key=event.sport_key,
        commence_time=event.commence_time,
        market_key=market_key,
        home_team=event.home_team,
        away_team=event.away_team,
        legs=legs,
        total_stake=staking.default_total_stake,
        margin=result.margin,
        profit=result.profit,
        roi=result.roi,
        reference_verified=verified,
        observed_at=observed_at,
    )


# ── stake sizing helper ──────────────────────────────────────────────────────
def _stake_for_middle(
    over: _Leg, under: _Leg, detection: DetectionConfig, staking: StakingConfig, hit_rate: float
) -> float:
    """Resolve the total stake for a middle.

    For ``equal``/``balanced`` the total is the configured default. For ``kelly``
    the total is sized from bankroll against the position's per-unit edge (a
    balanced split is used to compute that edge), then capped by the helper.
    """
    if detection.stake_mode != "kelly":
        return staking.default_total_stake
    unit = evaluate_middle(
        over_point=over.threshold,
        over_odds=over.price,
        under_point=under.threshold,
        under_odds=under.price,
        total_stake=1.0,
        hit_rate=hit_rate,
        mode="balanced",
    )
    sized = fractional_kelly_stake(staking.bankroll, detection.kelly_fraction, unit.ev)
    return sized if sized > 0 else staking.default_total_stake


# ── sharp-reference sanity filter ────────────────────────────────────────────
def _verify_against_sharp(legs: list[_Leg], books: list[BookMarket], sharp_set: set[str], tolerance: float) -> bool:
    """Verify each leg's price against a sharp reference for the same selection.

    A leg is suspicious when its implied probability sits more than ``tolerance``
    *below* the sharp's (i.e. its odds are much longer than the sharp thinks they
    should be — the classic fingerprint of a stale or mistaken line). We only
    *verify* when a sharp price for the same (selection, line) exists; otherwise
    the opportunity is recorded but left unverified, and placement is refused
    (proposal §4.4: never auto-place on an unverified line).
    """
    sharp_prices: dict[tuple[str, float | None], float] = {}
    for bm in books:
        if canonical_book(bm.bookmaker) in sharp_set:
            for o in bm.outcomes:
                sharp_prices[(o.name, o.point)] = o.price
    if not sharp_prices:
        return False
    for leg in legs:
        sharp_price = sharp_prices.get((leg.name, leg.point))
        if sharp_price is None:
            return False
        if implied_prob(leg.price) < implied_prob(sharp_price) - tolerance:
            return False
    return True
