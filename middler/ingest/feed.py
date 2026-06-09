"""The feed abstraction.

The system is built against a single ``Feed`` protocol so additional providers
(odds-api.io, OddsPapi — proposal §4.3) can be added without touching the
scheduler or engine. The Odds API is the reference implementation; a new feed
just needs to return raw event objects in the same shape the normaliser expects,
or supply its own normaliser that yields :class:`~middler.models.Event` objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class Feed(Protocol):
    """A source of upcoming fixtures and their odds."""

    def get_events(self, sport_key: str) -> list[dict[str, Any]]:
        """Return upcoming events for a sport (cheap/free discovery)."""
        ...

    def get_odds(
        self,
        sport_key: str,
        markets: list[str],
        *,
        commence_from: datetime | None = None,
        commence_to: datetime | None = None,
        event_ids: list[str] | None = None,
        bookmakers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return odds for a sport, optionally windowed and targeted."""
        ...
