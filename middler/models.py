"""Domain models shared across the system.

All datetimes are timezone-aware **UTC** (proposal §4.2). Convert to Sydney time
only at the display edge (the Telegram alert and the HTML report).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EventStatus(StrEnum):
    """Lifecycle state of a fixture (proposal §4.2)."""

    SCHEDULED = "scheduled"  # known, but outside the active polling window
    ACTIVE = "active"  # inside the window; polled on a ramping cadence
    LIVE = "live"  # commenced — polling suspended (no in-play betting in AU)
    SETTLED = "settled"  # finished — retained in history, dropped from polling


class Outcome(BaseModel):
    """A single priced selection within a bookmaker's market."""

    name: str
    price: float  # decimal odds
    point: float | None = None  # the line, e.g. 72.5 (None for head-to-head)


class BookMarket(BaseModel):
    """One bookmaker's prices for one market on one event."""

    bookmaker: str  # provider key, e.g. "sportsbet"
    market_key: str  # "h2h" | "totals" | "spreads"
    outcomes: list[Outcome]
    last_update: datetime | None = None


class Event(BaseModel):
    """A fixture with every bookmaker's markets attached."""

    id: str
    sport_key: str
    sport_title: str | None = None
    commence_time: datetime
    home_team: str | None = None
    away_team: str | None = None
    status: EventStatus = EventStatus.SCHEDULED
    book_markets: list[BookMarket] = Field(default_factory=list)

    def is_live(self, now: datetime) -> bool:
        """Return True once the event has commenced (cannot bet in-play in AU)."""
        return now >= self.commence_time


class OddsQuote(BaseModel):
    """A single normalised, flattened odds observation — the atom of history.

    One row per (event, bookmaker, market, outcome) at one observation time. This
    is what the recorder writes to DuckDB and what the detection engine consumes.
    """

    event_id: str
    sport_key: str
    commence_time: datetime
    bookmaker: str
    market_key: str
    outcome_name: str
    point: float | None
    price: float
    observed_at: datetime


class OpportunityLeg(BaseModel):
    """One leg of a detected opportunity, with its suggested stake."""

    bookmaker: str
    market_key: str
    outcome_name: str
    side: str  # "over" | "under" | "back"
    point: float | None
    price: float
    stake: float
    deep_link: str | None = None  # populated by the alerter


class Opportunity(BaseModel):
    """A detected middle or arbitrage, ready to record, alert, and report.

    Metric fields not relevant to ``kind`` stay ``None`` (e.g. ``width`` is a
    middle concept; ``margin`` is an arb concept). Flat by design so it persists
    cleanly to DuckDB and renders directly in the HTML report.
    """

    kind: str  # "arb" | "middle"
    event_id: str
    sport_key: str
    commence_time: datetime
    market_key: str
    home_team: str | None = None
    away_team: str | None = None
    legs: list[OpportunityLeg]
    total_stake: float

    # Arb metrics
    margin: float | None = None
    profit: float | None = None
    roi: float | None = None

    # Middle metrics
    width: float | None = None
    ev: float | None = None
    ev_roi: float | None = None
    hit_rate: float | None = None
    worst_case: float | None = None
    pl_middle: float | None = None
    is_risk_free: bool = False

    reference_verified: bool = False  # passed the sharp-book sanity filter
    observed_at: datetime

    @property
    def signature(self) -> str:
        """A stable id for de-duplication and alert throttling.

        Built from the kind, event, market, and each leg's book/outcome/point —
        but **not** the price, so the same structural opportunity is recognised
        across polls even as the odds drift slightly.
        """
        parts = [self.kind, self.event_id, self.market_key]
        for leg in sorted(self.legs, key=lambda x: (x.bookmaker, x.outcome_name, x.point or 0.0)):
            parts.append(f"{leg.bookmaker}:{leg.outcome_name}:{leg.point}")
        digest = hashlib.sha1("|".join(parts).encode()).hexdigest()  # noqa: S324 - id only, not security
        return digest[:16]
