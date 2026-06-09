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

import signal
import time
from datetime import UTC, datetime, timedelta

import httpx

from middler.alert.telegram import Alerter
from middler.config import AppConfig, Settings, load_config, load_settings
from middler.detection.engine import detect_opportunities
from middler.ingest.normaliser import normalise_event, normalise_odds_response
from middler.ingest.odds_api import OddsApiClient
from middler.logging_setup import get_logger, setup_logging
from middler.models import Event, EventStatus
from middler.schedule.scheduler import PollScheduler
from middler.schedule.state_machine import is_pollable, next_status
from middler.store.history import HistoryStore
from middler.store.hot import HotStore

log = get_logger(__name__)

ALERT_COOLDOWN_SEC = 1800  # don't re-alert the same structural opportunity within 30 min


class MiddlerApp:
    """Wires the components into discovery + polling cycles."""

    def __init__(self, settings: Settings, config: AppConfig) -> None:
        self.settings = settings
        self.config = config
        self.client = OddsApiClient(settings.the_odds_api_key, region=config.region)
        self.history = HistoryStore(settings.duckdb_path)
        self.hot = HotStore(settings.redis_url)
        self.scheduler = PollScheduler(config.scheduler)
        self.alerter = Alerter(settings.telegram_bot_token, settings.chat_ids)
        self._sport_of: dict[str, str] = {}
        self._last_discovery: datetime | None = None
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
            try:
                raw = self.client.get_odds(
                    sport, self.config.markets, commence_from=now, commence_to=window_to, event_ids=ids
                )
            except httpx.HTTPError as exc:
                log.warning("odds poll failed for %s: %s", sport, exc)
                for event_id in ids:
                    self.scheduler.reschedule(event_id, now)
                continue
            events, quotes = normalise_odds_response(raw, observed_at=now)
            self.history.write_quotes(quotes)
            self.history.upsert_events(events)
            for event in events:
                alerted += self._detect_and_alert(event, now)
            for event_id in ids:
                self.scheduler.reschedule(event_id, now)
        self._ping_healthcheck()
        return alerted

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

    # ── loop ─────────────────────────────────────────────────────────────────
    def run_once(self, now: datetime | None = None) -> None:
        """Run a single cycle: discover if due, then poll due events."""
        now = now or datetime.now(UTC)
        interval = timedelta(seconds=self.config.scheduler.discovery_interval_sec)
        if self._last_discovery is None or now - self._last_discovery >= interval:
            self.discover(now)
        self.poll_due(now)

    def run_forever(self) -> None:
        """Run cycles until interrupted (SIGINT/SIGTERM), then shut down cleanly."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        tick = max(5, min(self.config.scheduler.poll_min_sec, 30))
        log.info("middler starting; tick=%ss, sports=%s", tick, ", ".join(self.config.sports))
        try:
            while not self._stop:
                self.run_once()
                time.sleep(tick)
        finally:
            self.close()

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
