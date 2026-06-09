"""Semi-automatic placement of the Betfair exchange leg (Phase 6, optional).

Money-touching and deliberately dormant: nothing here acts unless
``PLACEMENT_ENABLED=true`` *and* a Betfair key is configured *and* the line is
sharp-verified. The bookmaker leg is **always** placed by a human (proposal §2).
No probabilistic code may live here (enforced by the no-rng pre-commit hook).
"""
