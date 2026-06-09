# API sign-up guide — free tiers for the backtest

What to sign up for, what each gives us, and **whether we can get historical data**
(the thing that decides between an *instant* backtest and a ~2-week self-recorded
one). All keys go into your local **[`.env`](.env.example)** — copy
[`.env.example`](.env.example) to `.env` and paste them in.

> Short answer on historical: **yes, a free backtest is realistic.** One provider
> (**OddsPapi**) includes multi-book historical on its free tier, and there's a free
> Australian CSV dataset (**AusSportsBetting**) plus Betfair's free historical sample.
> The Odds API and SportsGameOdds keep historical behind paid plans (SportsGameOdds'
> 7-day trial is a free window). And remember middler records everything from day one,
> so even with zero historical a backtest builds itself for free in ~2 weeks.

## The shortlist (7)

| # | Provider | Free tier | Historical data | AU books + AFL/NRL | Role here | Sign up |
|---|----------|-----------|-----------------|--------------------|-----------|---------|
| 1 | **OddsPapi** ⭐ | 250 requests/mo, no card; 1 request = all books | **Yes — included free, no penalty** (the key one) | 350+ books incl Pinnacle; confirm AFL/NRL on signup | **Instant backtest feed** (client TBD) | [oddspapi.io](https://oddspapi.io) |
| 2 | **The Odds API** | ~500 credits/mo (current odds) | Paid only (10× credit multiplier, back to 2020) | ~40 AU/soft books, no sharps on free | **WIRED — primary feed** | [the-odds-api.com](https://the-odds-api.com) |
| 3 | **SportsGameOdds** | Free tier + **7-day trial** of a paid plan | Closing odds = paid (the 7-day trial is a free window) | 80+ incl Pinnacle; AU: Sportsbet, Ladbrokes, TAB, PointsBet, Betr | Extra feed / trial backtest (client TBD) | [sportsgameodds.com](https://sportsgameodds.com) |
| 4 | **odds-api.io** | 2 books, 100 req/hour | Unclear on free (only 2 books anyway) | AU region supported | **WIRED — secondary feed** | [odds-api.io](https://odds-api.io) |
| 5 | **Betfair** | **Free *delayed* App Key**; live key ~A$940 later | **Free historical *sample***; full depth paid ([historicdata.betfair.com](https://historicdata.betfair.com)) — exchange-only | Betfair AU exchange (the sharp + the lay leg) | **WIRED guard**; unlocks the lay strategy | [developer.betfair.com](https://developer.betfair.com) |
| 6 | **OpticOdds** | Free **trial on request** (no public pricing) | Yes — full price-history endpoint | 100+ books, 25+ sports | Premium trial backtest (client TBD) | [opticodds.com](https://opticodds.com) |
| 7 | **AusSportsBetting** | **Free CSV/Excel download** (no signup, no API) | **Yes — AFL/NRL/NBL results + odds back to ~2013** (open/min/max/close for H2H, line, total) | AU-specific | Calibration + closing-line backtest | [aussportsbetting.com/data](https://www.aussportsbetting.com/data/) |

⭐ = best single signup for a free multi-book historical backtest.

## Will we get historical data? — the honest detail

- **Middling needs *multi-bookmaker* historical** (two books with different lines at the
  same past moment). Only true multi-book historical does this:
  - **OddsPapi** — free, multi-book, 250 req/mo. Enough for a *modest* instant backtest
    (each request returns all books for a snapshot). **This is the one to get.**
  - **The Odds API / SportsGameOdds / OpticOdds** — multi-book historical too, but paid
    (SportsGameOdds' 7-day trial and OpticOdds' trial are free windows worth using).
- **AusSportsBetting** gives free AU history but only a few price points (open/min/max/close)
  from aggregated books — brilliant for **calibrating the result distributions** (how often a
  total/margin actually lands in a 1-point window) and a closing-line sanity check, but not a
  full live-middle replay.
- **Betfair historical** is free at sample level and deep when paid, but **exchange-only** —
  it can't show a cross-book middle. Its value is calibrating priors and modelling the lay leg.

**Bottom line:** sign up for **OddsPapi** for the instant backtest, grab the free
**AusSportsBetting** CSVs for calibration, and get the free **Betfair delayed key** for the
lay strategy. That trio is $0 and covers it.

## Recommended order (all free)

1. **The Odds API** + **odds-api.io** — these two are already wired; the moment you paste the
   keys, `uv run middler` starts recording real multi-book data (the self-recorded backtest).
2. **OddsPapi** — the instant historical backtest. Tell me when you've got the key and I'll
   wire the client (it's a quick follow-on behind the existing `Feed` protocol).
3. **Betfair delayed key** — unlocks the lay-strategy detector and placement mapping. I'll
   write the cert-login walkthrough when you're ready.
4. *(optional)* **SportsGameOdds** / **OpticOdds** free trials if you want a bigger or
   sharper historical pull; **AusSportsBetting** CSVs anytime for calibration.

## Which key goes where (`.env`)

Copy [`.env.example`](.env.example) → `.env`, then fill:

| `.env` variable | Provider | Status |
|---|---|---|
| `THE_ODDS_API_KEY` | The Odds API | wired (primary) |
| `ODDS_API_IO_KEY` | odds-api.io | wired (secondary) |
| `ODDSPAPI_KEY` | OddsPapi | slot ready, client TBD |
| `SPORTSGAMEODDS_KEY` | SportsGameOdds | slot only |
| `OPTICODDS_KEY` | OpticOdds | slot only |
| `BETFAIR_APP_KEY` (+ `BETFAIR_USERNAME` / `PASSWORD` / `CERT_FILE` / `KEY_FILE`) | Betfair | wired guard; lay-detector TBD |
| — (CSV download) | AusSportsBetting | no key needed |

## Caveats

- **Confirm AFL/NRL/NBL + AU-book coverage on signup** — most of these lead with US/UK
  markets; AU depth varies. A 30-second check of their `/sports` or coverage page saves grief.
- Free tiers have caps (OddsPapi 250 req/mo, The Odds API 500 credits/mo) — fine for a backtest
  and a fortnight's forward-test, not for hammering every market every minute.
- OddsPapi's "free historical" is per their own marketing — worth a quick verify against their
  docs once you're in, but multiple sources corroborate it.
- Only **The Odds API** and **odds-api.io** have clients today. OddsPapi / SportsGameOdds /
  OpticOdds are quick to add (the `Feed` protocol exists) — sign up for whichever you like and
  I'll wire the one(s) you land.

*Sources: provider pricing/docs pages linked above, and the
[2026 odds-API comparison](https://oddspapi.io/blog/odds-api-pricing-2026-comparison/).*
