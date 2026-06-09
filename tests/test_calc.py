"""Smoke tests for the manual calculator CLI (maths itself tested in test_maths)."""

from __future__ import annotations

import argparse

from middler.tools.calc import _arb, _backlay, _middle


def test_calc_middle(capsys) -> None:
    args = argparse.Namespace(
        over=71.5, over_odds=1.91, under=73.5, under_odds=1.95, stake=100.0, mode="balanced", hit_rate=0.06
    )
    _middle(args)
    out = capsys.readouterr().out
    assert "MIDDLE" in out
    assert "lands on 72, 73" in out
    assert "Risk-free: no" in out


def test_calc_middle_rejects_non_overlap(capsys) -> None:
    args = argparse.Namespace(
        over=73.5, over_odds=1.91, under=71.5, under_odds=1.95, stake=100.0, mode="balanced", hit_rate=0.06
    )
    _middle(args)
    assert "not a middle" in capsys.readouterr().out


def test_calc_backlay(capsys) -> None:
    _backlay(argparse.Namespace(back=81.0, lay=34.0, stake=100.0, commission=0.05))
    out = capsys.readouterr().out
    assert "126.66" in out and "risk-free" in out


def test_calc_arb(capsys) -> None:
    _arb(argparse.Namespace(odds=[2.10, 2.10], stake=100.0))
    out = capsys.readouterr().out
    assert "4.76%" in out  # margin
    assert "profit $5.00" in out
