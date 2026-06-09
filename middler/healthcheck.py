"""Container healthcheck — exit 0 if the history store is reachable.

Used by Docker's ``HEALTHCHECK`` and handy to run by hand. Deliberately minimal:
it proves the process can open its database, which is the dependency most likely
to break a deployment.
"""

from __future__ import annotations

import sys

from middler.config import load_settings
from middler.store.history import HistoryStore


def main() -> None:
    """Print a one-line status and exit 0 (healthy) or 1 (unhealthy)."""
    try:
        settings = load_settings()
        with HistoryStore(settings.duckdb_path) as store:
            quotes = store.quote_count()
            opps = store.opportunity_count()
        print(f"ok quotes={quotes} opportunities={opps}")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - healthcheck reports any failure
        print(f"unhealthy: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
