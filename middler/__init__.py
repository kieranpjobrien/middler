"""middler — pre-match betting middling & arbitrage detector for AU bookmakers.

The detection and stake-sizing maths (``middler.detection``) is deterministic
arithmetic by design: no probabilistic model, RNG, or LLM ever touches a number
that has money riding on it (proposal §3, §8).
"""

__version__ = "0.1.0"
