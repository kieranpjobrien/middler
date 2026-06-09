"""API call budgeting — stay inside the free tiers (proposal §4.3).

The free tiers are tight: The Odds API gives **500 credits/month** and a single
team-sport ``/odds`` call (h2h+totals+spreads, one region) costs **3 credits** —
about five calls a day for a whole month. odds-api.io allows 100 requests/hour;
OddsPapi 250/month. Without a guard the scheduler would exhaust a month's credits
in well under a day.

:class:`BudgetGuard` caps calls per feed (per-hour and/or per-day sliding
windows) and, for The Odds API, also stops once the credit balance the API itself
reports drops below a reserve. State is persisted to a small JSON file so a
restart doesn't reset the windows.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class BudgetGuard:
    """Caps API calls per feed to stay within free tiers, persisted across restarts."""

    def __init__(self, state_path: str | Path, caps: dict[str, dict[str, int | None]]) -> None:
        """Initialise the guard.

        Args:
            state_path: Where to persist call timestamps and credit balances.
            caps: ``{feed: {"per_hour": int|None, "per_day": int|None}}``.
        """
        self.state_path = Path(state_path)
        self.caps = caps
        self._calls: dict[str, list[float]] = {}
        self._remaining: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._calls = {k: list(v) for k, v in data.get("calls", {}).items()}
            self._remaining = dict(data.get("remaining", {}))

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"calls": self._calls, "remaining": self._remaining}), encoding="utf-8")

    def _prune(self, feed: str, now: float) -> list[float]:
        kept = [t for t in self._calls.get(feed, []) if now - t < 86400]
        self._calls[feed] = kept
        return kept

    def allow(self, feed: str, now: float | None = None, min_reserve: int | None = None) -> bool:
        """Return True if another call to ``feed`` is within budget right now.

        Args:
            feed: Feed key (e.g. ``"the_odds_api"``).
            now: Current epoch seconds (defaults to wall clock).
            min_reserve: For credit-metered feeds, refuse if the last-reported
                remaining balance is below this.

        Returns:
            True if a call is permitted.
        """
        now = time.time() if now is None else now
        ts = self._prune(feed, now)
        cap = self.caps.get(feed, {})
        per_hour = cap.get("per_hour")
        per_day = cap.get("per_day")
        if per_hour is not None and sum(1 for t in ts if now - t < 3600) >= per_hour:
            return False
        if per_day is not None and len(ts) >= per_day:
            return False
        return not (min_reserve is not None and feed in self._remaining and self._remaining[feed] < min_reserve)

    def record(self, feed: str, now: float | None = None, remaining: int | None = None, count: int = 1) -> None:
        """Record ``count`` call(s) to ``feed`` and optionally its reported credit balance."""
        now = time.time() if now is None else now
        self._calls.setdefault(feed, []).extend([now] * count)
        if remaining is not None:
            self._remaining[feed] = remaining
        self._prune(feed, now)
        self._save()

    def remaining(self, feed: str) -> int | None:
        """Return the last-known remaining credit balance for a feed, if any."""
        return self._remaining.get(feed)


def caps_from_config(budget: object) -> dict[str, dict[str, int | None]]:
    """Build the per-feed caps mapping from a :class:`~middler.config.BudgetConfig`."""
    return {
        "the_odds_api": {"per_hour": None, "per_day": getattr(budget, "the_odds_api_per_day", 5)},
        "odds_api_io": {"per_hour": getattr(budget, "odds_api_io_per_hour", 90), "per_day": None},
        "oddspapi": {"per_hour": None, "per_day": getattr(budget, "oddspapi_per_day", 8)},
    }
