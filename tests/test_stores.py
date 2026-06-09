"""Integration tests for the DuckDB history store and the hot store.

Real DuckDB (a temp file), real in-memory hot backend — no mocks (per house style).
"""

from __future__ import annotations

from datetime import UTC, datetime

from middler.models import OddsQuote, Opportunity, OpportunityLeg
from middler.store.history import HistoryStore
from middler.store.hot import HotStore

NOW = datetime(2026, 6, 9, 0, 0, tzinfo=UTC)
COMMENCE = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)


def _quote(book: str, price: float) -> OddsQuote:
    return OddsQuote(
        event_id="evt1",
        sport_key="aussierules_afl",
        commence_time=COMMENCE,
        bookmaker=book,
        market_key="totals",
        outcome_name="Over",
        point=72.5,
        price=price,
        observed_at=NOW,
    )


def test_history_records_quotes_and_opportunities(tmp_path) -> None:
    db = tmp_path / "test.duckdb"
    with HistoryStore(db) as store:
        written = store.write_quotes([_quote("sportsbet", 1.95), _quote("tab", 1.90)])
        assert written == 2
        assert store.quote_count() == 2

        opp = Opportunity(
            kind="middle",
            event_id="evt1",
            sport_key="aussierules_afl",
            commence_time=COMMENCE,
            market_key="totals",
            legs=[
                OpportunityLeg(
                    bookmaker="sportsbet",
                    market_key="totals",
                    outcome_name="Over",
                    side="over",
                    point=71.5,
                    price=1.95,
                    stake=50.0,
                ),
                OpportunityLeg(
                    bookmaker="tab",
                    market_key="totals",
                    outcome_name="Under",
                    side="under",
                    point=72.5,
                    price=1.95,
                    stake=50.0,
                ),
            ],
            total_stake=100.0,
            width=1.0,
            ev=1.23,
            ev_roi=0.0123,
            hit_rate=0.06,
            worst_case=-4.5,
            pl_middle=91.0,
            is_risk_free=False,
            observed_at=NOW,
        )
        store.write_opportunity(opp)
        assert store.opportunity_count() == 1

    # Reopen to confirm persistence to disk.
    with HistoryStore(db) as store:
        assert store.quote_count() == 2
        df = store.load_quotes("aussierules_afl")
        assert df.height == 2
        assert set(df["bookmaker"].to_list()) == {"sportsbet", "tab"}


def test_hot_store_in_memory_alert_throttle() -> None:
    hot = HotStore(redis_url=None)
    assert hot.backend == "memory"
    # First time fires; immediate repeat is suppressed within the cooldown.
    assert hot.should_alert("sig-123", cooldown_sec=60) is True
    assert hot.should_alert("sig-123", cooldown_sec=60) is False
    # A different signature is independent.
    assert hot.should_alert("sig-999", cooldown_sec=60) is True


def test_hot_store_json_roundtrip() -> None:
    hot = HotStore(redis_url=None)
    hot.set_json("k", {"a": 1, "b": [2, 3]})
    assert hot.get_json("k") == {"a": 1, "b": [2, 3]}
    assert hot.get_json("missing") is None
