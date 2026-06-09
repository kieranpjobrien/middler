"""The event lifecycle state machine (proposal §4.2).

::

    SCHEDULED ──(commence within active window)──▶ ACTIVE
    ACTIVE ────(commence passes)──────────────────▶ LIVE      [polling suspended]
    LIVE ──────(event ends)────────────────────────▶ SETTLED   [history retained]

Polling only ever happens in ``ACTIVE``. Once an event is ``LIVE`` it is never
polled again — online in-play betting is illegal in AU, so there is nothing to
do but wait for it to settle. All comparisons use timezone-aware UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from middler.models import EventStatus

# Sports we track finish well within this window after commence; after it, the
# event is treated as settled and dropped from any working set.
DEFAULT_SETTLE_AFTER_HOURS = 4.0


def next_status(
    commence_time: datetime,
    now: datetime,
    active_window_hours: int,
    settle_after_hours: float = DEFAULT_SETTLE_AFTER_HOURS,
) -> EventStatus:
    """Compute the lifecycle status for an event at a given instant.

    Args:
        commence_time: When the event starts (UTC).
        now: The current instant (UTC).
        active_window_hours: How far ahead of commence an event becomes ACTIVE.
        settle_after_hours: Hours after commence at which the event is SETTLED.

    Returns:
        The :class:`EventStatus` for ``now``.
    """
    if now >= commence_time + timedelta(hours=settle_after_hours):
        return EventStatus.SETTLED
    if now >= commence_time:
        return EventStatus.LIVE
    if commence_time - now <= timedelta(hours=active_window_hours):
        return EventStatus.ACTIVE
    return EventStatus.SCHEDULED


def is_pollable(status: EventStatus) -> bool:
    """Return True only for events that should currently be polled for odds."""
    return status == EventStatus.ACTIVE
