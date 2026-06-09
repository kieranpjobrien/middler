"""Budget guard tests — deterministic via injected timestamps (no real clock)."""

from __future__ import annotations

from middler.budget import BudgetGuard, caps_from_config
from middler.config import BudgetConfig

T = 1_000_000.0  # arbitrary epoch base


def test_per_day_cap(tmp_path) -> None:
    g = BudgetGuard(tmp_path / "b.json", {"f": {"per_hour": None, "per_day": 3}})
    for _ in range(3):
        assert g.allow("f", now=T)
        g.record("f", now=T)
    assert not g.allow("f", now=T)  # 3/3 used
    assert g.allow("f", now=T + 25 * 3600)  # >24h later, window cleared


def test_per_hour_cap(tmp_path) -> None:
    g = BudgetGuard(tmp_path / "b.json", {"f": {"per_hour": 2, "per_day": None}})
    g.record("f", now=T)
    g.record("f", now=T)
    assert not g.allow("f", now=T)
    assert g.allow("f", now=T + 3601)  # an hour on, the two fall out of the window


def test_min_reserve_blocks_when_credits_low(tmp_path) -> None:
    g = BudgetGuard(tmp_path / "b.json", {"f": {"per_hour": None, "per_day": 100}})
    g.record("f", now=T, remaining=40)
    assert not g.allow("f", now=T, min_reserve=50)
    g.record("f", now=T, remaining=80)
    assert g.allow("f", now=T, min_reserve=50)


def test_record_count(tmp_path) -> None:
    g = BudgetGuard(tmp_path / "b.json", {"f": {"per_hour": None, "per_day": 3}})
    g.record("f", now=T, count=2)
    assert g.allow("f", now=T)  # 2/3
    g.record("f", now=T)
    assert not g.allow("f", now=T)  # 3/3


def test_persistence_across_instances(tmp_path) -> None:
    path = tmp_path / "b.json"
    g = BudgetGuard(path, {"f": {"per_hour": None, "per_day": 2}})
    g.record("f", now=T, remaining=123)
    reloaded = BudgetGuard(path, {"f": {"per_hour": None, "per_day": 2}})
    assert reloaded.remaining("f") == 123
    assert reloaded.allow("f", now=T)  # 1/2 used
    reloaded.record("f", now=T)
    assert not reloaded.allow("f", now=T)  # 2/2


def test_caps_from_config_defaults() -> None:
    caps = caps_from_config(BudgetConfig())
    assert caps["the_odds_api"]["per_day"] == 5
    assert caps["odds_api_io"]["per_hour"] == 90
    assert caps["oddspapi"]["per_day"] == 8
