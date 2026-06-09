"""Client + normaliser for **odds-api.io** — the free high-frequency feed.

A second source behind the :class:`~middler.ingest.feed.Feed` protocol (proposal
§4.3). Its free tier allows ~100 requests/hour, making it the workhorse for
frequent polling once The Odds API's monthly credits run thin.

Its JSON differs from The Odds API, so this module owns its own normaliser into
the common :class:`~middler.models.Event` schema. Verified response shape
(``GET /odds?eventId=...``)::

    {
        "id": 123456,
        "home": "Man United",
        "away": "Liverpool",
        "date": "2025-10-15T15:00:00Z",
        "status": "pending",
        "bookmakers": {
            "Bet365": [
                {"name": "ML", "odds": [{"home": "2.10", "draw": "3.40", "away": "3.20"}]},
                {"name": "Asian Handicap", "odds": [{"hdp": -0.5, "home": "1.95", "away": "1.85"}]},
                {"name": "Over/Under", "odds": [{"max": 2.5, "over": "1.90", "under": "1.90"}]},
            ]
        },
    }

Note: ``bookmakers`` is a *dict* (book → markets); prices are *strings*; the
handicap is a single ``hdp`` on the home side; the total line is ``max``.
"""

from __future__ import annotations

from typing import Any

import httpx

from middler.ingest.normaliser import parse_commence
from middler.logging_setup import get_logger
from middler.models import BookMarket, Event, Outcome

log = get_logger(__name__)

BASE_URL = "https://api.odds-api.io/v3"

# Map odds-api.io market display names → our market keys.
MARKET_ALIASES = {
    "ml": "h2h",
    "moneyline": "h2h",
    "1x2": "h2h",
    "h2h": "h2h",
    "match winner": "h2h",
    "asian handicap": "spreads",
    "handicap": "spreads",
    "spreads": "spreads",
    "point spread": "spreads",
    "over/under": "totals",
    "totals": "totals",
    "total": "totals",
    "goals over/under": "totals",
}


def _book_key(display_name: str) -> str:
    """Normalise a display name (``"Bet365"``) to a stable key (``"bet365"``)."""
    return display_name.lower().replace(" ", "").replace("-", "")


def _f(value: Any) -> float | None:
    """Parse a (possibly string) odds value to float, or None if unusable."""
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _outcomes_for(market_key: str, entry: dict[str, Any], home: str, away: str) -> list[Outcome]:
    """Build outcomes for one odds entry, in the common schema."""
    outcomes: list[Outcome] = []
    if market_key == "h2h":
        for key, name in (("home", home), ("away", away), ("draw", "Draw")):
            price = _f(entry.get(key))
            if price is not None:
                outcomes.append(Outcome(name=name, price=price, point=None))
    elif market_key == "spreads":
        hdp = entry.get("hdp")
        if hdp is not None:
            home_price, away_price = _f(entry.get("home")), _f(entry.get("away"))
            if home_price is not None:
                outcomes.append(Outcome(name=home, price=home_price, point=float(hdp)))
            if away_price is not None:
                outcomes.append(Outcome(name=away, price=away_price, point=-float(hdp)))
    elif market_key == "totals":
        line = entry.get("max")
        if line is not None:
            over_price, under_price = _f(entry.get("over")), _f(entry.get("under"))
            if over_price is not None:
                outcomes.append(Outcome(name="Over", price=over_price, point=float(line)))
            if under_price is not None:
                outcomes.append(Outcome(name="Under", price=under_price, point=float(line)))
    return outcomes


def normalise_io_event(raw: dict[str, Any], sport_key: str) -> Event:
    """Convert one odds-api.io event object into an :class:`Event`.

    Args:
        raw: A single event object from ``/odds`` or ``/events``.
        sport_key: The sport this event was fetched under (the response may not
            echo it).

    Returns:
        An :class:`Event` with all recognised markets across all books attached.
    """
    home = str(raw.get("home", ""))
    away = str(raw.get("away", ""))
    book_markets: list[BookMarket] = []
    for book_name, markets in (raw.get("bookmakers") or {}).items():
        key = _book_key(str(book_name))
        for market in markets:
            market_key = MARKET_ALIASES.get(str(market.get("name", "")).lower())
            if market_key is None:
                continue
            last_update = market.get("updatedAt")
            for entry in market.get("odds", []):
                outcomes = _outcomes_for(market_key, entry, home, away)
                if outcomes:
                    book_markets.append(
                        BookMarket(
                            bookmaker=key,
                            market_key=market_key,
                            outcomes=outcomes,
                            last_update=parse_commence(last_update) if last_update else None,
                        )
                    )
    return Event(
        id=str(raw["id"]),
        sport_key=sport_key,
        commence_time=parse_commence(raw["date"]),
        home_team=home or None,
        away_team=away or None,
        book_markets=book_markets,
    )


class OddsApiIoClient:
    """Thin synchronous wrapper over the odds-api.io v3 API."""

    def __init__(self, api_key: str, region: str = "au", timeout: float = 20.0) -> None:
        """Initialise the client.

        Args:
            api_key: odds-api.io API key (sent as the ``apiKey`` query param).
            region: Bookmaker region (``"au"``).
            timeout: Per-request timeout in seconds.
        """
        self._key = api_key
        self.region = region
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def __enter__(self) -> OddsApiIoClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        resp = self._client.get(path, params={**params, "apiKey": self._key})
        resp.raise_for_status()
        return resp.json()

    def get_sports(self) -> list[dict[str, Any]]:
        """List available sports (and their slugs)."""
        return list(self._get("/sports", {}))

    def get_events(self, sport_slug: str) -> list[dict[str, Any]]:
        """List upcoming events for a sport slug."""
        return list(self._get("/events", {"sport": sport_slug}))

    def get_odds(self, event_ids: list[str], bookmakers: list[str] | None = None) -> list[Event]:
        """Fetch and normalise odds for one or more events.

        Args:
            event_ids: odds-api.io event ids.
            bookmakers: Restrict to these book keys (optional).

        Returns:
            Normalised :class:`Event` objects (sport_key left blank — set by the
            caller that knows which sport it queried).
        """
        params: dict[str, Any] = {"regions": self.region}
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)
        if len(event_ids) == 1:
            params["eventId"] = event_ids[0]
            raw = self._get("/odds", params)
            events = [raw] if isinstance(raw, dict) else list(raw)
        else:
            params["eventIds"] = ",".join(event_ids)
            raw = self._get("/odds/multi", params)
            events = list(raw)
        return [normalise_io_event(ev, sport_key="") for ev in events]
