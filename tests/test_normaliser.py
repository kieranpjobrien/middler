"""Normaliser tests against a realistic The-Odds-API ``/odds`` payload."""

from __future__ import annotations

from datetime import UTC, datetime

from middler.ingest.normaliser import normalise_odds_response, parse_commence

SAMPLE = [
    {
        "id": "abc123",
        "sport_key": "aussierules_afl",
        "sport_title": "AFL",
        "commence_time": "2026-06-10T09:00:00Z",
        "home_team": "Team A",
        "away_team": "Team B",
        "bookmakers": [
            {
                "key": "sportsbet",
                "title": "SportsBet",
                "last_update": "2026-06-09T05:00:00Z",
                "markets": [
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.91, "point": 72.5},
                            {"name": "Under", "price": 1.91, "point": 72.5},
                        ],
                    },
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Team A", "price": 1.80},
                            {"name": "Team B", "price": 2.00},
                        ],
                    },
                    {"key": "lay", "outcomes": [{"name": "ignored", "price": 1.5}]},
                ],
            }
        ],
    }
]


def test_parse_commence_is_utc_aware() -> None:
    dt = parse_commence("2026-06-10T09:00:00Z")
    assert dt == datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
    assert dt.tzinfo is not None


def test_normalise_builds_events_and_quotes() -> None:
    observed = datetime(2026, 6, 9, 6, 0, tzinfo=UTC)
    events, quotes = normalise_odds_response(SAMPLE, observed_at=observed)
    assert len(events) == 1
    event = events[0]
    assert event.home_team == "Team A"
    # Unknown market "lay" is dropped; totals + h2h remain.
    assert {bm.market_key for bm in event.book_markets} == {"totals", "h2h"}
    # 2 totals + 2 h2h outcomes = 4 flattened quotes, all stamped with observed_at.
    assert len(quotes) == 4
    assert all(q.observed_at == observed for q in quotes)
    assert all(q.event_id == "abc123" for q in quotes)


def test_normalise_skips_non_positive_prices() -> None:
    payload = [
        {
            "id": "x",
            "sport_key": "s",
            "commence_time": "2026-06-10T09:00:00Z",
            "bookmakers": [
                {
                    "key": "b",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "A", "price": 0}, {"name": "B", "price": 2.0}]}],
                }
            ],
        }
    ]
    _events, quotes = normalise_odds_response(payload)
    assert len(quotes) == 1
    assert quotes[0].outcome_name == "B"
