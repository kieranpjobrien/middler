"""Backup tool tests against a real temp filesystem (no mocks)."""

from __future__ import annotations

from middler.store.history import HistoryStore
from middler.tools.backup import _prune, backup


def test_backup_copies_history(tmp_path, monkeypatch) -> None:
    db = tmp_path / "odds.duckdb"
    with HistoryStore(db) as store:  # create a real database file
        assert store.quote_count() == 0
    monkeypatch.setenv("DUCKDB_PATH", str(db))

    dest = tmp_path / "backups"
    created = backup(dest, keep=14)
    assert created is not None
    assert (created / "odds.duckdb").exists()


def test_backup_handles_missing_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "absent.duckdb"))
    assert backup(tmp_path / "backups") is None


def test_prune_keeps_most_recent(tmp_path) -> None:
    for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
        (tmp_path / f"middler-{stamp}").mkdir()
    _prune(tmp_path, keep=2)
    remaining = sorted(p.name for p in tmp_path.glob("middler-*"))
    assert remaining == ["middler-20260102T000000Z", "middler-20260103T000000Z"]
