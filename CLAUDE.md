# middler — Pre-match Middling & Arbitrage Detector

Spots betting **middles** and **arbitrage** across AU-licensed bookmakers pre-match,
records everything, alerts on Telegram, produces a browser report, and can
semi-automatically place the Betfair leg. Full brief: `betting-middling-detector-proposal.md`.

## The one rule that matters
**The detection and stake-sizing maths is sacred — deterministic arithmetic only.**
No probabilistic model, RNG, or LLM may ever touch a number with money on it
(proposal §3, §8). `middler/detection/` and `middler/place/` must not import
`random`, `numpy.random`, `sentence_transformers`, `anthropic`, or `openai` — a
pre-commit hook (`no-rng-in-detection`) enforces this. If you change the maths in
`middler/detection/maths.py`, the hand-worked tests in `tests/test_maths.py` must
still pass; they are the proof of correctness a reviewer checks without trusting the code.

## Other invariants
- **Pre-match only.** Online in-play betting is illegal in AU. The scheduler drops
  any event at commence and never polls a live market.
- **UTC internally, Sydney at the edge.** All logic uses tz-aware UTC; convert to
  `Australia/Sydney` only for display (`middler/timeutil.py`).
- **Never auto-place an unverified line.** Placement is refused unless the
  opportunity passed the sharp-reference filter (`reference_verified`). The
  **bookmaker leg is always placed by a human** — only the Betfair exchange leg is
  ever automated, and only behind `PLACEMENT_ENABLED=true` + a Betfair key.
- **Record first.** Every odds observation goes to DuckDB before detection, so the
  backcast accumulates for free.

## Layout
```
middler/
  detection/   maths.py (SACRED), engine.py (market→over/under mapping, filters)
  ingest/      odds_api.py (The Odds API), feed.py (Feed protocol), normaliser.py
  store/       history.py (DuckDB: quotes/opps/events/results), hot.py (Redis + in-memory fallback)
  schedule/    state_machine.py (lifecycle), scheduler.py (adaptive cadence)
  backcast/    replay.py (replays history through the LIVE engine), report.py (self-contained HTML)
  alert/       telegram.py (pure format_alert + async Alerter), deeplinks.py
  match/       entity.py (exact→alias→rapidfuzz→optional embedding, confidence-gated)
  place/       betfair.py (evaluate_placement guard + dry-run-default placement)
  tools/       seed_demo.py, get_chat_id.py, backup.py
  app.py       orchestrator loop;  config.py  settings(.env)+AppConfig(config.yaml);  models.py
tests/         pytest, real DuckDB/in-memory (no mocks)
config.yaml    non-secret operating config (sports, markets, thresholds, cadence)
.env           secrets (copy from .env.example) — never committed
```

## Commands (uv)
```bash
uv sync --extra dev            # set up the environment
uv run pytest -q               # tests (70+, all green)
uv run ruff check middler tests && uv run ruff format middler tests
uv run mypy                    # strict, clean
uv run middler                 # run the live alert-only loop (needs API keys)
uv run python -m middler.tools.seed_demo   # build a populated DEMO report with no keys
uv run middler-report          # backcast the real recorded history → reports/backcast.html
docker compose up -d           # deploy (middler + redis, outbound-only)
```

## Conventions
- uv + `pyproject.toml`; Python 3.13; ruff (120 cols, `E F W I UP B SIM`); mypy strict.
- Google-style docstrings; type hints on all signatures. Australian English in prose.
- Tests with pytest, **no mocks** for DB/integration — use real DuckDB temp files and
  the in-memory hot backend.
- Simple over clever; don't add error handling, feature flags, or future-proofing that
  isn't needed.

## Status & what's still manual (not code — credentials/money)
Phases 0–7 are built and tested. The remaining steps are human actions, in order
(see README "Manual actions"): free API keys + Telegram bot (before live running);
Telegram chat id; then — only once the backcast and a fortnight's forward-test prove
it — open/fund Betfair and buy the ~A$940 live key. Keep `PLACEMENT_ENABLED=false`
until then.

## Heads-up
- No git remote yet — flag and offer to create one (`kieranpjobrien`) before relying on push.
- Second odds feed (odds-api.io) is a documented extension point (`Feed` protocol), not
  yet implemented — The Odds API is the working foundation.
- Live Betfair placement needs odds-api event → Betfair `market_id`/`selection_id`
  resolution (`listMarketCatalogue`); deliberately not wired so nothing places by accident.
