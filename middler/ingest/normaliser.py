"""Map raw provider payloads into the common schema (:mod:`middler.models`).

The Odds API is the reference shape (proposal §4.3). Other feeds are adapted to
the same :class:`~middler.models.Event` / :class:`~middler.models.OddsQuote`
structure so the rest of the system never sees a provider-specific field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from middler.models import BookMarket, Event, EventStatus, OddsQuote, Outcome

# Markets we understand. Anything else is ignored by the normaliser.
KNOWN_MARKETS = frozenset({"h2h", "totals", "spreads"})


def parse_commence(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC datetime.

    Args:
        value: ISO-8601 string, e.g. ``"2026-06-10T09:00:00Z"``.

    Returns:
        A UTC-aware :class:`datetime`.
    """
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _parse_outcome(raw: dict[str, Any]) -> Outcome | None:
    """Parse one outcome; return None if the price is missing or non-positive."""
    price = raw.get("price")
    if price is None or price <= 0:
        return None
    return Outcome(name=str(raw["name"]), price=float(price), point=raw.get("point"))


def normalise_event(raw: dict[str, Any]) -> Event:
    """Convert one The-Odds-API event object into an :class:`Event`.

    Args:
        raw: A single element of the ``/odds`` response array.

    Returns:
        An :class:`Event` with all recognised bookmaker markets attached.
    """
    commence = parse_commence(raw["commence_time"])
    book_markets: list[BookMarket] = []
    for book in raw.get("bookmakers", []):
        last_update = book.get("last_update")
        for market in book.get("markets", []):
            if market.get("key") not in KNOWN_MARKETS:
                continue
            outcomes = [o for o in (_parse_outcome(x) for x in market.get("outcomes", [])) if o is not None]
            if not outcomes:
                continue
            book_markets.append(
                BookMarket(
                    bookmaker=str(book["key"]),
                    market_key=str(market["key"]),
                    outcomes=outcomes,
                    last_update=parse_commence(last_update) if last_update else None,
                )
            )
    return Event(
        id=str(raw["id"]),
        sport_key=str(raw["sport_key"]),
        sport_title=raw.get("sport_title"),
        commence_time=commence,
        home_team=raw.get("home_team"),
        away_team=raw.get("away_team"),
        status=EventStatus.SCHEDULED,
        book_markets=book_markets,
    )


def quotes_from_event(event: Event, observed_at: datetime) -> list[OddsQuote]:
    """Flatten an :class:`Event` into atomic :class:`OddsQuote` rows for history.

    Args:
        event: The event to flatten.
        observed_at: The observation timestamp (UTC) to stamp on each row.

    Returns:
        One :class:`OddsQuote` per (bookmaker, market, outcome).
    """
    quotes: list[OddsQuote] = []
    for bm in event.book_markets:
        for outcome in bm.outcomes:
            quotes.append(
                OddsQuote(
                    event_id=event.id,
                    sport_key=event.sport_key,
                    commence_time=event.commence_time,
                    bookmaker=bm.bookmaker,
                    market_key=bm.market_key,
                    outcome_name=outcome.name,
                    point=outcome.point,
                    price=outcome.price,
                    observed_at=observed_at,
                )
            )
    return quotes


def normalise_odds_response(
    raw_list: list[dict[str, Any]], observed_at: datetime | None = None
) -> tuple[list[Event], list[OddsQuote]]:
    """Normalise a full ``/odds`` response into events and flattened quotes.

    Args:
        raw_list: The decoded JSON array from The Odds API ``/odds`` endpoint.
        observed_at: Observation time (UTC). Defaults to now.

    Returns:
        A ``(events, quotes)`` tuple.
    """
    stamp = observed_at or datetime.now(UTC)
    events = [normalise_event(raw) for raw in raw_list]
    quotes = [q for ev in events for q in quotes_from_event(ev, stamp)]
    return events, quotes
