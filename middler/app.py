"""The orchestrator — discovery, polling, recording, detection and alerting.

One slow, free discovery loop populates the working set from ``/events``; one fast
loop polls only events the scheduler says are due, fetching each sport's active
events in a single windowed ``/odds`` call (cheap — one request returns every game
and book). Everything observed is recorded to DuckDB first, so the backcast
accumulates for free; detection and alerting happen on the same pass.

This is alert-only by default (Phase 4 / forward-test). Placement (Phase 6) is a
separate, money-touching module that stays dormant unless explicitly enabled.
"""

from __future__ import annotations

import calendar
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from middler.alert.telegram import Alerter
from middler.budget import BudgetGuard, caps_from_config
from middler.config import AppConfig, Settings, load_config, load_settings
from middler.detection.engine import detect_opportunities
from middler.ingest.merge import align_and_merge
from middler.ingest.normaliser import normalise_event, normalise_odds_response, quotes_from_event
from middler.ingest.odds_api import OddsApiClient
from middler.ingest.oddsapi_io import OddsApiIoClient
from middler.logging_setup import get_logger, setup_logging
from middler.match.entity import EntityMatcher
from middler.models import Event, EventStatus
from middler.schedule.scheduler import PollScheduler
from middler.schedule.state_machine import is_pollable, next_status
from middler.store.history import HistoryStore
from middler.store.hot import HotStore

log = get_logger(__name__)

ALERT_COOLDOWN_SEC = 1800  # don't re-alert the same structural opportunity within 30 min
SECONDARY_MAX_EVENTS = 10  # per secondary poll: the soonest fixtures (bounds the /odds/multi call)


def _days_left_in_month(now: datetime) -> int:
    """Days remaining in the current calendar month, including today (≥ 1)."""
    return max(1, calendar.monthrange(now.year, now.month)[1] - now.day + 1)


class MiddlerApp:
    """Wires the components into discovery + polling cycles."""

    def __init__(self, settings: Settings, config: AppConfig) -> None:
        self.settings = settings
        self.config = config
        self.client = OddsApiClient(settings.the_odds_api_key, region=config.region)
        self.secondary = (
            OddsApiIoClient(settings.odds_api_io_key, region=config.region) if settings.odds_api_io_key else None
        )
        self.history = HistoryStore(settings.duckdb_path)
        self.hot = HotStore(settings.redis_url)
        self.scheduler = PollScheduler(config.scheduler)
        self.alerter = Alerter(settings.telegram_bot_token, settings.chat_ids)
        self.budget = BudgetGuard(Path(settings.duckdb_path).parent / "budget.json", caps_from_config(config.budget))
        self._matcher = EntityMatcher()
        self._sport_of: dict[str, str] = {}
        self._last_discovery: datetime | None = None
        self._last_secondary: datetime | None = None
        self._last_report: datetime | None = None
        self._stop = False

    # ── discovery (free) ─────────────────────────────────────────────────────
    def discover(self, now: datetime) -> None:
        """List upcoming events per sport and schedule those inside the window."""
        for sport in self.config.sports:
            try:
                raw = self.client.get_events(sport)
            except httpx.HTTPError as exc:
                log.warning("discovery failed for %s: %s", sport, exc)
                continue
            for ev_raw in raw:
                event = normalise_event(ev_raw)
                status = next_status(event.commence_time, now, self.config.scheduler.active_window_hours)
                self.history.upsert_events([event])
                self._sport_of[event.id] = event.sport_key
                if is_pollable(status) and not self.scheduler.is_tracked(event.id):
                    self.scheduler.schedule(event.id, event.commence_time, now)
                elif status in (EventStatus.LIVE, EventStatus.SETTLED):
                    self.scheduler.drop(event.id)
        self._last_discovery = now
        log.info("discovery complete; tracking %d events", self.scheduler.tracked)

    # ── polling (costs credits) ──────────────────────────────────────────────
    def poll_due(self, now: datetime) -> int:
        """Poll all due events (grouped by sport), record, detect and alert.

        Returns:
            The number of opportunities alerted on this cycle.
        """
        due_ids = self.scheduler.due(now)
        if not due_ids:
            return 0
        by_sport: dict[str, list[str]] = {}
        for event_id in due_ids:
            by_sport.setdefault(self._sport_of.get(event_id, ""), []).append(event_id)

        alerted = 0
        window_to = now + timedelta(hours=self.config.scheduler.active_window_hours)
        for sport, ids in by_sport.items():
            if not sport:
                continue
            markets = self.config.markets_for(sport)
            cost = len(markets)
            reserve = self.config.budget.the_odds_api_min_reserve
            remaining = self.budget.remaining("the_odds_api")
            if remaining is None:
                remaining = self.config.budget.the_odds_api_monthly_credits
            daily_budget = max(float(cost), (remaining - reserve) / _days_left_in_month(now))
            if not self.budget.allow(
                "the_odds_api", min_reserve=reserve, daily_credit_budget=daily_budget, next_cost=cost
            ):
                log.info("the_odds_api day's credit budget spent (remaining=%s) — skipping %s", remaining, sport)
                for event_id in ids:
                    self.scheduler.reschedule(event_id, now)
                continue
            try:
                raw = self.client.get_odds(sport, markets, commence_from=now, commence_to=window_to, event_ids=ids)
            except httpx.HTTPError as exc:
                log.warning("odds poll failed for %s: %s", sport, exc)
                for event_id in ids:
                    self.scheduler.reschedule(event_id, now)
                continue
            self.budget.record("the_odds_api", remaining=self.client.remaining_credits, cost=cost)
            events, quotes = normalise_odds_response(raw, observed_at=now)
            # Record the primary feed's observations (the backcast stays single-feed
            # and consistent); the secondary feed only enriches live detection.
            self.history.write_quotes(quotes)
            self.history.upsert_events(events)
            for event in self._enrich_with_secondary(sport, events):
                alerted += self._detect_and_alert(event, now)
            for event_id in ids:
                self.scheduler.reschedule(event_id, now)
        self._ping_healthcheck()
        return alerted

    def _enrich_with_secondary(self, sport: str, events: list[Event]) -> list[Event]:
        """Merge in odds-api.io books for the same fixtures, if configured.

        Returns the events unchanged when the secondary feed is disabled, the
        sport is unmapped, or the secondary call fails — detection then simply
        runs on the primary feed alone.
        """
        if self.secondary is None:
            return events
        slug = self.config.odds_api_io_sport_map.get(sport)
        if not slug:
            return events
        if not self.budget.allow("odds_api_io"):
            log.info("odds-api.io hourly budget reached — skipping enrichment for %s", sport)
            return events
        try:
            io_dicts = self.secondary.get_events(slug)
            io_ids = [str(d["id"]) for d in io_dicts][:50]
            io_events = self.secondary.get_odds(io_ids, self.config.odds_api_io_bookmakers) if io_ids else []
            self.budget.record("odds_api_io", count=2)  # get_events + get_odds
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("secondary feed (odds-api.io) failed for %s: %s", sport, exc)
            return events
        return align_and_merge(events, io_events, self._matcher)

    def _detect_and_alert(self, event: Event, now: datetime) -> int:
        opps = detect_opportunities(
            event,
            detection=self.config.detection,
            staking=self.config.staking,
            sharp_books=self.config.sharp_books,
            hit_rate_prior=self.config.backcast.middle_hit_rate_prior,
            observed_at=now,
        )
        count = 0
        for opp in opps:
            if self.hot.should_alert(opp.signature, ALERT_COOLDOWN_SEC):
                self.history.write_opportunity(opp)
                self.alerter.notify(opp, event)
                count += 1
        return count

    # ── secondary feed: independent, high-frequency odds-api.io polling ──────
    def _maybe_secondary(self, now: datetime) -> None:
        """Poll the secondary feed on its own fast cadence (rate-, not credit-, limited)."""
        interval = self.config.scheduler.secondary_interval_sec
        if interval <= 0 or self.secondary is None:
            return
        if self._last_secondary is not None and (now - self._last_secondary).total_seconds() < interval:
            return
        try:
            self.poll_secondary(now)
        except Exception as exc:  # noqa: BLE001 - the secondary feed must never stop the loop
            log.warning("secondary poll error: %s", exc)
        self._last_secondary = now

    def poll_secondary(self, now: datetime) -> int:
        """Independently poll odds-api.io for near-term fixtures, record and detect.

        Unlike the cross-feed enrichment in :meth:`poll_due`, this runs on its own
        frequent cadence and records the observations — turning odds-api.io's
        Bet365 + Betfair (incl. lay) into high-frequency back-lay and middle signal.

        Returns:
            The number of opportunities alerted on this pass.
        """
        if self.secondary is None:
            return 0
        window_to = now + timedelta(hours=self.config.scheduler.active_window_hours)
        alerted = 0
        for sport in self.config.sports:
            slug = self.config.odds_api_io_sport_map.get(sport)
            if not slug or not self.budget.allow("odds_api_io"):
                continue
            try:
                io_dicts = self.secondary.get_events(slug)
                soon = [d for d in io_dicts if self._io_event_soon(d, now, window_to)]
                soon.sort(key=lambda d: str(d.get("startTime") or d.get("date") or ""))
                io_ids = [str(d["id"]) for d in soon[:SECONDARY_MAX_EVENTS]]
                if not io_ids:
                    self.budget.record("odds_api_io", count=1)
                    continue
                io_events = self.secondary.get_odds(io_ids, self.config.odds_api_io_bookmakers)
                self.budget.record("odds_api_io", count=2)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                log.warning("secondary poll (odds-api.io) failed for %s: %s", sport, exc)
                continue
            for event in io_events:
                event.sport_key = sport
                self.history.write_quotes(quotes_from_event(event, now))
                self.history.upsert_events([event])
                alerted += self._detect_and_alert(event, now)
        return alerted

    @staticmethod
    def _io_event_soon(raw: dict[str, object], now: datetime, window_to: datetime) -> bool:
        """True if an odds-api.io event starts within the active window (or has no time)."""
        start = raw.get("startTime") or raw.get("date")
        if not start:
            return True
        try:
            dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            return True
        return now <= dt <= window_to

    # ── loop ─────────────────────────────────────────────────────────────────
    def run_once(self, now: datetime | None = None) -> None:
        """Run a single cycle: discover if due, poll due events, refresh the report."""
        now = now or datetime.now(UTC)
        interval = timedelta(seconds=self.config.scheduler.discovery_interval_sec)
        if self._last_discovery is None or now - self._last_discovery >= interval:
            self.discover(now)
        self.poll_due(now)
        self._maybe_secondary(now)
        self._maybe_report(now)

    def _maybe_report(self, now: datetime) -> None:
        """Regenerate the HTML report on a cadence so the NAS copy stays current."""
        interval = self.config.backcast.report_interval_sec
        if interval <= 0:
            return
        if self._last_report is not None and (now - self._last_report).total_seconds() < interval:
            return
        try:
            from middler.backcast.replay import run_backcast
            from middler.backcast.report import render_report

            result = run_backcast(self.history, self.config)
            render_report(result, self.config, self.config.backcast.report_path)
            self._last_report = now
            log.info(
                "report refreshed → %s (%d opportunities)", self.config.backcast.report_path, len(result.opportunities)
            )
        except Exception as exc:  # noqa: BLE001 - a report failure must never stop recording
            log.warning("report refresh failed: %s", exc)

    def run_forever(self) -> None:
        """Run cycles until interrupted (SIGINT/SIGTERM), then shut down cleanly."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        tick = max(5, min(self.config.scheduler.poll_min_sec, 30))
        log.info("middler starting; tick=%ss, sports=%s", tick, ", ".join(self.config.sports))
        try:
            while not self._stop:
                self.run_once()
                self._write_heartbeat()
                time.sleep(tick)
        finally:
            self.close()

    def _write_heartbeat(self) -> None:
        """Touch a heartbeat file each cycle for the container healthcheck.

        The healthcheck can't open DuckDB (the running app holds the single-writer
        lock), so liveness is signalled by the freshness of this file instead.
        """
        try:
            path = Path(self.settings.duckdb_path).parent / "heartbeat"
            path.write_text(datetime.now(UTC).isoformat())
        except OSError as exc:
            log.debug("heartbeat write failed: %s", exc)

    def _handle_signal(self, *_: object) -> None:
        log.info("shutdown signal received")
        self._stop = True

    def _ping_healthcheck(self) -> None:
        url = self.settings.healthcheck_ping_url
        if not url:
            return
        try:
            httpx.get(url, timeout=10)
        except httpx.HTTPError as exc:
            log.debug("healthcheck ping failed: %s", exc)

    def close(self) -> None:
        """Close clients and stores."""
        self.client.close()
        if self.secondary is not None:
            self.secondary.close()
        self.history.close()


def main() -> None:
    """CLI entry point: run the live alert-only loop."""
    setup_logging(log_file="logs/middler.log")
    settings = load_settings()
    config = load_config()
    if not settings.the_odds_api_key:
        log.warning("THE_ODDS_API_KEY is not set — see .env.example and the README manual actions.")
    MiddlerApp(settings, config).run_forever()


if __name__ == "__main__":
    main()
