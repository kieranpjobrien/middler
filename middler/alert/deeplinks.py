"""Bookmaker deep-links for the alert buttons.

AU corporate books don't expose a stable public URL scheme for a specific event's
market, so by default we link to the book's site and let the operator navigate the
last step by hand (the bookmaker leg is always placed manually anyway — proposal
§2). If a feed later supplies real betslip links (The Odds API's paid *links*
add-on), :func:`deep_link` will prefer a per-leg URL passed in via ``override``.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from middler.models import Event

# Known AU-licensed bookmaker homepages, keyed by feed bookmaker key (and aliases).
_HOMEPAGES = {
    "sportsbet": "https://www.sportsbet.com.au",
    "tab": "https://www.tab.com.au",
    "tabtouch": "https://www.tabtouch.com.au",
    "pointsbetau": "https://pointsbet.com.au",
    "pointsbet": "https://pointsbet.com.au",
    "ladbrokesau": "https://www.ladbrokes.com.au",
    "ladbrokes": "https://www.ladbrokes.com.au",
    "neds": "https://www.neds.com.au",
    "unibet": "https://www.unibet.com.au",
    "betfair_ex_au": "https://www.betfair.com.au/exchange/plus/",
    "betfair": "https://www.betfair.com.au/exchange/plus/",
    "bet365_au": "https://www.bet365.com.au",
    "bet365": "https://www.bet365.com.au",
    "pinnacle": "https://www.pinnacle.com",
    "betr_au": "https://www.betr.com.au",
    "playup": "https://playup.com.au",
}


def deep_link(bookmaker: str, event: Event | None = None, override: str | None = None) -> str:
    """Return the best available URL to reach a bookmaker for an event.

    Args:
        bookmaker: The feed's bookmaker key.
        event: The event (used to build a search URL when no homepage is known).
        override: A real per-leg betslip URL from the feed, if available — used as-is.

    Returns:
        A URL string. Never empty.
    """
    if override:
        return override
    home = _HOMEPAGES.get(bookmaker.lower())
    if home:
        return home
    # Unknown book: a web search for the book + fixture is the safest fallback.
    teams = f"{event.home_team} {event.away_team}" if event and event.home_team else ""
    return f"https://www.google.com/search?q={quote_plus(f'{bookmaker} {teams}'.strip())}"
