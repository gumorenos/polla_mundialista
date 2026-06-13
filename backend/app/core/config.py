from __future__ import annotations

import json
from typing import Any, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    SQLITE_PATH: str = "data/sqlite/oraculo.db"
    DATA_RAW_PATH: str = "data/raw"
    DATA_EXPORTS_PATH: str = "data/exports"

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
            "meta-llama/llama-3.1-8b-instruct:free",
            "mistralai/mistral-7b-instruct:free",
        ]
    )

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    ADMIN_TOKEN: str = ""
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

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    SCHEDULER_ENABLED: bool = True
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
    # Environment
    # ------------------------------------------------------------------
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # ------------------------------------------------------------------
    # Validators: accept JSON array or comma-separated string from env
    # ------------------------------------------------------------------
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
