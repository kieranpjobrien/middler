"""Replay recorded odds history through the live detection engine (proposal §3).

The backcast reconstructs each historical *snapshot* (all quotes sharing one
``observed_at``), rebuilds the multi-book events exactly as they looked then, and
runs the very same :func:`~middler.detection.engine.detect_opportunities` used
live. Identical code path live and in hindsight → the report cannot flatter the
engine with maths it would not really use.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from middler.config import AppConfig
from middler.detection.engine import detect_opportunities
from middler.models import BookMarket, Event, Opportunity, Outcome
from middler.store.history import HistoryStore


@dataclass(slots=True)
class BackcastResult:
    """The outcome of a backcast run, ready to summarise and render."""

    opportunities: list[Opportunity] = field(default_factory=list)
    total_quotes: int = 0
    snapshots: int = 0
    events_seen: int = 0
    start: datetime | None = None
    end: datetime | None = None

    @property
    def middles(self) -> list[Opportunity]:
        return [o for o in self.opportunities if o.kind == "middle"]

    @property
    def arbs(self) -> list[Opportunity]:
        return [o for o in self.opportunities if o.kind == "arb"]

    @property
    def risk_free(self) -> list[Opportunity]:
        return [o for o in self.opportunities if o.is_risk_free]


def _reconstruct_event(event_id: str, rows: list[dict[str, object]], meta: dict[str, dict[str, object]]) -> Event:
    """Rebuild one :class:`Event` from its flat quote rows plus stored metadata."""
    grouped: dict[tuple[str, str], list[Outcome]] = defaultdict(list)
    for r in rows:
        grouped[(str(r["bookmaker"]), str(r["market_key"]))].append(
            Outcome(name=str(r["outcome_name"]), price=float(r["price"]), point=r["point"])  # type: ignore[arg-type]
        )
    book_markets = [
        BookMarket(bookmaker=book, market_key=market, outcomes=outs) for (book, market), outs in grouped.items()
    ]
    m = meta.get(event_id, {})
    first = rows[0]
    return Event(
        id=event_id,
        sport_key=str(m.get("sport_key") or first["sport_key"]),
        sport_title=m.get("sport_title"),  # type: ignore[arg-type]
        commence_time=m.get("commence_time") or first["commence_time"],  # type: ignore[arg-type]
        home_team=m.get("home_team"),  # type: ignore[arg-type]
        away_team=m.get("away_team"),  # type: ignore[arg-type]
        book_markets=book_markets,
    )


def run_backcast(store: HistoryStore, config: AppConfig) -> BackcastResult:
    """Replay all recorded history through the engine.

    Args:
        store: The history store to read quotes and event metadata from.
        config: Operating configuration (detection thresholds, staking, priors).

    Returns:
        A :class:`BackcastResult` with every opportunity the engine would have
        flagged, plus coverage metadata.
    """
    df = store.load_quotes()
    meta = store.load_events()
    result = BackcastResult(total_quotes=df.height)
    if df.height == 0:
        return result

    # snapshot time -> event_id -> rows
    snapshots: dict[datetime, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    for row in df.iter_rows(named=True):
        snapshots[row["observed_at"]][row["event_id"]].append(row)

    event_ids: set[str] = set()
    for observed_at in sorted(snapshots):
        for event_id, rows in snapshots[observed_at].items():
            event_ids.add(event_id)
            event = _reconstruct_event(event_id, rows, meta)
            result.opportunities.extend(
                detect_opportunities(
                    event,
                    detection=config.detection,
                    staking=config.staking,
                    sharp_books=config.sharp_books,
                    hit_rate_prior=config.backcast.middle_hit_rate_prior,
                    observed_at=observed_at,
                )
            )

    result.snapshots = len(snapshots)
    result.events_seen = len(event_ids)
    times = sorted(snapshots)
    result.start, result.end = times[0], times[-1]
    return result
