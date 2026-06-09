"""Deterministic detection maths and the opportunity-finding engine.

Nothing in this package may import a probabilistic model, RNG, or LLM client.
The pre-commit hook ``no-rng-in-detection`` enforces this.
"""

from middler.detection.maths import (
    ArbResult,
    BackLayResult,
    MiddleResult,
    arbitrage,
    balanced_split,
    evaluate_back_lay,
    evaluate_middle,
    fractional_kelly_stake,
    implied_prob,
    implied_sum,
    lay_stake,
)

__all__ = [
    "ArbResult",
    "BackLayResult",
    "MiddleResult",
    "arbitrage",
    "balanced_split",
    "evaluate_back_lay",
    "evaluate_middle",
    "fractional_kelly_stake",
    "implied_prob",
    "implied_sum",
    "lay_stake",
]
