"""Tests for the lifecycle state machine and the adaptive poll scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from middler.config import SchedulerConfig
from middler.models import EventStatus
from middler.schedule.scheduler import PollScheduler
from middler.schedule.state_machine import is_pollable, next_status

WINDOW_H = 72


def _at(hours_from_commence: float) -> tuple[datetime, datetime]:
    """Return (now, commence) with commence ``hours_from_commence`` after now."""
    commence = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
    now = commence - timedelta(hours=hours_from_commence)
    return now, commence


# ── state machine ────────────────────────────────────────────────────────────
def test_status_scheduled_outside_window() -> None:
    now, commence = _at(100)  # 100h out, window is 72h
    assert next_status(commence, now, WINDOW_H) == EventStatus.SCHEDULED


def test_status_active_inside_window() -> None:
    now, commence = _at(10)
    assert next_status(commence, now, WINDOW_H) == EventStatus.ACTIVE
    assert is_pollable(EventStatus.ACTIVE)


def test_status_live_after_commence() -> None:
    commence = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
    now = commence + timedelta(minutes=30)
    assert next_status(commence, now, WINDOW_H) == EventStatus.LIVE
    assert not is_pollable(EventStatus.LIVE)


def test_status_settled_after_event() -> None:
    commence = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
    now = commence + timedelta(hours=5)
    assert next_status(commence, now, WINDOW_H) == EventStatus.SETTLED


# ── scheduler cadence ────────────────────────────────────────────────────────
def _scheduler() -> PollScheduler:
    return PollScheduler(SchedulerConfig(active_window_hours=72, poll_min_sec=60, poll_max_sec=3600))


def test_interval_ramps_toward_commence() -> None:
    sched = _scheduler()
    far_now, commence = _at(48)
    near_now, _ = _at(1)
    far = sched.interval_seconds(far_now, commence)
    near = sched.interval_seconds(near_now, commence)
    assert near < far
    assert 60 <= near <= 3600 and 60 <= far <= 3600


def test_interval_floor_at_commence() -> None:
    sched = _scheduler()
    now, commence = _at(0)
    assert sched.interval_seconds(now, commence) == 60.0


def test_volatility_shortens_interval() -> None:
    sched = _scheduler()
    now, commence = _at(24)
    calm = sched.interval_seconds(now, commence, volatility=0.0)
    jumpy = sched.interval_seconds(now, commence, volatility=1.0)
    assert jumpy < calm
    assert jumpy == 60.0  # full volatility collapses to the floor


def test_due_returns_event_after_its_interval() -> None:
    sched = _scheduler()
    now, commence = _at(24)
    sched.schedule("evt1", commence, now)
    assert sched.due(now) == []  # not yet due
    later = now + timedelta(seconds=sched.interval_seconds(now, commence) + 1)
    assert sched.due(later) == ["evt1"]


def test_reschedule_drops_event_at_commence() -> None:
    sched = _scheduler()
    now, commence = _at(1)
    sched.schedule("evt1", commence, now)
    assert sched.tracked == 1
    # At commence, the event must be dropped, not rescheduled (no in-play polling).
    assert sched.reschedule("evt1", commence) is False
    assert sched.tracked == 0


def test_due_drops_commenced_events() -> None:
    sched = _scheduler()
    now, commence = _at(1)
    sched.schedule("evt1", commence, now)
    # Far in the future (past commence): the event is dropped, not returned.
    assert sched.due(commence + timedelta(hours=1)) == []
    assert sched.tracked == 0
