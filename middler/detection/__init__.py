"""Deterministic detection maths and the opportunity-finding engine.

Nothing in this package may import a probabilistic model, RNG, or LLM client.
The pre-commit hook ``no-rng-in-detection`` enforces this.
"""

from middler.detection.maths import (
    ArbResult,
    MiddleResult,
    arbitrage,
    balanced_split,
    evaluate_middle,
    fractional_kelly_stake,
    implied_prob,
    implied_sum,
)

__all__ = [
    "ArbResult",
    "MiddleResult",
    "arbitrage",
    "balanced_split",
    "evaluate_middle",
    "fractional_kelly_stake",
    "implied_prob",
    "implied_sum",
]
