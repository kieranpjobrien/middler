"""Client + normaliser for **OddsPapi** (https://oddspapi.io) — deep cross-book.

A tertiary feed (proposal §4.3) whose strength is breadth: 300+ bookmakers per
fixture, far more than The Odds API's ~11. Its free tier is small (250
requests/month), so it's used sparingly for deep multi-book *h2h* snapshots —
ideal for catching head-to-head arbitrage a book the other feeds don't carry.

Market identity is taken from the authoritative ``/markets`` reference, never
guessed: each ``marketId`` maps to a ``marketType`` (``moneyline``/``1x2``) and
explicit outcome labels (``"1"`` = home/participant-1, ``"2"`` = away, ``"X"`` =
draw). Only those h2h market types are normalised here; totals/spreads are
deliberately left out until their outcome labels are verified live, so nothing
mis-mapped ever reaches the money maths.
"""

from __future__ import annotations

from typing import Any

import httpx

from middler.books import canonical_book
from middler.ingest.normaliser import parse_commence
from middler.logging_setup import get_logger
from middler.models import BookMarket, Event, Outcome

log = get_logger(__name__)

BASE_URL = "https://api.oddspapi.io/v4"

# OddsPapi marketType values we treat as head-to-head. "1x2" carries a draw.
H2H_MARKET_TYPES = frozenset({"moneyline", "1x2"})


def _price(outcome: dict[str, Any]) -> float | None:
    """Pull the decimal price from an OddsPapi outcome (first player entry)."""
    players = outcome.get("players") or {}
    for entry in players.values():
        price = entry.get("price")
        if price:
            try:
                value = float(price)
            except (TypeError, ValueError):
                return None
            return value if value > 1.0 else None
    return None


def normalise_oddspapi_fixture(
    raw: dict[str, Any],
    market_ref: dict[int, dict[str, Any]],
    sport_key: str,
) -> Event:
    """Convert one OddsPapi fixture's odds into an :class:`Event` (h2h only).

    Args:
        raw: A ``/odds`` fixture object (``bookmakerOdds`` nested by book → market).
        market_ref: The ``/markets`` reference: ``marketId → {market_type,
            outcomes: {outcomeId: label}}``.
        sport_key: The The-Odds-API sport key to stamp on the event.

    Returns:
        An :class:`Event` with one h2h :class:`BookMarket` per bookmaker.
    """
    p1 = str(raw.get("participant1Name") or "")
    p2 = str(raw.get("participant2Name") or "")
    label_to_name = {"1": p1, "2": p2, "X": "Draw"}
    book_markets: list[BookMarket] = []
    for book_name, book in (raw.get("bookmakerOdds") or {}).items():
        key = canonical_book(str(book_name))
        for market_id, market in (book.get("markets") or {}).items():
            mdef = market_ref.get(int(market_id)) if str(market_id).isdigit() else None
            if mdef is None or mdef.get("market_type") not in H2H_MARKET_TYPES:
                continue
            outcomes: list[Outcome] = []
            for outcome_id, outcome in (market.get("outcomes") or {}).items():
                label = mdef["outcomes"].get(int(outcome_id)) if str(outcome_id).isdigit() else None
                name = label_to_name.get(str(label))
                price = _price(outcome)
                if name and price is not None:
                    outcomes.append(Outcome(name=name, price=price, point=None))
            if len(outcomes) >= 2:
                book_markets.append(BookMarket(bookmaker=key, market_key="h2h", outcomes=outcomes))
    return Event(
        id=str(raw["fixtureId"]),
        sport_key=sport_key,
        commence_time=parse_commence(str(raw["startTime"])),
        home_team=p1 or None,
        away_team=p2 or None,
        book_markets=book_markets,
    )


class OddsPapiClient:
    """Thin synchronous wrapper over the OddsPapi v4 API."""

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        """Initialise the client.

        Args:
            api_key: OddsPapi API key (sent as the ``apiKey`` query param).
            timeout: Per-request timeout in seconds.
        """
        self._key = api_key
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._market_ref: dict[int, dict[str, Any]] | None = None

    def __enter__(self) -> OddsPapiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def _get(self, path: str, **params: Any) -> Any:
        params["apiKey"] = self._key
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def market_reference(self) -> dict[int, dict[str, Any]]:
        """Fetch (once, cached) the ``/markets`` reference for h2h market types.

        Returns:
            ``marketId → {market_type, handicap, outcomes: {outcomeId: label}}``,
            limited to the h2h market types we normalise.
        """
        if self._market_ref is None:
            ref: dict[int, dict[str, Any]] = {}
            for m in self._get("/markets"):
                if not isinstance(m, dict) or m.get("marketType") not in H2H_MARKET_TYPES:
                    continue
                ref[m["marketId"]] = {
                    "market_type": m.get("marketType"),
                    "handicap": m.get("handicap"),
                    "outcomes": {o["outcomeId"]: o["outcomeName"] for o in m.get("outcomes", [])},
                }
            self._market_ref = ref
        return self._market_ref

    def get_tournaments(self, sport_id: int) -> list[dict[str, Any]]:
        """List tournaments for an OddsPapi sport id."""
        return _items(self._get("/tournaments", sportId=sport_id))

    def get_fixtures(self, tournament_id: int) -> list[dict[str, Any]]:
        """List fixtures for a tournament."""
        return _items(self._get("/fixtures", tournamentId=tournament_id))

    def get_fixture_odds(self, fixture_id: str, sport_key: str) -> Event:
        """Fetch one fixture's odds (all books) and normalise to an h2h Event."""
        raw = self._get("/odds", fixtureId=fixture_id)
        return normalise_oddspapi_fixture(raw, self.market_reference(), sport_key)


def _items(payload: Any) -> list[dict[str, Any]]:
    """Pull the list of records from an OddsPapi response (list or wrapped)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "tournaments", "fixtures", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
