"""Placement guard tests — the safety logic that decides whether to auto-place.

No network, no Betfair account: these prove the *refusal* rules, which are the
ones that matter (proposal §2, §4.4).
"""

from __future__ import annotations

from datetime import UTC, datetime

from middler.config import AppConfig, Settings
from middler.models import Opportunity, OpportunityLeg
from middler.place.betfair import BetfairExchange, betfair_leg, evaluate_placement

NOW = datetime(2026, 6, 9, tzinfo=UTC)


def _opp(verified: bool = True, with_betfair: bool = True, total: float = 100.0) -> Opportunity:
    legs = [
        OpportunityLeg(
            bookmaker="sportsbet",
            market_key="totals",
            outcome_name="Over",
            side="over",
            point=71.5,
            price=1.95,
            stake=total / 2,
        ),
    ]
    if with_betfair:
        legs.append(
            OpportunityLeg(
                bookmaker="betfair_ex_au",
                market_key="totals",
                outcome_name="Under",
                side="under",
                point=72.5,
                price=1.95,
                stake=total / 2,
            )
        )
    return Opportunity(
        kind="middle",
        event_id="e",
        sport_key="aussierules_afl",
        commence_time=NOW,
        market_key="totals",
        legs=legs,
        total_stake=total,
        width=1.0,
        ev=1.2,
        is_risk_free=False,
        reference_verified=verified,
        observed_at=NOW,
    )


def _settings(enabled: bool, key: str) -> Settings:
    return Settings(placement_enabled=enabled, betfair_app_key=key)


def test_disabled_refuses() -> None:
    d = evaluate_placement(_opp(), _settings(False, "k"), AppConfig())
    assert not d.allowed and "disabled" in d.reason


def test_missing_key_refuses() -> None:
    d = evaluate_placement(_opp(), _settings(True, ""), AppConfig())
    assert not d.allowed and "key" in d.reason


def test_unverified_line_refuses() -> None:
    d = evaluate_placement(_opp(verified=False), _settings(True, "k"), AppConfig())
    assert not d.allowed and "verified" in d.reason


def test_no_betfair_leg_refuses() -> None:
    d = evaluate_placement(_opp(with_betfair=False), _settings(True, "k"), AppConfig())
    assert not d.allowed and "Betfair" in d.reason


def test_allowed_when_all_guards_pass() -> None:
    d = evaluate_placement(_opp(), _settings(True, "k"), AppConfig())
    assert d.allowed and d.reason == "ok"
    assert d.requires_second_confirm is False


def test_large_stake_requires_second_confirm() -> None:
    cfg = AppConfig()
    cfg.staking.two_step_confirm_above = 200.0
    d = evaluate_placement(_opp(total=500.0), _settings(True, "k"), cfg)
    assert d.allowed and d.requires_second_confirm is True


def test_betfair_leg_finder() -> None:
    assert betfair_leg(_opp()).bookmaker == "betfair_ex_au"
    assert betfair_leg(_opp(with_betfair=False)) is None


def test_dry_run_place_does_not_send() -> None:
    ex = BetfairExchange(_settings(True, "k"))
    result = ex.place_back_order("1.234", 567, 1.95, 50.0, "ref-1", dry_run=True)
    assert result["status"] == "dry_run"
    assert result["market_id"] == "1.234"
