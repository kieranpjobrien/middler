"""End-to-end backcast: record history → replay → render HTML report."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from middler.backcast.replay import run_backcast
from middler.backcast.report import render_report
from middler.config import AppConfig
from middler.models import Event, OddsQuote
from middler.store.history import HistoryStore

COMMENCE = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)


def _quote(book: str, market: str, name: str, point: float | None, price: float, when: datetime) -> OddsQuote:
    return OddsQuote(
        event_id="evt1",
        sport_key="aussierules_afl",
        commence_time=COMMENCE,
        bookmaker=book,
        market_key=market,
        outcome_name=name,
        point=point,
        price=price,
        observed_at=when,
    )


def _seed(store: HistoryStore) -> None:
    store.upsert_events(
        [
            Event(
                id="evt1",
                sport_key="aussierules_afl",
                sport_title="AFL",
                commence_time=COMMENCE,
                home_team="Team A",
                away_team="Team B",
            )
        ]
    )
    # Two snapshots, each containing a 1-point totals middle across two books.
    for offset_h in (48, 24):
        when = COMMENCE - timedelta(hours=offset_h)
        store.write_quotes(
            [
                _quote("sportsbet", "totals", "Over", 71.5, 1.95, when),
                _quote("sportsbet", "totals", "Under", 71.5, 1.87, when),
                _quote("tab", "totals", "Over", 72.5, 1.85, when),
                _quote("tab", "totals", "Under", 72.5, 1.95, when),
            ]
        )


def test_backcast_finds_middles_in_recorded_history(tmp_path) -> None:
    with HistoryStore(tmp_path / "bc.duckdb") as store:
        _seed(store)
        result = run_backcast(store, AppConfig(sports=["aussierules_afl"]))
    assert result.total_quotes == 8
    assert result.snapshots == 2
    assert len(result.middles) == 2  # one per snapshot
    assert all(m.width == 1.0 for m in result.middles)


def test_report_is_self_contained_html(tmp_path) -> None:
    with HistoryStore(tmp_path / "bc.duckdb") as store:
        _seed(store)
        result = run_backcast(store, AppConfig(sports=["aussierules_afl"]))
    out = render_report(result, AppConfig(sports=["aussierules_afl"]), tmp_path / "report.html")
    text = out.read_text(encoding="utf-8")
    assert out.exists()
    assert "Backcast" in text
    assert "Team A" in text and "Team B" in text
    # Plotly is embedded inline → the file is self-contained (no CDN needed).
    assert "plotly" in text.lower()
    assert len(text) > 100_000  # inline plotly.js makes it substantial


def test_backcast_on_empty_history_is_graceful(tmp_path) -> None:
    with HistoryStore(tmp_path / "empty.duckdb") as store:
        result = run_backcast(store, AppConfig())
        out = render_report(result, AppConfig(), tmp_path / "empty.html")
    assert result.total_quotes == 0
    assert "No odds recorded yet" in out.read_text(encoding="utf-8")
