from __future__ import annotations

import json
from typing import Any, List, Tuple, Type

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict
from pydantic_settings.main import PydanticBaseSettingsSource


class _LenientEnvSource(EnvSettingsSource):
    """pydantic-settings ≥2.7 raises SettingsError when json.loads() fails on
    List[str] fields whose env value is a comma-separated string (not JSON).
    This subclass returns the raw string on decode failure so that the
    field_validator can handle it."""

    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except Exception:
            return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        **kwargs: Any,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _LenientEnvSource(settings_cls),
            dotenv_settings,
        )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    SQLITE_PATH: str = "data/sqlite/oraculo.db"
    DATA_RAW_PATH: str = "data/raw"
    DATA_EXPORTS_PATH: str = "data/exports"
    STATSBOMB_DATA_PATH: str = "/home/ubuntu/proyectos/statsbomb-data/data"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    LOG_FILE: str = "data/oraculo.log"
    LOG_LEVEL: str = "INFO"

    # ------------------------------------------------------------------
    # Redis / RQ
    # ------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    RQ_DEFAULT_TIMEOUT: int = 3600
    RQ_LONG_TIMEOUT: int = 7200

    # ------------------------------------------------------------------
    # API Football
    # ------------------------------------------------------------------
    API_FOOTBALL_KEY: str = ""
    API_FOOTBALL_BASE_URL: str = "https://v3.football.api-sports.io/"
    API_FOOTBALL_HOST: str = "v3.football.api-sports.io"
    API_FOOTBALL_RAPIDAPI: bool = False

    # ------------------------------------------------------------------
    # football-data.org (backup de API Football)
    # ------------------------------------------------------------------
    FOOTBALL_DATA_API_KEY: str = ""

    # ------------------------------------------------------------------
    # OpenRouter / LLM
    # ------------------------------------------------------------------
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_MODEL: str = "deepseek/deepseek-v4-flash"
    OPENROUTER_SITE_URL: str = ""
    OPENROUTER_APP_NAME: str = "OraculoMundial2026"
    OPENROUTER_FALLBACK_MODELS: List[str] = Field(
        default=[
            "meta-llama/llama-3.1-8b-instruct",
            "google/gemma-4-31b-it:free",
        ]
    )

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    ADMIN_TOKEN: str = ""
    ADMIN_PASSWORD: str = Field(default="", description="Contraseña amigable para login web (distinta del token API)")
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"]
    )

    # ------------------------------------------------------------------
    # Statistical models
    # ------------------------------------------------------------------
    TIME_DECAY_FACTOR: float = 0.001
    POISSON_MAX_GOALS: int = 8
    DIXON_COLES_RHO: float = 0.15
    LOCAL_ADVANTAGE_NEUTRAL: float = 1.0
    LOCAL_ADVANTAGE_HOME: float = 1.1

    # ------------------------------------------------------------------
    # Injuries / News
    # ------------------------------------------------------------------
    INJURY_ATTACK_PENALTY: float = 0.15
    INJURY_DEFENSE_PENALTY: float = 0.05

    # ------------------------------------------------------------------
    # Suspensions
    # ------------------------------------------------------------------
    SUSPENSION_ATTACK_PENALTY: float = 0.12
    SUSPENSION_DEFENSE_PENALTY: float = 0.08
    NEWS_MIN_SOURCES: int = 2
    NEWS_CONFIDENCE_THRESHOLD: float = 0.7
    NEWS_MAX_PER_PLAYER: int = 5
    NEWS_DAYS_LOOKBACK: int = 7

    # ------------------------------------------------------------------
    # Monte Carlo
    # ------------------------------------------------------------------
    MONTECARLO_ITERATIONS: int = 30_000
    MONTECARLO_SEED: int = 42
    SIMULATION_BATCH_SIZE: int = 1_000

    # ------------------------------------------------------------------
    # Machine Learning
    # ------------------------------------------------------------------
    ML_TRAIN_START_YEAR: int = 2010
    ML_VALIDATION_SPLIT: float = 0.2
    ML_PREFERRED_ALGORITHM: str = "lightgbm"
    ML_MODELS_PATH: str = "data/models"
    ML_MODELS_KEEP: int = 5

    # ------------------------------------------------------------------
    # Rate limiting (slowapi)
    # ------------------------------------------------------------------
    RATE_LIMIT_PUBLIC: str = "60/minute"
    RATE_LIMIT_ADMIN: str = "10/minute"

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    SCHEDULER_ENABLED: bool = False  # must be enabled explicitly; only in the scheduler service
    SCHEDULER_FULL_REFRESH_CRON: str = "0 3 * * *"
    SCHEDULER_NEWS_CRON: str = "0 */6 * * *"

    # ------------------------------------------------------------------
    # External URLs
    # ------------------------------------------------------------------
    ELO_URL: str = "http://www.eloratings.net/"
    FUENTES_CONFIABLES: List[str] = Field(
        default=["espn.com", "marca.com", "theathletic.com", "bbc.com", "goal.com"]
    )

    # ------------------------------------------------------------------
    # The Odds API — https://the-odds-api.com (plan gratuito: 500 req/mes)
    # ------------------------------------------------------------------
    ODDS_API_KEY: str = ""
    ODDS_API_SPORT: str = "soccer_fifa_world_cup"
    ODDS_API_BASE_URL: str = "https://api.the-odds-api.com/v4"

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        _unsafe = {"", "change_me_in_production"}
        if self.ENVIRONMENT == "production":
            if self.ADMIN_TOKEN in _unsafe:
                raise ValueError(
                    "ADMIN_TOKEN must be set to a non-placeholder value in production. "
                    "Set ENVIRONMENT=development to bypass this check."
                )
            # ADMIN_PASSWORD is only needed by the API process (login endpoint).
            # Scheduler/worker run with SCHEDULER_ENABLED=true and don't serve auth.
            if not self.SCHEDULER_ENABLED and self.ADMIN_PASSWORD in _unsafe:
                raise ValueError(
                    "ADMIN_PASSWORD must be set in production. "
                    "Use a memorable passphrase (min 8 chars)."
                )
        return self

    @field_validator(
        "CORS_ORIGINS",
        "FUENTES_CONFIABLES",
        "OPENROUTER_FALLBACK_MODELS",
        mode="before",
    )
    @classmethod
    def parse_list_field(cls, v: Any) -> Any:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return v


settings = Settings()
