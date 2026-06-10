"""Container healthcheck — exit 0 if the app has run a cycle recently.

The running app holds DuckDB's single-writer lock, so a separate process cannot
open the database to check it (it would conflict). Instead the app touches a
``heartbeat`` file each cycle, and this checks that file is fresh. Used by Docker's
``HEALTHCHECK`` and handy to run by hand.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from middler.config import load_settings

MAX_AGE_SEC = 300  # the loop ticks every ~30s; allow a generous staleness margin


def main() -> None:
    """Print a one-line status and exit 0 (healthy) or 1 (unhealthy)."""
    settings = load_settings()
    heartbeat = Path(settings.duckdb_path).parent / "heartbeat"
    if not heartbeat.exists():
        print("unhealthy: no heartbeat yet")
        sys.exit(1)
    age = time.time() - heartbeat.stat().st_mtime
    if age > MAX_AGE_SEC:
        print(f"unhealthy: heartbeat stale ({age:.0f}s old)")
        sys.exit(1)
    print(f"ok: heartbeat {age:.0f}s ago")
    sys.exit(0)


if __name__ == "__main__":
    main()
