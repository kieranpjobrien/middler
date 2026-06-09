# middler

A system that spots pre-match betting **middles** and **arbitrage** across
AU-licensed bookmakers, records everything it sees, alerts you on Telegram, and
produces a browser report you can share. It can also semi-automatically place the
Betfair exchange leg once you've proven it's worth it.

> Full design brief and the plain-English explanation for a non-technical reviewer:
> [`betting-middling-detector-proposal.md`](betting-middling-detector-proposal.md).

Two related opportunities: an **arbitrage** backs both sides of the same line
across two books for a guaranteed small profit; a **middle** backs two overlapping
lines (e.g. Over 71.5 at one book, Under 72.5 at another) so that if the result
lands in the gap, *both* bets win. Detection and stake sizing are pure deterministic
arithmetic — no model ever guesses a number that has money on it.

## See it now (no accounts, no keys)

```bash
uv sync --extra dev
uv run python -m middler.tools.seed_demo          # fabricates a realistic history
```

Open **`reports/backcast-demo.html`** in any browser. It's a single self-contained
file (charts + a sortable table of every opportunity the engine would have flagged)
— exactly what the Reviewer receives. The data is synthetic, but it runs through the
identical live detection engine.

## How it works

```
discovery (free /events) ──► scheduler ──► poll odds (adaptive cadence) ──► record (DuckDB)
                                                                              │
                                       detect middles + arbs (pure maths) ◄───┘
                                                  │
                              sharp-reference sanity filter
                                                  │
                         Telegram alert  +  (optional) Betfair leg
```

- **Pre-match only** — online in-play betting is illegal in AU, so the scheduler
  ramps polling as an event nears and **drops it at kickoff**.
- **Records first** — every odds observation lands in DuckDB before detection, so the
  backcast report accumulates for free as the system runs.
- **Semi-automatic placement** — only the Betfair exchange leg can be automated; the
  bookmaker leg is *always* placed by you, by hand (by design — automating bookmaker
  sites breaches their terms and gets accounts closed).

## Validate before spending a cent (proposal §2)

1. **Backcast** — replay recorded history → a shareable HTML report. Risk: none.
2. **Forward-test** — run live in **alert-only** mode for a fortnight. Real alerts,
   no bets.
3. **Semi-automatic live** — only then add real Betfair placement.

## Manual actions (the only things this code can't do)

In order, with the right moment for each. Everything up to step 4 is free.

| When | Action | Cost |
|---|---|---|
| Before running live | Get free API keys (The Odds API, odds-api.io), create a Telegram bot via **@BotFather**. Put them in `.env`. | Free |
| Before alerts | Message your bot, then run `uv run middler-chatid` to get your chat id → `.env`. | Free |
| At backcast | Either wait ~2 weeks for self-recorded data (free) or buy a short window of paid history for an instant demo. | Optional |
| Before placement | Open + fund a **Betfair** account (debit/bank — not credit/crypto); place one bet on the free **delayed** key. | Funding |
| Before placement | ⚠️ Buy the **Betfair Live App Key** (~A$940). **Only after the concept is proven.** | ~A$940 |
| Ongoing | Place each **bookmaker** leg yourself when you act on an alert. Fund bankroll via debit/bank only. | — |

Keep `PLACEMENT_ENABLED=false` in `.env` until the backcast and forward-test justify it.

## Setup

```bash
cp .env.example .env          # then fill in keys (see the table above)
uv sync --extra dev
uv run pytest -q              # 70+ tests, all green
```

Edit [`config.yaml`](config.yaml) for sports, markets, thresholds, and polling cadence
(safe to commit; no secrets).

## Running

```bash
uv run middler                # live alert-only loop (Ctrl-C to stop)
uv run middler-report         # backcast recorded history → reports/backcast.html
uv run middler-backup --dest /mnt/nas/middler-backups   # nightly DB+config backup
```

## Deploy (Raspberry Pi 5 or any host)

```bash
docker compose up -d          # middler + redis, restart-always, outbound-only
docker compose logs -f middler
```

No ports are published — alerts and placement all go *out*, so there's no
port-forwarding or static IP to configure. Boot the Pi from SSD/NVMe, not microSD.
Add a free external uptime monitor by setting `HEALTHCHECK_PING_URL` in `.env`
(e.g. healthchecks.io) — you'll be pinged if the Pi goes silent.

## Costs (AUD, summary)

- **Low** (free APIs, Pi host, manual placement): ~$1–2/month, ~$180–200 one-off Pi.
- **Medium** (adds Betfair live key): ~$2–50/month, ~$1,250 one-off.
- **High** (premium streaming feed): ~$140–700/month.

Start at Low. Most setups never need High. Detail: proposal §7.

## Safety & legal

- AU-licensed books, pre-match only. The system stops at kickoff.
- Funding is debit/bank only (no credit/crypto — a legal requirement).
- The biggest real risk is **account limiting** ("gubbing") — books restrict winning
  middlers; the Betfair exchange leg matters because exchanges don't ban winners.
- The maths never auto-places on a line that disagrees with a sharp reference.
