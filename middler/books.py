"""Bookmaker-key canonicalisation.

Different feeds spell the same book differently — The Odds API says
``betfair_ex_au`` and ``pointsbetau``; odds-api.io says ``Betfair`` and
``PointsBet``. To merge feeds without double-counting a book (which would
manufacture a fake arb out of one bookmaker's two prices), every key is reduced
to one canonical form. Kept deliberately neutral (no detection/IO imports) so
both the engine and the merge layer can use it.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]")

# Explicit canonical forms for books whose names don't reduce cleanly — in
# particular the sharp references, whose identity must stay stable across feeds.
_CANONICAL = {
    "betfair": "betfair",
    "betfairexau": "betfair",
    "betfairexchange": "betfair",
    "betfairex": "betfair",
    "pinnacle": "pinnacle",
    "pinnaclesports": "pinnacle",
    "pointsbet": "pointsbet",
    "ladbrokes": "ladbrokes",
    "bet365": "bet365",
    "bet365nolatency": "bet365",
    "sportsbet": "sportsbet",
    "tab": "tab",
    "tabtouch": "tabtouch",
    "neds": "neds",
    "unibet": "unibet",
    "betr": "betr",
    "playup": "playup",
}


def canonical_book(key: str) -> str:
    """Reduce a bookmaker key to a stable canonical form.

    Args:
        key: A feed-specific bookmaker key or display name.

    Returns:
        A lowercase alphanumeric canonical key (e.g. ``betfair_ex_au`` and
        ``Betfair`` both → ``"betfair"``).
    """
    reduced = _NON_ALNUM.sub("", key.lower())
    if reduced in _CANONICAL:
        return _CANONICAL[reduced]
    # Drop a trailing AU region suffix, then retry the explicit map.
    if reduced.endswith("au") and len(reduced) > 4:
        trimmed = reduced[:-2]
        return _CANONICAL.get(trimmed, trimmed)
    return reduced
