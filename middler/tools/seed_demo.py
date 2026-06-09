"""Generate a realistic *synthetic* odds history so the report can be seen now.

This is a **fixture generator**, not part of the live system and never part of
detection. It fabricates plausible pre-match odds across several AU books and a
handful of fixtures, deliberately seeding some genuine middles and arbitrages, so
the Reviewer can open a populated ``backcast`` report before any real data (or API
keys) exist. Use ``--db data/demo.duckdb`` to keep it out of the real history.

Randomness lives here on purpose — it shapes *fake market data*, never a real
stake. The detection maths it is fed remains exactly the deterministic engine.
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta
from typing import cast

from middler.backcast.replay import run_backcast
from middler.backcast.report import render_report
from middler.config import AppConfig, load_config
from middler.logging_setup import get_logger, setup_logging
from middler.models import Event, OddsQuote
from middler.store.history import HistoryStore

log = get_logger(__name__)

BOOKS = ["sportsbet", "tab", "pointsbetau", "ladbrokesau", "neds", "betfair_ex_au", "pinnacle"]
SHARP = {"betfair_ex_au", "pinnacle"}

SPORTS: dict[str, dict[str, object]] = {
    "aussierules_afl": {
        "title": "AFL",
        "total": 165.0,
        "teams": ["Carlton", "Collingwood", "Geelong", "Brisbane", "Sydney", "Melbourne", "Port Adelaide", "Fremantle"],
    },
    "rugbyleague_nrl": {
        "title": "NRL",
        "total": 38.0,
        "teams": ["Penrith", "Melbourne Storm", "Broncos", "Roosters", "Sharks", "Cowboys", "Eels", "Raiders"],
    },
    "basketball_nba": {
        "title": "NBA",
        "total": 225.0,
        "teams": ["Celtics", "Nuggets", "Thunder", "Knicks", "Lakers", "Mavericks", "Bucks", "Timberwolves"],
    },
    "americanfootball_nfl": {
        "title": "NFL",
        "total": 45.0,
        "teams": ["Chiefs", "49ers", "Ravens", "Bills", "Lions", "Eagles", "Cowboys", "Dolphins"],
    },
}


def _decimal_from_prob(prob: float) -> float:
    """Convert a probability to decimal odds, rounded to 2dp like a real book."""
    return round(1.0 / max(0.02, min(0.98, prob)), 2)


def _book_total_line(base: float, rng: random.Random, straddle: int) -> float:
    """A book's totals line: half-point steps around the base, with optional straddle."""
    step = rng.choice([-0.5, 0.0, 0.0, 0.0, 0.5]) + straddle * 0.5
    return round((base + step) * 2) / 2 - 0.5  # land on a .5 line


def _generate_event(rng: random.Random, sport_key: str, idx: int, now: datetime) -> tuple[Event, list[OddsQuote]]:
    meta = SPORTS[sport_key]
    teams = list(cast("list[str]", meta["teams"]))
    rng.shuffle(teams)
    home, away = teams[0], teams[1]
    commence = now - timedelta(days=rng.randint(1, 9), hours=rng.randint(0, 23))
    event_id = f"{sport_key}-{idx}"
    event = Event(
        id=event_id,
        sport_key=sport_key,
        sport_title=str(meta["title"]),
        commence_time=commence,
        home_team=home,
        away_team=away,
    )

    base_total = float(meta["total"])  # type: ignore[arg-type]
    base_margin = round(rng.uniform(1.5, 9.5) * 2) / 2 - 0.5  # a half-point spread line
    true_home_prob = rng.uniform(0.35, 0.65)
    make_total_middle = rng.random() < 0.45
    make_spread_middle = rng.random() < 0.30
    make_h2h_arb = rng.random() < 0.18

    quotes: list[OddsQuote] = []
    # Snapshots from ~48h out to ~3h out before commence.
    for hours_out in (48, 36, 24, 12, 6, 3):
        observed = commence - timedelta(hours=hours_out)
        if observed >= now:
            continue
        for b_i, book in enumerate(BOOKS):
            vig = 0.0 if book in SHARP else rng.uniform(0.03, 0.06)

            # ── h2h ──
            hp = min(0.95, true_home_prob + vig / 2 + rng.uniform(-0.01, 0.01))
            ap = min(0.95, (1 - true_home_prob) + vig / 2 + rng.uniform(-0.01, 0.01))
            home_odds, away_odds = _decimal_from_prob(hp), _decimal_from_prob(ap)
            if make_h2h_arb and b_i == 0:
                home_odds = round(home_odds * 1.18, 2)  # one book overshoots the home side
            if make_h2h_arb and b_i == 1:
                away_odds = round(away_odds * 1.18, 2)  # another overshoots the away side
            quotes.append(_q(event, book, "h2h", home, None, home_odds, observed))
            quotes.append(_q(event, book, "h2h", away, None, away_odds, observed))

            # ── totals ── (seed a cross-book middle on two designated books)
            straddle = 0
            if make_total_middle and book == "sportsbet":
                straddle = -1  # offers a lower line → its Over is the middle's over leg
            elif make_total_middle and book == "tab":
                straddle = 1  # offers a higher line → its Under is the middle's under leg
            line = _book_total_line(base_total, rng, straddle)
            o_price = _decimal_from_prob(0.5 + vig / 2 + rng.uniform(-0.02, 0.02))
            u_price = _decimal_from_prob(0.5 + vig / 2 + rng.uniform(-0.02, 0.02))
            if make_total_middle and book in ("sportsbet", "tab"):
                o_price = u_price = round(rng.uniform(1.92, 1.98), 2)  # juicy near-even prices
            quotes.append(_q(event, book, "totals", "Over", line, o_price, observed))
            quotes.append(_q(event, book, "totals", "Under", line, u_price, observed))

            # ── spreads ── (seed an occasional cross-book middle on two books)
            s_straddle = 0.0
            if make_spread_middle and book == "pointsbetau":
                s_straddle = -0.5  # offers a tighter home line → the over leg
            elif make_spread_middle and book == "ladbrokesau":
                s_straddle = 0.5  # offers a wider away line → the under leg
            s_line = base_margin + rng.choice([-0.5, 0.0, 0.0, 0.0, 0.5]) + s_straddle
            sp = _decimal_from_prob(0.5 + vig / 2 + rng.uniform(-0.02, 0.02))
            if make_spread_middle and book in ("pointsbetau", "ladbrokesau"):
                sp = round(rng.uniform(1.92, 1.98), 2)
            quotes.append(_q(event, book, "spreads", home, -s_line, sp, observed))
            quotes.append(_q(event, book, "spreads", away, s_line, sp, observed))

    return event, quotes


def _q(event: Event, book: str, market: str, name: str, point: float | None, price: float, when: datetime) -> OddsQuote:
    return OddsQuote(
        event_id=event.id,
        sport_key=event.sport_key,
        commence_time=event.commence_time,
        bookmaker=book,
        market_key=market,
        outcome_name=name,
        point=point,
        price=price,
        observed_at=when,
    )


def generate(db_path: str, n_events: int, seed: int) -> None:
    """Populate a DuckDB history with synthetic odds for ``n_events`` fixtures."""
    rng = random.Random(seed)
    now = datetime.now(UTC)
    sport_keys = list(SPORTS)
    with HistoryStore(db_path) as store:
        for i in range(n_events):
            sport_key = sport_keys[i % len(sport_keys)]
            event, quotes = _generate_event(rng, sport_key, i, now)
            store.upsert_events([event])
            store.write_quotes(quotes)
        log.info("seeded %d events, %d quotes → %s", n_events, store.quote_count(), db_path)


def main() -> None:
    """CLI: seed synthetic history and render a demo backcast report."""
    setup_logging()
    parser = argparse.ArgumentParser(description="Seed a synthetic odds history and render a demo report.")
    parser.add_argument("--db", default="data/demo.duckdb")
    parser.add_argument("--events", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--report", default="reports/backcast-demo.html")
    args = parser.parse_args()

    generate(args.db, args.events, args.seed)
    config: AppConfig = load_config()
    with HistoryStore(args.db) as store:
        result = run_backcast(store, config)
    render_report(result, config, args.report)
    log.info("demo report ready → %s", args.report)


if __name__ == "__main__":
    main()
