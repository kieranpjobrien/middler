# Build log — autonomous session 2026-06-09

Kieran handed me the proposal and went out for ~2 hours. Here's what got built,
the decisions I made, and where to pick up.

## TL;DR
The whole system is built and tested — Phases 0–7 of the proposal. The proposal's
"MANUAL ACTION" callouts are all **credentials and money** (API keys, Telegram token,
funding Betfair), none of which block *code*, so I built the lot with secrets stubbed
in `.env.example`. **70 tests pass, mypy strict clean, ruff clean.** ~3,340 lines of
package code across 34 modules, ~1,150 lines of tests, in 5 logical commits.

👉 **Open `reports/backcast-demo.html` in a browser now** — a populated demo report
(synthetic data through the real engine) so you can see the Reviewer deliverable
immediately, before any API keys exist.

## What's built (by phase)
- **0 Scaffold** — uv/`pyproject.toml`, ruff/mypy/pytest, pre-commit (incl. bandit,
  codespell, and a custom hook that bans RNG/ML/LLM imports in the maths), `config.yaml`,
  `.env.example`, `.gitattributes`.
- **2 Detection maths (did this first — it's "sacred")** — implied prob, N-way
  arbitrage with stake split, two-leg middle with equal/balanced splits and
  conservative EV, fractional-Kelly sizing. `tests/test_maths.py` has 23 **hand-worked**
  cases (every expected number computed in a comment) including the proposal's worked example.
- **1 Ingestion + storage** — domain models (Event lifecycle, OddsQuote, Opportunity,
  all UTC); The Odds API client (free discovery + credit-aware odds) behind a `Feed`
  protocol; normaliser; DuckDB history store (records every quote + opportunity + event +
  settled result); Redis hot store with a transparent **in-memory fallback** so it runs
  without Redis.
- **2 Detection engine** — maps totals/spreads/h2h into one over/under abstraction,
  finds middles + arbs across books, sizes stakes, and applies the sharp-reference
  sanity filter (`reference_verified`).
- **Scheduler** — event lifecycle state machine + adaptive poll cadence that ramps
  toward kickoff and **drops events at commence** (never polls in-play).
- **3 Backcast + report** — replays recorded history through the *identical* live engine;
  renders a **self-contained** HTML report (inline plotly: cards, charts, sortable table).
  Sydney-time display, UTC internals.
- **4 Telegram alerter** — pure `format_alert` (unit-tested without network) + async
  sender, bookmaker deep-link buttons; alert-only by default.
- **App orchestrator** — discovery + polling loop, records→detects→alerts, throttles
  duplicate alerts, pings an uptime monitor, clean SIGTERM shutdown.
- **5 Entity matcher** — exact → alias → rapidfuzz → optional embedding fallback,
  confidence-gated (weak matches flagged, never auto-actioned).
- **6 Placement** — `evaluate_placement` guard (tested refusal rules) + Betfair wrapper
  that **defaults to dry-run** and won't place unless enabled, keyed, sharp-verified, and
  carrying a Betfair leg.
- **7 Hardening** — Dockerfile (arm64-ready) + compose (Redis, restart-always,
  outbound-only, healthcheck) + nightly backup tool.
- **Tooling** — `seed_demo` (demo report), `get_chat_id`, `backup`, `healthcheck`.

## Decisions I made without you
- **Built everything, not just the early phases.** The manual actions gate *credentials/
  money*, not code, so pausing would have wasted the window. Nothing money-touching can
  fire: `PLACEMENT_ENABLED` defaults false and the guard refuses on every missing precondition.
- **Stack** matched your existing repos: uv, ruff (120 cols), mypy strict, DuckDB + Polars,
  httpx, pydantic. Added `pyarrow`/`pytz`/`tzdata` (DuckDB↔Polars bridge + tz on Windows),
  `plotly` (self-contained report), `python-telegram-bot`, `rapidfuzz`. `sentence-transformers`
  and `betfairlightweight` are **optional extras** (heavy / money-phase) — not installed by default.
- **EV is deliberately conservative** — uses the worst-case non-middle outcome, so it's a
  lower bound in general and exact under the default balanced split. It will never overstate.
- **Second feed (odds-api.io) not implemented** — left as a clean `Feed`-protocol extension
  point rather than shipping a client I couldn't verify against their live schema. The Odds
  API is the working foundation.
- **Demo data generator** seeds genuine middles/arbs by construction so the report is
  compelling; tuned spread noise down so the opportunity count is believable (~1,560 across
  40 fixtures), not absurd.

## Quality
- `uv run pytest -q` → **70 passed**.
- `uv run mypy` → clean (strict, 34 files). `uv run ruff check` → clean.
- The maths tests are the ones to trust: if `tests/test_maths.py` is green, the arithmetic
  matches the hand-worked numbers.

## What's left / next steps
1. **Git remote** — I initialised git locally and made 5 commits, but there's **no remote**
   (your global rule says to flag this). Nothing is pushed. Say the word and I'll create
   `github.com/kieranpjobrien/middler` (private) and push.
2. **Free keys** (15 min) — The Odds API + Telegram bot → `.env`, then `uv run middler` runs
   live alert-only. That starts the fortnight forward-test and accumulates real history.
3. **odds-api.io client** — implement against the `Feed` protocol when you want frequent-poll
   headroom (proposal §4.3).
4. **Live Betfair** — only after the backcast + forward-test prove it. Needs the odds-api →
   Betfair `market_id`/`selection_id` resolver wired (intentionally left out so nothing
   places by accident) and the live key.
5. Consider raising `config.yaml` detection thresholds before going live — defaults flag even
   marginal middles, which is great for the backcast, noisier for live alerts.

## Files worth a look first
- `reports/backcast-demo.html` — the deliverable, populated.
- `middler/detection/maths.py` + `tests/test_maths.py` — the sacred core and its proof.
- `CLAUDE.md` — project guide for future sessions. `README.md` — operator runbook.
