"""Client for **The Odds API** (https://the-odds-api.com) — the foundation feed.

Key facts that shape this client (proposal §4.3):

* ``/sports`` and ``/events`` cost **no** credits — used for cheap discovery.
* ``/odds`` costs ``markets × regions`` credits per call, but one call returns
  *all* games for a sport across *all* books in the region. Budget scales with
  requests, not with the number of odds observed.
* Credit balance is reported in the ``x-requests-remaining`` response header.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from middler.logging_setup import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"


class OddsApiClient:
    """Thin synchronous wrapper over The Odds API v4."""

    def __init__(self, api_key: str, region: str = "au", timeout: float = 20.0) -> None:
        """Initialise the client.

        Args:
            api_key: The Odds API key.
            region: Bookmaker region (``"au"`` for AU-licensed books).
            timeout: Per-request timeout in seconds.
        """
        self._key = api_key
        self.region = region
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout)
        self.remaining_credits: int | None = None
        self.used_credits: int | None = None

    def __enter__(self) -> OddsApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def _track_credits(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-requests-remaining")
        used = response.headers.get("x-requests-used")
        if remaining is not None:
            self.remaining_credits = int(float(remaining))
        if used is not None:
            self.used_credits = int(float(used))

    # ── free (no-credit) discovery endpoints ────────────────────────────────
    def get_sports(self, all_sports: bool = False) -> list[dict[str, Any]]:
        """List available sports. Free of credits.

        Args:
            all_sports: Include out-of-season sports when True.

        Returns:
            The decoded ``/sports`` array.
        """
        params = {"apiKey": self._key}
        if all_sports:
            params["all"] = "true"
        resp = self._client.get("/sports", params=params)
        resp.raise_for_status()
        return list(resp.json())

    def get_events(self, sport_key: str) -> list[dict[str, Any]]:
        """List upcoming events for a sport (id, teams, commence_time). Free of credits.

        Args:
            sport_key: The Odds API sport key, e.g. ``"aussierules_afl"``.

        Returns:
            The decoded ``/events`` array.
        """
        resp = self._client.get(f"/sports/{sport_key}/events", params={"apiKey": self._key})
        resp.raise_for_status()
        return list(resp.json())

    # ── odds (costs credits) ────────────────────────────────────────────────
    def get_odds(
        self,
        sport_key: str,
        markets: list[str],
        *,
        commence_from: datetime | None = None,
        commence_to: datetime | None = None,
        event_ids: list[str] | None = None,
        bookmakers: list[str] | None = None,
        odds_format: str = "decimal",
    ) -> list[dict[str, Any]]:
        """Fetch odds for a sport, windowed and optionally targeted.

        Costs ``len(markets) × 1`` credits (single region). Windowing with
        ``commence_from``/``commence_to`` and targeting with ``event_ids`` keeps
        each call cheap and relevant.

        Args:
            sport_key: The Odds API sport key.
            markets: Market keys, e.g. ``["totals", "spreads"]``.
            commence_from: Lower bound on commence time (UTC).
            commence_to: Upper bound on commence time (UTC).
            event_ids: Restrict to these event ids.
            bookmakers: Restrict to these bookmaker keys.
            odds_format: ``"decimal"`` (required by the maths) or ``"american"``.

        Returns:
            The decoded ``/odds`` response array.
        """
        params: dict[str, Any] = {
            "apiKey": self._key,
            "regions": self.region,
            "markets": ",".join(markets),
            "oddsFormat": odds_format,
            "dateFormat": "iso",
        }
        if commence_from is not None:
            params["commenceTimeFrom"] = _iso_z(commence_from)
        if commence_to is not None:
            params["commenceTimeTo"] = _iso_z(commence_to)
        if event_ids:
            params["eventIds"] = ",".join(event_ids)
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)

        resp = self._client.get(f"/sports/{sport_key}/odds", params=params)
        resp.raise_for_status()
        self._track_credits(resp)
        log.debug("odds %s markets=%s remaining=%s", sport_key, markets, self.remaining_credits)
        return list(resp.json())


def _iso_z(dt: datetime) -> str:
    """Format a datetime as UTC ``YYYY-MM-DDTHH:MM:SSZ`` (the API's expected form)."""
    utc = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
