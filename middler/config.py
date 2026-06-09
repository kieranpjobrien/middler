"""Configuration: secrets from ``.env`` and operating config from ``config.yaml``.

Two distinct concerns, kept separate:

* :class:`Settings` — secrets and per-host values (API keys, tokens, paths). Read
  from the environment / ``.env``. Never committed.
* :class:`AppConfig` — non-secret operating parameters (sports, markets,
  thresholds, cadence). Read from ``config.yaml``. Safe to commit and review.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and per-host configuration, sourced from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Data feeds
    the_odds_api_key: str = ""
    odds_api_io_key: str = ""
    oddspapi_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""

    # Stores
    redis_url: str = "redis://localhost:6379/0"
    duckdb_path: str = "data/odds.duckdb"

    # Ops
    healthcheck_ping_url: str = ""

    # Placement (money-touching — disabled while blank)
    betfair_app_key: str = ""
    betfair_username: str = ""
    betfair_password: str = ""
    betfair_cert_file: str = ""
    betfair_key_file: str = ""
    placement_enabled: bool = False

    @property
    def chat_ids(self) -> list[int]:
        """Parse the comma-separated chat-id list into integers."""
        return [int(c.strip()) for c in self.telegram_chat_ids.split(",") if c.strip()]


# ── config.yaml schema ───────────────────────────────────────────────────────
class DetectionConfig(BaseModel):
    min_arb_margin: float = 0.005
    min_middle_width: float = 0.5
    min_middle_ev: float = 0.0
    stake_mode: str = "balanced"  # "balanced" | "equal" | "kelly"
    kelly_fraction: float = 0.25
    sharp_tolerance: float = 0.06
    # Back-and-lay (exchange) strategy: Betfair commission on net winnings, and the
    # minimum locked-in ROI to flag a back-lay position. Used once Betfair exchange
    # lay prices are available (see middler/detection/maths.evaluate_back_lay).
    betfair_commission: float = 0.05
    min_back_lay_roi: float = 0.0


class SchedulerConfig(BaseModel):
    active_window_hours: int = 72
    discovery_interval_sec: int = 3600
    poll_min_sec: int = 60
    poll_max_sec: int = 3600
    stop_before_commence_sec: int = 0


class StakingConfig(BaseModel):
    default_total_stake: float = 100.0
    two_step_confirm_above: float = 200.0
    bankroll: float = 1000.0  # used only when detection.stake_mode == "kelly"


class BackcastConfig(BaseModel):
    middle_hit_rate_prior: dict[str, float] = Field(default_factory=lambda: {"totals": 0.06, "spreads": 0.05})
    report_path: str = "reports/backcast.html"
    # How often the live app regenerates the HTML report (seconds). 0 disables.
    report_interval_sec: int = 3600


class AppConfig(BaseModel):
    """Top-level operating configuration loaded from ``config.yaml``."""

    region: str = "au"
    sports: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=lambda: ["h2h", "totals", "spreads"])
    sharp_books: list[str] = Field(default_factory=lambda: ["pinnacle", "betfair_ex_au"])
    bookmakers: list[str] = Field(default_factory=list)
    # Maps a The-Odds-API sport key → the odds-api.io slug for the same sport.
    # The secondary feed enriches detection only for sports listed here.
    odds_api_io_sport_map: dict[str, str] = Field(default_factory=dict)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    staking: StakingConfig = Field(default_factory=StakingConfig)
    backcast: BackcastConfig = Field(default_factory=BackcastConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Load and validate ``config.yaml`` into an :class:`AppConfig`.

    Args:
        path: Path to the YAML file. Falls back to all defaults if it is absent.

    Returns:
        A validated :class:`AppConfig`.
    """
    p = Path(path)
    if not p.exists():
        return AppConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)


def load_settings() -> Settings:
    """Load secrets/host config from the environment and ``.env``."""
    return Settings()
