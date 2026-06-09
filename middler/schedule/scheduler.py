"""The adaptive odds-polling scheduler (proposal §4.2).

A priority queue keyed on each event's ``next_poll_time``. The cadence ramps from
``poll_max_sec`` (events far from commence) toward ``poll_min_sec`` (events close
to commence), and tightens further with recent volatility. Crucially, an event is
**dropped rather than rescheduled** once it reaches commence — the system never
polls a live market.

The scheduler is a pure in-memory structure with no clock of its own: the caller
passes ``now`` in. That keeps it deterministic and trivially testable.
"""

from __future__ import annotations

import heapq
from datetime import datetime, timedelta

from middler.config import SchedulerConfig


class PollScheduler:
    """A heap-based, time-to-commence-aware poll scheduler."""

    def __init__(self, config: SchedulerConfig) -> None:
        """Initialise with scheduler configuration.

        Args:
            config: Cadence floor/ceiling, active window, and stop-before-commence.
        """
        self._config = config
        self._heap: list[tuple[float, str]] = []  # (next_poll_epoch, event_id)
        self._scheduled: dict[str, float] = {}  # event_id -> epoch (for lazy invalidation)
        self._commence: dict[str, datetime] = {}

    @property
    def tracked(self) -> int:
        """Number of events currently tracked (active in the queue)."""
        return len(self._commence)

    def interval_seconds(self, now: datetime, commence: datetime, volatility: float = 0.0) -> float:
        """Compute the next poll interval in seconds.

        The interval is a linear ramp on time-to-commence between ``poll_max_sec``
        (far away) and ``poll_min_sec`` (at/after commence), then scaled toward the
        floor by ``volatility``.

        Args:
            now: Current instant (UTC).
            commence: Event commence time (UTC).
            volatility: Recent line volatility in ``[0, 1]``; higher polls sooner.

        Returns:
            The interval in seconds, clamped to ``[poll_min_sec, poll_max_sec]``.
        """
        window = self._config.active_window_hours * 3600
        ttc = max(0.0, (commence - now).total_seconds())
        frac = min(1.0, ttc / window) if window else 0.0
        base = self._config.poll_min_sec + frac * (self._config.poll_max_sec - self._config.poll_min_sec)
        v = min(1.0, max(0.0, volatility))
        interval = self._config.poll_min_sec + (base - self._config.poll_min_sec) * (1.0 - v)
        return max(float(self._config.poll_min_sec), min(float(self._config.poll_max_sec), interval))

    def schedule(self, event_id: str, commence: datetime, now: datetime, volatility: float = 0.0) -> None:
        """Add (or re-add) an event to the queue with its next poll time."""
        self._commence[event_id] = commence
        when = now + timedelta(seconds=self.interval_seconds(now, commence, volatility))
        self._push(event_id, when)

    def reschedule(self, event_id: str, now: datetime, volatility: float = 0.0) -> bool:
        """Reschedule a just-polled event, or drop it if it has commenced.

        Args:
            event_id: The event that was just polled.
            now: Current instant (UTC).
            volatility: Recent line volatility in ``[0, 1]``.

        Returns:
            True if rescheduled, False if dropped (commenced / unknown).
        """
        commence = self._commence.get(event_id)
        if commence is None:
            return False
        cutoff = commence - timedelta(seconds=self._config.stop_before_commence_sec)
        if now >= cutoff:
            self.drop(event_id)
            return False
        when = now + timedelta(seconds=self.interval_seconds(now, commence, volatility))
        self._push(event_id, when)
        return True

    def due(self, now: datetime) -> list[str]:
        """Pop and return all event ids whose next poll time has arrived.

        Events that have reached commence are dropped here rather than returned.
        The caller must :meth:`reschedule` each returned event after polling it.
        """
        out: list[str] = []
        now_epoch = now.timestamp()
        while self._heap and self._heap[0][0] <= now_epoch:
            epoch, event_id = heapq.heappop(self._heap)
            if self._scheduled.get(event_id) != epoch:
                continue  # stale heap entry (superseded by a later schedule)
            commence = self._commence.get(event_id)
            if commence is not None and now >= commence - timedelta(seconds=self._config.stop_before_commence_sec):
                self.drop(event_id)
                continue
            del self._scheduled[event_id]  # consumed; awaits reschedule
            out.append(event_id)
        return out

    def drop(self, event_id: str) -> None:
        """Remove an event from tracking entirely (e.g. it went live or settled)."""
        self._scheduled.pop(event_id, None)
        self._commence.pop(event_id, None)

    def _push(self, event_id: str, when: datetime) -> None:
        epoch = when.timestamp()
        self._scheduled[event_id] = epoch
        heapq.heappush(self._heap, (epoch, event_id))
