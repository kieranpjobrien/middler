"""Orchestrator wiring test with an injected fake feed (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from middler.app import MiddlerApp
from middler.config import AppConfig, Settings

NOW = datetime(2026, 6, 9, 0, 0, tzinfo=UTC)
COMMENCE = NOW + timedelta(hours=10)


class FakeClient:
    """Stand-in for OddsApiClient returning canned discovery + odds payloads."""

    def get_events(self, sport_key: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "evt1",
                "sport_key": sport_key,
                "commence_time": COMMENCE.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "home_team": "Carlton",
                "away_team": "Collingwood",
            }
        ]

    def get_odds(self, sport_key: str, markets: list[str], **_: Any) -> list[dict[str, Any]]:
        # Two books straddling the total → a 1-point middle.
        return [
            {
                "id": "evt1",
                "sport_key": sport_key,
                "sport_title": "AFL",
                "commence_time": COMMENCE.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "home_team": "Carlton",
                "away_team": "Collingwood",
                "bookmakers": [
                    {
                        "key": "sportsbet",
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": 1.95, "point": 71.5},
                                    {"name": "Under", "price": 1.87, "point": 71.5},
                                ],
                            }
                        ],
                    },
                    {
                        "key": "tab",
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": 1.85, "point": 72.5},
                                    {"name": "Under", "price": 1.95, "point": 72.5},
                                ],
                            }
                        ],
                    },
                ],
            }
        ]

    def close(self) -> None:  # pragma: no cover - parity with the real client
        pass


def test_orchestrator_records_and_detects(tmp_path) -> None:
    settings = Settings(duckdb_path=str(tmp_path / "app.duckdb"), telegram_bot_token="")
    config = AppConfig(sports=["aussierules_afl"], markets=["totals"])
    app = MiddlerApp(settings, config)
    app.client = FakeClient()  # type: ignore[assignment]

    app.discover(NOW)
    assert app.scheduler.tracked == 1

    # Poll once the event is due (an hour later, still well before commence).
    alerted = app.poll_due(NOW + timedelta(hours=1))

    assert app.history.quote_count() == 4  # 2 books × Over/Under
    assert app.history.opportunity_count() >= 1  # the middle was recorded
    assert alerted >= 1
    app.history.close()
