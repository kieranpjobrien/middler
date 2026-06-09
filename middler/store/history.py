"""DuckDB history store — every odds observation and every opportunity.

This is the system's memory and the backcast's source of truth (proposal §4.1).
It records *everything* it sees from day one, so the forward-test naturally
accumulates the data the backcast replays, for free (§2).

Schema (all timestamps stored as ``TIMESTAMPTZ``, i.e. UTC):

* ``odds_quotes`` — one row per (event, book, market, outcome) per observation.
* ``opportunities`` — one row per detected middle/arb, legs stored as JSON.
* ``results`` — settled outcome per (event, market), to derive empirical
  middle-hit-rates once events finish.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import TracebackType

import duckdb

from middler.models import Event, OddsQuote, Opportunity

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id      VARCHAR PRIMARY KEY,
    sport_key     VARCHAR,
    sport_title   VARCHAR,
    commence_time TIMESTAMPTZ,
    home_team     VARCHAR,
    away_team     VARCHAR
);

CREATE TABLE IF NOT EXISTS odds_quotes (
    event_id      VARCHAR,
    sport_key     VARCHAR,
    commence_time TIMESTAMPTZ,
    bookmaker     VARCHAR,
    market_key    VARCHAR,
    outcome_name  VARCHAR,
    point         DOUBLE,
    price         DOUBLE,
    observed_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS opportunities (
    signature          VARCHAR,
    kind               VARCHAR,
    event_id           VARCHAR,
    sport_key          VARCHAR,
    commence_time      TIMESTAMPTZ,
    market_key         VARCHAR,
    home_team          VARCHAR,
    away_team          VARCHAR,
    legs               JSON,
    total_stake        DOUBLE,
    margin             DOUBLE,
    profit             DOUBLE,
    roi                DOUBLE,
    width              DOUBLE,
    ev                 DOUBLE,
    ev_roi             DOUBLE,
    hit_rate           DOUBLE,
    worst_case         DOUBLE,
    pl_middle          DOUBLE,
    is_risk_free       BOOLEAN,
    reference_verified BOOLEAN,
    observed_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS results (
    event_id     VARCHAR,
    market_key   VARCHAR,
    settled_value DOUBLE,
    settled_at   TIMESTAMPTZ
);
"""


class HistoryStore:
    """A thin DuckDB-backed recorder and reader for odds and opportunities."""

    def __init__(self, path: str | Path = "data/odds.duckdb") -> None:
        """Open (creating if needed) the DuckDB database and ensure the schema.

        Args:
            path: File path, or ``":memory:"`` for an ephemeral in-memory store
                (used in tests).
        """
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._conn = duckdb.connect(self.path)
        self._conn.execute(_SCHEMA)  # the JSON type is bundled in DuckDB

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ── writes ───────────────────────────────────────────────────────────────
    def upsert_events(self, events: list[Event]) -> None:
        """Insert or update event metadata (commence time, teams) by event id."""
        for e in events:
            self._conn.execute(
                """
                INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO UPDATE SET
                    sport_key = excluded.sport_key,
                    sport_title = excluded.sport_title,
                    commence_time = excluded.commence_time,
                    home_team = excluded.home_team,
                    away_team = excluded.away_team
                """,
                [e.id, e.sport_key, e.sport_title, e.commence_time, e.home_team, e.away_team],
            )

    def write_quotes(self, quotes: list[OddsQuote]) -> int:
        """Append a batch of odds observations.

        Args:
            quotes: The flattened quotes to persist.

        Returns:
            The number of rows written.
        """
        if not quotes:
            return 0
        rows = [
            (
                q.event_id,
                q.sport_key,
                q.commence_time,
                q.bookmaker,
                q.market_key,
                q.outcome_name,
                q.point,
                q.price,
                q.observed_at,
            )
            for q in quotes
        ]
        self._conn.executemany(
            "INSERT INTO odds_quotes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        return len(rows)

    def write_opportunity(self, opp: Opportunity) -> None:
        """Append one detected opportunity (legs serialised to JSON)."""
        legs_json = json.dumps([leg.model_dump() for leg in opp.legs])
        self._conn.execute(
            """
            INSERT INTO opportunities VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                opp.signature,
                opp.kind,
                opp.event_id,
                opp.sport_key,
                opp.commence_time,
                opp.market_key,
                opp.home_team,
                opp.away_team,
                legs_json,
                opp.total_stake,
                opp.margin,
                opp.profit,
                opp.roi,
                opp.width,
                opp.ev,
                opp.ev_roi,
                opp.hit_rate,
                opp.worst_case,
                opp.pl_middle,
                opp.is_risk_free,
                opp.reference_verified,
                opp.observed_at,
            ],
        )

    def record_result(self, event_id: str, market_key: str, settled_value: float, settled_at: datetime) -> None:
        """Record a settled outcome (e.g. final total) for hit-rate estimation."""
        self._conn.execute(
            "INSERT INTO results VALUES (?, ?, ?, ?)",
            [event_id, market_key, settled_value, settled_at],
        )

    # ── reads ────────────────────────────────────────────────────────────────
    def _scalar(self, sql: str) -> int:
        row = self._conn.execute(sql).fetchone()
        return int(row[0]) if row else 0

    def quote_count(self) -> int:
        """Return the total number of recorded odds observations."""
        return self._scalar("SELECT COUNT(*) FROM odds_quotes")

    def opportunity_count(self) -> int:
        """Return the total number of recorded opportunities."""
        return self._scalar("SELECT COUNT(*) FROM opportunities")

    def load_quotes(self, sport_key: str | None = None):  # type: ignore[no-untyped-def]
        """Load recorded quotes as a Polars DataFrame (for the backcast).

        Args:
            sport_key: Restrict to one sport, or all sports when None.

        Returns:
            A ``polars.DataFrame`` ordered by ``observed_at``.
        """
        if sport_key:
            rel = self._conn.execute(
                "SELECT * FROM odds_quotes WHERE sport_key = ? ORDER BY observed_at",
                [sport_key],
            )
        else:
            rel = self._conn.execute("SELECT * FROM odds_quotes ORDER BY observed_at")
        return rel.pl()

    def load_events(self) -> dict[str, dict[str, object]]:
        """Return event metadata keyed by event id (for backcast reconstruction)."""
        rows = self._conn.execute(
            "SELECT event_id, sport_key, sport_title, commence_time, home_team, away_team FROM events"
        ).fetchall()
        return {
            r[0]: {
                "sport_key": r[1],
                "sport_title": r[2],
                "commence_time": r[3],
                "home_team": r[4],
                "away_team": r[5],
            }
            for r in rows
        }

    def distinct_observation_times(self, event_id: str, market_key: str) -> list[datetime]:
        """Return the sorted distinct observation timestamps for an event+market."""
        rows = self._conn.execute(
            "SELECT DISTINCT observed_at FROM odds_quotes WHERE event_id = ? AND market_key = ? ORDER BY observed_at",
            [event_id, market_key],
        ).fetchall()
        return [r[0] for r in rows]
