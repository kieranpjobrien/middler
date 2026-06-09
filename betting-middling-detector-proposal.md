# Pre-Match Middling & Arbitrage Detector — Build Proposal

*A system to spot betting "middles" and arbitrage opportunities across Australian bookmakers, alert you in real time, and (optionally) place the exchange leg semi-automatically.*

---

## 0. How to read this document

This file has two audiences:

- **The Operator** — the technically capable person who will hand this to **Claude Code**, run the build, and set it up on a Raspberry Pi. Sections 4–6 are written for you (and for Claude Code).
- **The Reviewer** — an intelligent but non-code-literate collaborator who wants to understand what this is and whether it works, *without installing anything*. Sections 1, 2, 7, 8, 9 and the Glossary are written in plain English for you. You will never need a terminal: you'll review a report in your web browser and receive alerts on Telegram. That's it.

Throughout, look for these callouts:

> **MANUAL ACTION —** something a human must do (Claude Code can't), with the right moment to do it.

> **MANUAL ACTION (SPEND / IRREVERSIBLE) —** the same, but it costs money or can't be undone. Deliberately deferred until the system has proved itself.

**Using this with Claude Code:** hand it the whole file and ask it to begin at **Phase 0**, complete phases **in order**, and **pause at every MANUAL ACTION callout** so the Operator can act before continuing.

---

## 1. What this is (plain English)

Different bookmakers price the same event slightly differently. Two related opportunities arise:

- **Arbitrage** — backing *both sides of the same line* across two books where the prices, combined, guarantee a small profit whatever the result. Rare and short-lived.
- **Middling** — backing two *overlapping* lines. Example: one book offers **Under 72.5**, another offers **Over 71.5**. If the result lands in the gap (here, exactly 72), **both bets win**. Outside the gap, one wins and one loses, and you either break even or lose a small, known amount. You pay a little on most results to win big when the middle hits. Middles are more durable than pure arbs, which makes them the realistic target.

**The legal frame (Australia).** This shapes the entire design:

- **Pre-match only.** Online in-play (live) betting on sport is prohibited in Australia. The system therefore only ever looks at markets *before* they start, and stops the moment an event goes live. This is a feature, not a limitation — durable pre-match middles are exactly what's reachable.
- **Funding.** Online wagering can't be funded by credit card or cryptocurrency. Bankroll is debit/bank only.
- **You, the punter, aren't the regulated party** — the rules target operators — but they define what's available: AU-licensed books, pre-match.

**What you'll actually see.** Two things, both requiring zero technical skill from the Reviewer:

1. A **Telegram alert** when an opportunity appears, with the two books, the lines, the stake split, and the expected value — plus buttons that open each bookmaker at the right market.
2. A **browser report** (a single web page, no install) showing what the system has found or *would have* found. See the next section.

---

## 2. The approach: prove it before spending a cent

We validate in three stages, and only reach real money at the end. Critically, the first two stages risk **nothing** and produce evidence the Reviewer can see.

1. **Backcast (hindcast).** Replay historical odds through the detection engine and produce a shareable HTML report: *"Over the last N weeks, the system would have flagged X middles, averaging Y points wide, with Z% landing in the middle, for an estimated return of…"* This is the centrepiece for convincing the Reviewer — it opens in any browser, shows charts and a table, and needs no software on their part.
2. **Forward-test (paper trading).** Run the system live in **alert-only** mode for a fortnight. It sends real Telegram alerts but places no bets. This confirms the backcast holds up on live data.
3. **Semi-automatic live.** Only now do we add real placement (see Phase 6 and the design note below).

> **MANUAL ACTION —** The system records everything it sees from day one, so the forward-test naturally accumulates the data the backcast replays, **for free**. If you want an *instant* backcast for the Reviewer before data accumulates, you can optionally buy a short window of paid historical data (one-off, see costs). Decide this at Phase 3.

**A hard design rule on placement.** The exchange leg (Betfair) *can* be placed automatically via a sanctioned API. The bookmaker leg *cannot* — no Australian corporate bookmaker offers a betting API, and automating their websites breaches their terms and gets accounts closed fast. So the system is **semi-automatic**: one tap fires the Betfair leg; the bookmaker leg is opened for you to confirm by hand. Full hands-off placement is deliberately out of scope because it's self-defeating.

---

## 3. Scope

**In scope**
- Pre-match middles and arbitrage across AU-licensed bookmakers.
- Markets where middling lives: totals (over/under) and handicaps/spreads, plus head-to-head for arbs.
- An adaptive scheduler that watches upcoming markets, ramps polling as events near, and stops at kick-off.
- Telegram alerts with bookmaker deep-links and a stake calculator.
- A backcast/report module producing a self-contained HTML report.
- Optional semi-automatic placement of the Betfair leg.

**Out of scope (and why)**
- **In-play betting** — illegal online in AU.
- **Scraping bookmaker sites** — breaches terms, gets blocked, torches accounts.
- **Any LLM in the maths** — detection and stake sizing are deterministic arithmetic; a probabilistic model could hallucinate a number with money on the line. Never.
- **Predicting outcomes** — this is market-neutral; we exploit price gaps, we don't forecast winners.

---

## 4. Architecture (for the Operator / Claude Code)

### 4.1 Components

| Component | Job |
|---|---|
| **Discovery loop** | Periodically lists upcoming fixtures (cheap/free endpoints) and adds them to a watch-list. |
| **Scheduler / state machine** | Decides what to poll and when; promotes/retires events through their lifecycle. |
| **Ingestion + normaliser** | Pulls odds, maps every provider into one common schema. |
| **Entity matcher** | Matches the same event/team/player across books (fuzzy first, embedding fallback). |
| **Hot store (Redis)** | Current best line per event/market/book. |
| **History store (DuckDB)** | All observed odds, for the backcast and audit. |
| **Detection engine** | Finds middles + arbs, computes EV and stake splits. Pure arithmetic. |
| **Alerter (Telegram)** | Pushes opportunities with deep-links and a confirm button. |
| **Backcast + report** | Replays history through the engine; emits a shareable HTML report. |
| **Placement (optional)** | Fires the Betfair leg on confirmation; opens the bookmaker leg for manual placement. |

### 4.2 Event lifecycle (state machine)

```
SCHEDULED ──(commence_time enters 72h window)──▶ ACTIVE
ACTIVE ──(polled on a ramping cadence; lines compared)──▶ ACTIVE
ACTIVE ──(commence_time passes)──▶ LIVE   [polling suspended — cannot bet in-play in AU]
LIVE ──(event ends)──▶ SETTLED            [purged from polling; data retained in DuckDB]
```

- A **slow, free discovery loop** populates `SCHEDULED`.
- A **fast odds loop** polls only `ACTIVE` events via a priority queue keyed on `next_poll_time`: pop what's due, fetch, recompute `next_poll_time` from time-to-commence and recent volatility, reinsert — but **drop instead of reinsert once `commence_time` passes**.
- All time logic runs in **UTC**; convert to Sydney time only for display.

### 4.3 Data feeds (free-first)

- **The Odds API** — foundation. Free tier ~500 credits/month (credits = markets × regions per call; one call returns all games for a sport with all books in a region). Has an `au` region and the markets we need. Key endpoints: `/sports` and `/events` (both free of credits — used for discovery), `/odds` (filter with `commenceTimeFrom`/`commenceTimeTo`, target with `eventIds` and `bookmakers`).
- **odds-api.io** — 100 requests/hour, free forever. The real free workhorse for frequent polling.
- **OddsPapi** — free tier bundling many bookmakers (incl. sharp references like Pinnacle) per call — useful as a sanity check.
- **Betfair Exchange API** — *delayed* app key is free (development + modelling); *live* key needed for real-time placement (one-off fee, see costs). Sanctioned programmatic placement via `placeOrders`.

A key insight for budgeting: you pay per **request**, but one request returns hundreds of **odds quotes** (all games × all books). The number of requests scales with *markets × polling cadence × simultaneous events* — not with how many odds you observe. Adaptive cadence (poll dead markets rarely, hot markets often, in-play never) is what keeps a fixed budget covering a large universe.

### 4.4 Detection maths (specify exactly — no approximation)

- **Implied probability** of decimal odds `d`: `p = 1/d`.
- **Arbitrage**: for two opposing outcomes on the *same* line at odds `d1`, `d2`, an arb exists when `1/d1 + 1/d2 < 1`. Profit margin `= 1 − (1/d1 + 1/d2)`. Stake split for total `T`: `stake_i = T · (1/d_i) / (1/d1 + 1/d2)`.
- **Middle**: for `Under X @ d_a` and `Over Y @ d_b` with `Y < X`, the middle window is `(Y, X)`. Compute (a) the non-middle outcome P/L under the chosen stake split, and (b) the both-win payout. Flag with an **estimated EV** using the historical frequency of results landing in the window (the backcast estimates this per market type).
- **Stake sizing**: configurable — equal stakes, balanced to equalise the non-middle outcomes, or a fractional-Kelly stake on the middle. Default: balanced.
- **Sanity filter**: compare each line against a sharp reference (Pinnacle/Betfair). Drop "edges" that are just one book being wrong rather than genuinely off, and **never auto-place on an unverified line**.

### 4.5 Stack & deployment

- **Language**: Python.
- **Data**: Polars + DuckDB (analytics/history), Redis (hot state).
- **Bot**: `python-telegram-bot` (use inline **callback buttons**, not emoji reactions — reactions don't fire in 1:1 chats).
- **Matching**: `rapidfuzz` (cheap) + a `sentence-transformers` embedding model (fallback only; runs on the Pi's CPU).
- **Placement**: Betfair API client.
- **Host**: Raspberry Pi 5, Docker Compose, **outbound-only** (no inbound ports — alerts and placement all go *out*, so no port-forwarding or static IP needed). Boot from SSD/NVMe, not microSD, for endurance.
- **Repo**: single command to stand up (`docker compose up`), with a short written runbook so the Operator can deploy without bespoke knowledge.

---

## 5. Build phases (for Claude Code)

Each phase is a milestone; complete in order; pause at MANUAL ACTION callouts.

**Phase 0 — Scaffold.** Repo structure, config (`.env` for keys, a YAML for sports/markets/books/thresholds), Docker Compose for Python + Redis + DuckDB, logging, and a stub healthcheck.

**Phase 1 — Discovery + ingestion + recording.** Implement `/sports` and `/events` discovery, the state machine, the odds-fetch (windowed with `commenceTimeFrom`/`commenceTimeTo`), the normaliser, and write **everything** to DuckDB. No detection yet. *Outcome: the system is quietly recording real data.*

> **MANUAL ACTION —** *Before Phase 1.* Sign up for the free API keys (The Odds API, odds-api.io, OddsPapi) and create a Telegram bot via **@BotFather** to get a bot token. Paste these into `.env`. (All free, ~15 minutes.)

**Phase 2 — Detection engine.** Implement the arb and middle maths in §4.4, the stake-sizing options, and the sharp-reference sanity filter. Ship with **unit tests on known hand-worked cases** so the arithmetic is provably correct.

**Phase 3 — Backcast + HTML report.** Replay DuckDB history through the engine; produce a single self-contained HTML report (summary stats, charts of opportunity frequency/width over time, and a sortable table of every opportunity). *This is the deliverable you send the Reviewer.*

> **MANUAL ACTION —** *At Phase 3.* Decide whether to (a) wait ~2 weeks for self-recorded data to backcast on (free), or (b) buy a short window of paid historical data for an instant demo (one-off cost — see §7). Recommended: start with (a); use (b) only if you need to show the Reviewer immediately.

**Phase 4 — Telegram alerter (alert-only).** Push opportunities with the stake split, EV, and **deep-link buttons** to each bookmaker's market. No placement yet — this is the forward-test. Run for a fortnight.

> **MANUAL ACTION —** *Before Phase 4.* Send your bot a message and capture the chat ID into `.env` (Claude Code will provide a tiny helper for this). Add the Reviewer's Telegram too if they should receive alerts. (Free, ~2 minutes.)

**Phase 5 — Entity matcher.** Add `rapidfuzz` matching with alias tables, then the `sentence-transformers` embedding fallback for hard cases, **gated by a confidence threshold**. Low-confidence matches are flagged, never auto-actioned.

**Phase 6 — Semi-automatic placement (optional).** On a confirmation button, fire the **Betfair leg** via `placeOrders` and simultaneously open the bookmaker leg for manual confirmation. Include a confirmation handshake, a two-step confirm above a stake threshold, sensible leg-ordering (place the faster-moving leg first), and full logging. The bookmaker leg is **always** placed by a human.

> **MANUAL ACTION (SPEND / IRREVERSIBLE) —** *Before Phase 6, and only once the backcast + forward-test have proved it's worth it:*
> 1. Open accounts with your chosen AU bookmakers (free).
> 2. Open and fund a **Betfair** account (debit/bank — not credit/crypto).
> 3. Place at least one bet via the free **delayed** key (a prerequisite for live-key activation).
> 4. Purchase the **Betfair Live App Key** (~A$940 one-off). *Do not do this until the evidence justifies it.*

**Phase 7 — Hardening.** Docker `restart: always`, an external uptime monitor (e.g. healthchecks.io — free) that pings you if the Pi goes silent, and a nightly DuckDB/config backup to the Operator's NAS or cloud.

> **MANUAL ACTION (ONGOING) —** When an alert fires and you choose to act, **place the bookmaker leg yourself** in the opened app/site. This step is never automated, by design.

---

## 6. Manual actions — consolidated checklist

In sequence, with the right moment for each:

1. **Before Phase 1 —** Free API keys + Telegram bot token. *(Free.)*
2. **Before Phase 4 —** Telegram chat ID(s). *(Free.)*
3. **At Phase 3 —** Choose free-by-waiting vs paid-instant backcast data. *(Optional one-off cost.)*
4. **Before Phase 6 —** Open bookmaker accounts; open + fund Betfair; place one bet on the delayed key. *(Funding required.)*
5. **Before Phase 6 —** ⚠️ Buy the Betfair Live App Key (~A$940). *(Only after the concept is proven.)*
6. **Ongoing —** ⚠️ Place each bookmaker leg by hand when you choose to act on an alert.
7. **Ongoing —** Keep bankroll funded via debit/bank only.

The guiding principle: **all free, reversible setup happens early; all spending and irreversible commitments are deferred until the backcast and forward-test have demonstrated value.**

---

## 7. Costs (AUD)

Two levers drive cost: **monthly ≈ which data feed you choose**; **one-off ≈ whether you buy the Betfair Live key** (plus the Pi). The Betfair key is priced in GBP (~£499 ≈ ~A$940) and data feeds in USD, so figures drift with exchange rates.

**Tiers**
- **Low** — free APIs, Pi host, *manual* placement. Prove the concept.
- **Medium** — adds the Betfair Live key for one-tap semi-auto placement; optional paid data tier for more polling headroom.
- **High** — premium real-time streaming feed (sharp books included), Betfair key, robust host.

**Monthly**

| Item | Low | Medium | High |
|---|---|---|---|
| Odds data | Free | Free–$50 | $140–700 |
| Hosting (Pi) | $1–2 | $1–2 | $1–2 |
| Alerts (Telegram) | Free | Free | Free |
| **≈ per month** | **$1–2** | **$2–50** | **$140–700** |

**One-off**

| Item | Low | Medium | High |
|---|---|---|---|
| Pi build (board, cooler, PSU, case, SSD/NVMe) | $180–200 | $250–300 | $250–300 |
| Betfair Live key | — | ~$940 | ~$940 |
| Extras (Pushover, UPS HAT) | — | ~$50 | ~$50 |
| **≈ one-off** | **$180–200** | **~$1,250** | **~$1,250** |

Notes: swap the Pi for a small cloud instance and hosting becomes ~A$10–30/month with no hardware one-off; an existing NAS or a free-forever cloud tier is $0 host and $0 one-off. The only other ongoing cost is Betfair's commission on net winnings (a cost of betting, not of running the system). At Low, the real "cost" is build time, not cash.

**Recommended path:** start at Low; run the backcast and a fortnight's forward-test; only spend the ~A$940 on the Betfair key once it's earning its keep; only move to High's premium feed if the free feeds prove too slow or thin. Most setups never need High.

---

## 8. Risks & honest caveats

- **Account limiting ("gubbing")** — bookmakers detect and restrict winning arbers/middlers, often within weeks. This is the biggest real-world risk, and the reason the Betfair exchange leg matters: exchanges don't punish winners.
- **Leg-out risk** — when you fire the Betfair leg but still confirm the bookmaker leg by hand, the bookmaker price can move in between. Mitigated (not eliminated) by leg-ordering and tight confirmation.
- **Home uptime** — a Pi depends on home power/internet. Fine for pre-match (not millisecond) alerting; mitigated by restart policies, an uptime monitor, and a UPS.
- **FX** — costs are GBP/USD underneath, so AUD figures move with exchange rates.
- **Golf specifically** — golf middling lives in niche, often per-event-priced score markets that move mostly in-play. For AU pre-match, **team-sport totals/handicaps (NRL, AFL, NBA, NFL)** are the richer, more durable, legally-placeable hunting ground. Golf is opportunistic, not the backbone.
- **The maths is sacred** — no probabilistic model ever touches detection or stake sizing.

---

## 9. What the Reviewer needs to do

Almost nothing:

1. Install **Telegram** on your phone and accept the bot (the Operator sends a link).
2. Open the **HTML report** link the Operator sends you — it opens in any browser, no install, and shows what the system has found or would have found.
3. *(Only if you intend to bet)* place the bookmaker leg yourself when an alert you like comes through.

You never touch a terminal, a server, or any code. The Operator handles all setup and runs it on a small device at home. GitHub is there if you're curious, but you're not expected to build or install anything.

---

## Glossary (plain English)

- **Middle** — backing two overlapping lines so that if the result lands in the gap, both bets win; otherwise you roughly break even.
- **Arbitrage (arb)** — backing both sides of the same line across two books for a guaranteed small profit. Rare.
- **Line** — the number a bet is set against, e.g. "Over/Under 72.5".
- **Decimal odds** — the multiplier on a winning stake (1.91 means $100 returns $191).
- **Vig / margin** — the bookmaker's built-in edge; why most non-middle outcomes lose a sliver.
- **EV (expected value)** — the average outcome of a bet if repeated many times; positive EV means it pays off on average.
- **Pre-match** — before the event starts; the only legal online betting window for sport in Australia.
- **Backcast / hindcast** — replaying past odds through the system to show what it *would* have caught, with no money at risk.
- **Forward-test / paper trading** — running live but placing no bets, to confirm the backcast holds up.
- **Exchange (Betfair)** — a peer-to-peer marketplace where you can *lay* (bet against) outcomes and which doesn't ban winners.
- **State machine** — the rules deciding when a market is watched, polled hard, or dropped at kick-off.

---

*Prepared as a build brief. Hand to Claude Code starting at Phase 0; share Sections 1–2, 7–9 and the Glossary with the Reviewer.*
