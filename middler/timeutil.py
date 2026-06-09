"""Time helpers. Internals are UTC; humans see Sydney time (proposal §4.2)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")


def to_sydney(dt: datetime) -> datetime:
    """Convert a UTC-aware datetime to Australia/Sydney."""
    return dt.astimezone(SYDNEY)


def fmt_sydney(dt: datetime) -> str:
    """Format a datetime in Sydney local time, e.g. ``Wed 10 Jun 7:00pm AEST``."""
    local = to_sydney(dt)
    stamp = local.strftime("%a %d %b %I:%M%p").replace("AM", "am").replace("PM", "pm")
    return f"{stamp} {local.tzname()}"
