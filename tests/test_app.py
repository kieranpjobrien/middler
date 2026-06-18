"""Orchestrator wiring test with an injected fake feed (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from middler.app import MiddlerApp
from middler.config import AppConfig, Settings
from middler.models import BookMarket, Event, Outcome

NOW = datetime(2026, 6, 9, 0, 0, tzinfo=UTC)
COMMENCE = NOW + timedelta(hours=10)


class FakeClient:
    """Stand-in for OddsApiClient returning canned discovery + odds payloads."""

    remaining_credits: int | None = None

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
    settings = Settings(duckdb_path=str(tmp_path / "app.duckdb"), telegram_bot_token="", _env_file=None)
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


class OneSidedClient(FakeClient):
    """Primary feed that sees only one side — no middle on its own."""

    def get_odds(self, sport_key: str, markets: list[str], **_: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "evt1",
                "sport_key": sport_key,
                "commence_time": COMMENCE.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "home_team": "Carlton",
                "away_team": "Collingwood",
                "bookmakers": [
                    {
                        "key": "sportsbet",
                        "markets": [{"key": "totals", "outcomes": [{"name": "Over", "price": 1.95, "point": 71.5}]}],
                    },
                ],
            }
        ]


class FakeSecondary:
    """Stand-in for OddsApiIoClient supplying the missing side of the middle."""

    def get_events(self, sport_slug: str) -> list[dict[str, Any]]:
        return [{"id": 999, "home": "Carlton", "away": "Collingwood"}]

    def get_odds(self, event_ids: list[str], bookmakers: list[str] | None = None) -> list[Event]:
        return [
            Event(
                id="999",
                sport_key="",
                commence_time=COMMENCE,
                home_team="Carlton",
                away_team="Collingwood",
                book_markets=[
                    BookMarket(
                        bookmaker="tab",
                        market_key="totals",
                        outcomes=[Outcome(name="Under", price=1.95, point=72.5)],
                    )
                ],
            )
        ]

    def close(self) -> None:  # pragma: no cover
        pass


def test_secondary_feed_completes_a_middle(tmp_path) -> None:
    settings = Settings(
        duckdb_path=str(tmp_path / "app2.duckdb"), telegram_bot_token="", odds_api_io_key="x", _env_file=None
    )
    config = AppConfig(sports=["aussierules_afl"], markets=["totals"], odds_api_io_sport_map={"aussierules_afl": "afl"})
    app = MiddlerApp(settings, config)
    app.client = OneSidedClient()  # type: ignore[assignment]
    app.secondary = FakeSecondary()  # type: ignore[assignment]

    app.discover(NOW)
    alerted = app.poll_due(NOW + timedelta(hours=1))

    # The primary alone has no middle; only the merged book set does.
    assert app.history.opportunity_count() >= 1
    assert alerted >= 1
    app.history.close()


class FakeSecondaryBackLay:
    """odds-api.io stand-in returning a Bet365 back + Betfair lay → a back-lay."""

    def get_events(self, sport_slug: str) -> list[dict[str, Any]]:
        return [
            {"id": 777, "home": "Carlton", "away": "Collingwood", "startTime": COMMENCE.strftime("%Y-%m-%dT%H:%M:%SZ")}
        ]

    def get_odds(self, event_ids: list[str], bookmakers: list[str]) -> list[Event]:
        return [
            Event(
                id="777",
                sport_key="",
                commence_time=COMMENCE,
                home_team="Carlton",
                away_team="Collingwood",
                book_markets=[
                    BookMarket(
                        bookmaker="bet365", market_key="totals", outcomes=[Outcome(name="Over", price=2.10, point=2.5)]
                    ),
                    BookMarket(
                        bookmaker="betfair_ex_au",
                        market_key="totals_lay",
                        outcomes=[Outcome(name="Over", price=2.00, point=2.5)],
                    ),
                ],
            )
        ]

    def close(self) -> None:  # pragma: no cover
        pass


def test_poll_secondary_records_and_detects(tmp_path) -> None:
    settings = Settings(
        duckdb_path=str(tmp_path / "app4.duckdb"), telegram_bot_token="", odds_api_io_key="x", _env_file=None
    )
    config = AppConfig(
        sports=["aussierules_afl"],
        markets=["totals"],
        odds_api_io_sport_map={"aussierules_afl": "aussie-rules"},
        odds_api_io_bookmakers=["Bet365", "Betfair Exchange"],
    )
    app = MiddlerApp(settings, config)
    app.secondary = FakeSecondaryBackLay()  # type: ignore[assignment]

    alerted = app.poll_secondary(NOW)

    assert app.history.quote_count() > 0  # odds-api.io observations recorded
    assert app.history.opportunity_count() >= 1 and alerted >= 1  # back-lay detected
    app.history.close()


class FakeTertiary:
    """OddsPapi stand-in: a tournament → fixture → deep h2h arb across two books."""

    def get_tournaments(self, sport_id: int) -> list[dict[str, Any]]:
        return [{"tournamentId": 100}]

    def get_fixtures(self, tournament_id: int) -> list[dict[str, Any]]:
        return [{"fixtureId": "fx1", "startTime": COMMENCE.strftime("%Y-%m-%dT%H:%M:%SZ")}]

    def get_fixture_odds(self, fixture_id: str, sport_key: str) -> Event:
        return Event(
            id=fixture_id,
            sport_key=sport_key,
            commence_time=COMMENCE,
            home_team="Carlton",
            away_team="Collingwood",
            book_markets=[
                BookMarket(
                    bookmaker="sportsbet",
                    market_key="h2h",
                    outcomes=[Outcome(name="Carlton", price=2.10), Outcome(name="Collingwood", price=1.80)],
                ),
                BookMarket(
                    bookmaker="tab",
                    market_key="h2h",
                    outcomes=[Outcome(name="Carlton", price=1.80), Outcome(name="Collingwood", price=2.10)],
                ),
            ],
        )

    def close(self) -> None:  # pragma: no cover
        pass


def test_poll_oddspapi_walks_records_and_detects(tmp_path) -> None:
    settings = Settings(
        duckdb_path=str(tmp_path / "app5.duckdb"), telegram_bot_token="", oddspapi_key="x", _env_file=None
    )
    config = AppConfig(sports=["aussierules_afl"], oddspapi_sport_map={"aussierules_afl": 31})
    app = MiddlerApp(settings, config)
    app.tertiary = FakeTertiary()  # type: ignore[assignment]

    alerted = app.poll_oddspapi(NOW)

    assert app.history.quote_count() == 4  # 2 books × 2 outcomes recorded
    assert app.history.opportunity_count() >= 1 and alerted >= 1  # the h2h arb detected
    app.history.close()


def test_poll_oddspapi_respects_budget(tmp_path) -> None:
    settings = Settings(
        duckdb_path=str(tmp_path / "app6.duckdb"), telegram_bot_token="", oddspapi_key="x", _env_file=None
    )
    config = AppConfig(sports=["aussierules_afl"], oddspapi_sport_map={"aussierules_afl": 31})
    config.budget.oddspapi_per_day = 0  # no allowance → nothing should be fetched
    app = MiddlerApp(settings, config)
    app.tertiary = FakeTertiary()  # type: ignore[assignment]

    alerted = app.poll_oddspapi(NOW)

    assert alerted == 0
    assert app.history.quote_count() == 0  # the budget guard blocked every call
    app.history.close()


def test_run_once_refreshes_report(tmp_path) -> None:
    settings = Settings(duckdb_path=str(tmp_path / "app3.duckdb"), telegram_bot_token="", _env_file=None)
    config = AppConfig(sports=["aussierules_afl"], markets=["totals"])
    config.backcast.report_path = str(tmp_path / "backcast.html")
    app = MiddlerApp(settings, config)
    app.client = FakeClient()  # type: ignore[assignment]

    app.run_once(NOW)  # discovers + polls (nothing due yet) + writes the report
    assert (tmp_path / "backcast.html").exists()
    app.close()
