"""Nightly backup of the DuckDB history and config (proposal §5, Phase 7).

Copies the history database and ``config.yaml`` to a destination directory
(e.g. the NAS at 192.168.4.42 or a cloud-synced folder), timestamped, and prunes
to the most recent N copies. Point a cron/systemd-timer or a scheduled task at:

    uv run python -m middler.tools.backup --dest /mnt/nas/middler-backups
"""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path

from middler.config import load_settings
from middler.logging_setup import get_logger, setup_logging

log = get_logger(__name__)


def backup(dest: str | Path, keep: int = 14) -> Path | None:
    """Copy the DuckDB history and config into a timestamped folder under ``dest``.

    Args:
        dest: Destination root directory (created if absent).
        keep: How many timestamped backups to retain (older ones are pruned).

    Returns:
        The created backup directory, or None if there was nothing to back up.
    """
    settings = load_settings()
    db_path = Path(settings.duckdb_path)
    if not db_path.exists():
        log.warning("no history database at %s — nothing to back up", db_path)
        return None

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = Path(dest) / f"middler-{stamp}"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, target / db_path.name)
    config = Path("config.yaml")
    if config.exists():
        shutil.copy2(config, target / "config.yaml")
    log.info("backed up history → %s", target)

    _prune(Path(dest), keep)
    return target


def _prune(dest: Path, keep: int) -> None:
    backups = sorted((p for p in dest.glob("middler-*") if p.is_dir()), reverse=True)
    for old in backups[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        log.info("pruned old backup %s", old.name)


def main() -> None:
    """CLI entry point for the backup job."""
    setup_logging()
    parser = argparse.ArgumentParser(description="Back up the middler history and config.")
    parser.add_argument("--dest", default="backups", help="destination directory (e.g. a NAS mount)")
    parser.add_argument("--keep", type=int, default=14, help="number of backups to retain")
    args = parser.parse_args()
    backup(args.dest, args.keep)


if __name__ == "__main__":
    main()
