"""Pure-formatting tests for alerts and deep-links (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from middler.alert.deeplinks import deep_link
from middler.alert.telegram import Alerter, format_alert
from middler.models import Event, Opportunity, OpportunityLeg

COMMENCE = datetime(2026, 6, 11, 9, 40, tzinfo=UTC)


def _middle() -> Opportunity:
    return Opportunity(
        kind="middle",
        event_id="evt1",
        sport_key="aussierules_afl",
        commence_time=COMMENCE,
        market_key="totals",
        home_team="Carlton",
        away_team="Collingwood",
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
        reference_verified=True,
        observed_at=COMMENCE,
    )


def _arb() -> Opportunity:
    return Opportunity(
        kind="arb",
        event_id="evt1",
        sport_key="aussierules_afl",
        commence_time=COMMENCE,
        market_key="h2h",
        home_team="Carlton",
        away_team="Collingwood",
        legs=[
            OpportunityLeg(
                bookmaker="sportsbet",
                market_key="h2h",
                outcome_name="Carlton",
                side="back",
                point=None,
                price=2.10,
                stake=50.0,
            ),
            OpportunityLeg(
                bookmaker="tab",
                market_key="h2h",
                outcome_name="Collingwood",
                side="back",
                point=None,
                price=2.10,
                stake=50.0,
            ),
        ],
        total_stake=100.0,
        margin=0.0476,
        profit=5.0,
        roi=0.05,
        observed_at=COMMENCE,
    )


def test_format_middle_alert() -> None:
    text, buttons = format_alert(_middle())
    assert "MIDDLE" in text
    assert "Carlton v Collingwood" in text
    assert "sportsbet" in text and "tab" in text
    assert "$91.00" in text  # both-win payout
    assert "Sharp-verified" in text
    assert len(buttons) == 2
    assert all(url.startswith("http") for _, url in buttons)


def test_format_arb_alert() -> None:
    text, _ = format_alert(_arb())
    assert "ARBITRAGE" in text
    assert "Guaranteed profit" in text
    assert "$5.00" in text


def test_deep_link_known_and_unknown() -> None:
    assert deep_link("sportsbet") == "https://www.sportsbet.com.au"
    event = Event(id="e", sport_key="s", commence_time=COMMENCE, home_team="A", away_team="B")
    assert deep_link("obscure_book", event).startswith("https://www.google.com/search")


def test_alerter_disabled_is_noop() -> None:
    alerter = Alerter(token="", chat_ids=[])
    assert alerter.enabled is False
    alerter.notify(_middle())  # must not raise
