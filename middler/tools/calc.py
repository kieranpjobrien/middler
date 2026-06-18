"""Manual middle / arb / back-lay calculator.

For lines you read off bookie sites by hand (e.g. golf player score over/unders,
which no odds API carries). Same deterministic maths the engine uses — one source
of truth, so a hand calc and an auto-detected one never disagree.

Examples::

    uv run middler-calc middle --over 71.5 --over-odds 1.91 --under 73.5 --under-odds 1.95
    uv run middler-calc backlay --back 81 --lay 34 --commission 0.05
    uv run middler-calc arb --odds 2.10 2.10
"""

from __future__ import annotations

import argparse

from middler.detection.maths import arbitrage, evaluate_back_lay, evaluate_middle


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _middle(args: argparse.Namespace) -> None:
    m = evaluate_middle(
        over_point=args.over,
        over_odds=args.over_odds,
        under_point=args.under,
        under_odds=args.under_odds,
        total_stake=args.stake,
        hit_rate=args.hit_rate,
        mode=args.mode,
    )
    print(f"MIDDLE - Over {args.over:g} @ {args.over_odds:g}  +  Under {args.under:g} @ {args.under_odds:g}")
    if not m.has_middle:
        print(f"  WARNING: no overlap (Over {args.over:g} >= Under {args.under:g}) - this is not a middle.")
        return
    inside = [n for n in range(int(args.over) + 1, int(args.under) + 1) if args.over < n < args.under]
    landing = ", ".join(str(n) for n in inside) if inside else "-"
    print(f"  Window {args.over:g}-{args.under:g} ({m.width:g} pts) -> lands on {landing} = both win")
    print(f"  Stake {_money(args.stake)} ({args.mode} split):")
    print(f"    Over  {args.over:g} @ {args.over_odds:g} -> {_money(m.stake_over)}")
    print(f"    Under {args.under:g} @ {args.under_odds:g} -> {_money(m.stake_under)}")
    print(f"  Both win:     {_money(m.pl_middle)}")
    print(f"  Miss (worst): {_money(m.worst_non_middle)}")
    print(f"  EV @ {args.hit_rate * 100:g}% hit-rate: {_money(m.ev)} ({m.ev_roi * 100:.2f}%)")
    print(f"  Risk-free: {'yes' if m.is_risk_free else 'no'}")


def _backlay(args: argparse.Namespace) -> None:
    bl = evaluate_back_lay(back_odds=args.back, lay_odds=args.lay, back_stake=args.stake, commission=args.commission)
    print(f"BACK-LAY - back @ {args.back:g}  +  lay @ {args.lay:g} ({args.commission * 100:g}% commission)")
    print(f"  Back stake {_money(args.stake)} -> lay {_money(bl.lay_stake)} (liability {_money(bl.lay_liability)})")
    print(
        f"  Locked profit: {_money(bl.guaranteed_profit)} ({bl.roi * 100:.2f}%) {'[risk-free]' if bl.is_value else '[not value]'}"
    )


def _arb(args: argparse.Namespace) -> None:
    r = arbitrage(args.odds, total_stake=args.stake)
    print(f"ARB - odds {', '.join(f'{o:g}' for o in args.odds)} (stake {_money(args.stake)})")
    print(f"  Book sum {r.implied_sum:.4f}, margin {r.margin * 100:.2f}%")
    print(f"  Stakes: {', '.join(_money(s) for s in r.stakes)}")
    verdict = (
        f"profit {_money(r.profit)} ({r.roi * 100:.2f}%)" if r.is_arbitrage else "NOT an arbitrage (book sum >= 1)"
    )
    print(f"  Guaranteed return {_money(r.guaranteed_return)} -> {verdict}")


def main() -> None:
    """CLI entry point for the manual calculator."""
    parser = argparse.ArgumentParser(prog="middler-calc", description="Manual middle / arb / back-lay calculator.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("middle", help="two overlapping over/under lines across books")
    m.add_argument("--over", type=float, required=True, help="the over line, e.g. 71.5")
    m.add_argument("--over-odds", type=float, required=True, dest="over_odds")
    m.add_argument("--under", type=float, required=True, help="the under line, e.g. 73.5")
    m.add_argument("--under-odds", type=float, required=True, dest="under_odds")
    m.add_argument("--stake", type=float, default=100.0)
    m.add_argument("--mode", default="balanced", choices=["balanced", "equal"])
    m.add_argument("--hit-rate", type=float, default=0.06, dest="hit_rate")
    m.set_defaults(func=_middle)

    b = sub.add_parser("backlay", help="back at a bookie, lay on the exchange")
    b.add_argument("--back", type=float, required=True, help="bookie back odds")
    b.add_argument("--lay", type=float, required=True, help="exchange lay odds")
    b.add_argument("--stake", type=float, default=100.0, help="back stake")
    b.add_argument("--commission", type=float, default=0.05)
    b.set_defaults(func=_backlay)

    a = sub.add_parser("arb", help="back every outcome across books")
    a.add_argument("--odds", type=float, nargs="+", required=True, help="decimal odds, one per outcome")
    a.add_argument("--stake", type=float, default=100.0)
    a.set_defaults(func=_arb)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
