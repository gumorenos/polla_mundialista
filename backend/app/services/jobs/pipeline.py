"""Orchestrated job pipelines: full refresh and daily update.

Each pipeline function:
- Accepts db_conn (SQLite) and job_id (for progress tracking)
- Returns a summary dict with per-step results and statuses
- Updates job progress at each step via JobRepository
- Wraps fault-tolerant steps in try/except; non-tolerant steps propagate errors

Fault-tolerant steps (continue on failure): ELO scraping, API Football,
  news analysis, ML training.
Mandatory steps (abort on failure): CSV ingestion, features, backtesting,
  simulations, snapshot.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable

from app.db.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)

_STEP_TIMEOUT_S = 600  # log ERROR if a step takes longer than this


class _StepTimer:
    """Context manager that logs step start/end with timing and fires a warning if a step hangs."""

    def __init__(self, name: str, step: int, total: int) -> None:
        self._name = name
        self._step = step
        self._total = total
        self._t0 = 0.0
        self._timer: threading.Timer | None = None

    def __enter__(self) -> "_StepTimer":
        self._t0 = time.monotonic()
        logger.info("[Pipeline] Paso %d/%d: %s — iniciando", self._step, self._total, self._name)
        self._timer = threading.Timer(
            _STEP_TIMEOUT_S,
            lambda: logger.error(
                "[Pipeline] Paso %d/%d: %s — sigue ejecutando después de %ds (posible cuelgue)",
                self._step, self._total, self._name, _STEP_TIMEOUT_S,
            ),
        )
        self._timer.daemon = True
        self._timer.start()
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> bool:
        if self._timer:
            self._timer.cancel()
        elapsed = time.monotonic() - self._t0
        if exc_type is None:
            logger.info(
                "[Pipeline] Paso %d/%d: %s — completado en %.1fs",
                self._step, self._total, self._name, elapsed,
            )
        else:
            logger.error(
                "[Pipeline] Paso %d/%d: %s — FALLÓ en %.1fs: %s",
                self._step, self._total, self._name, elapsed, exc_val,
            )
        return False

_BASE_MODELS = ["baseline", "elo", "poisson", "poisson_context"]
_ALL_MODELS  = _BASE_MODELS + ["ml_calibrated", "consensus"]


# ---------------------------------------------------------------------------
# Full refresh (9 steps)
# ---------------------------------------------------------------------------

def run_full_refresh(
    db_conn: sqlite3.Connection,
    job_id: str,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Full data refresh pipeline — loads and processes data only.

    Steps (with progress milestones):
      1. CSV ingestion        0.05  — mandatory
      2. ELO scraping         0.15  — fault-tolerant
      3. Own ELO recalc       0.22  — fault-tolerant
      4. API Football         0.25  — fault-tolerant
      5. Team strengths       0.35  — mandatory
      6. News analysis        0.45  — fault-tolerant
      7. Backtesting          0.60  — mandatory
      8. ML training          1.00  — fault-tolerant

    Monte Carlo simulations are intentionally excluded — run them
    manually from the UI once data is ready.
    """
    from app.core.config import settings
    from app.services.evaluation.backtesting import run_backtesting
    from app.services.features.strengths import calculate_team_strengths
    from app.services.ingestion.csv_loader import (
        load_fixtures_from_csv,
        load_groups_from_csv,
        load_historical_results_from_csv,
        load_ratings_from_csv,
        load_teams_from_csv,
        load_venues_from_csv,
    )
    from app.services.ingestion.elo_scraper import ingest_elo_ratings
    from app.services.ml.trainer import train_ml_model
    from app.services.news.availability import run_news_analysis

    job_repo = JobRepository(db_conn)
    summary: dict[str, Any] = {}
    started = datetime.now(timezone.utc).isoformat()

    def _progress(p: float) -> None:
        if cancel_check:
            cancel_check()
        job_repo.update_progress(job_id, p)
        db_conn.commit()

    # Limit backtesting to the last 2 years to avoid long scans
    backtesting_start_year = date.today().year - 2

    # ------------------------------------------------------------------
    # Step 1 — CSV ingestion (mandatory)
    # ------------------------------------------------------------------
    if cancel_check:
        cancel_check()
    with _StepTimer("CSV ingestion", 1, 8):
        teams    = load_teams_from_csv()
        groups   = load_groups_from_csv()
        fixtures = load_fixtures_from_csv()
        venues   = load_venues_from_csv()
        ratings  = load_ratings_from_csv()
        history  = load_historical_results_from_csv()
        summary["ingest_csv"] = {
            "teams": teams, "groups": groups,
            "fixtures": fixtures, "venues": venues,
            "ratings": ratings, "history": history,
        }
        if teams == 0:
            raise RuntimeError(
                "Full refresh aborted: teams.csv loaded 0 rows. "
                "Check DATA_RAW_PATH and that data/raw/teams.csv exists."
            )
    _progress(0.05)

    # ------------------------------------------------------------------
    # Step 1b — StatsBomb Open Data ingestion (fault-tolerant, optional)
    # ------------------------------------------------------------------
    from pathlib import Path as _Path
    if _Path(settings.STATSBOMB_DATA_PATH).exists():
        try:
            logger.info("[Pipeline] Paso 1b/8: Cargando datos StatsBomb")
            from app.services.ingestion.statsbomb_loader import load_all_wc_matches
            sb_count = load_all_wc_matches(db_conn, settings.STATSBOMB_DATA_PATH)
            summary["statsbomb"] = {"matches": sb_count}
            logger.info("[Pipeline] Paso 1b/8: %d partidos StatsBomb cargados", sb_count)
        except InterruptedError:
            raise
        except Exception as exc:
            logger.warning("[Pipeline] Paso 1b/8: StatsBomb falló (no fatal): %s", exc)
            summary["statsbomb"] = {"status": "failed", "error": str(exc)}
    else:
        logger.warning(
            "[Pipeline] Paso 1b/8: STATSBOMB_DATA_PATH no encontrado, saltando (%s)",
            settings.STATSBOMB_DATA_PATH,
        )
        summary["statsbomb"] = {"status": "skipped"}
    _progress(0.08)

    # ------------------------------------------------------------------
    # Step 2 — ELO scraping (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("ELO scraping", 2, 8):
            summary["elo_scrape"] = {"records": ingest_elo_ratings()}
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("ELO scraping failed (non-fatal): %s", exc)
        summary["elo_scrape"] = {"status": "failed", "error": str(exc)}
    _progress(0.15)

    # ------------------------------------------------------------------
    # Step 3 — Own ELO recalculation (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("Own ELO recalculation", 3, 8):
            from app.services.elo.calculator import recalculate_all_elos
            summary["elo_recalc"] = recalculate_all_elos(db_conn)
            db_conn.commit()
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("Own ELO recalculation failed (non-fatal): %s", exc)
        summary["elo_recalc"] = {"status": "failed", "error": str(exc)}
    _progress(0.22)

    # ------------------------------------------------------------------
    # Step 4 — API Football (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("API Football", 4, 8):
            from app.services.ingestion.api_football import ingest_api_fixtures
            summary["api_football"] = {"records": ingest_api_fixtures(conn=db_conn)}
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("API Football failed (non-fatal): %s", exc)
        summary["api_football"] = {"status": "failed", "error": str(exc)}
    _progress(0.25)

    # ------------------------------------------------------------------
    # Step 4 — Team strengths (mandatory)
    # ------------------------------------------------------------------
    with _StepTimer("Team strengths", 5, 8):
        strengths = calculate_team_strengths(db_conn)
        summary["features"] = {"n_teams": len(strengths)}
    _progress(0.35)

    # ------------------------------------------------------------------
    # Step 5 — News / injuries (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("News analysis", 6, 8):
            summary["news"] = run_news_analysis(db_conn)
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("News analysis failed (non-fatal): %s", exc)
        summary["news"] = {"status": "failed", "error": str(exc)}
    _progress(0.45)

    # ------------------------------------------------------------------
    # Step 6 — Backtesting (mandatory) — últimos 2 años, máx 500 partidos
    # ------------------------------------------------------------------
    with _StepTimer("Backtesting", 7, 8):
        summary["backtesting"] = run_backtesting(
            db_conn,
            models=_ALL_MODELS,
            start_year=backtesting_start_year,
            max_matches=500,
        )
    _progress(0.60)

    # ------------------------------------------------------------------
    # Step 7 — ML training (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("ML training", 8, 8):
            summary["ml_training"] = train_ml_model(db_conn)
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("ML training failed (non-fatal): %s", exc)
        summary["ml_training"] = {"status": "failed", "error": str(exc)}
    _progress(1.0)

    logger.info(
        "[Pipeline] Full Refresh completado. Datos listos. "
        "Lanza las simulaciones manualmente desde la UI."
    )
    logger.info("Full refresh complete: %s", {k: type(v).__name__ for k, v in summary.items()})
    return summary


# ---------------------------------------------------------------------------
# Daily update (5 steps, incremental)
# ---------------------------------------------------------------------------

def run_daily_update(
    db_conn: sqlite3.Connection,
    job_id: str,
) -> dict[str, Any]:
    """Incremental daily update pipeline — data only, no simulations.

    Steps:
      1. API Football incremental (últimos 7 días)  — fault-tolerant
      2. Suspensions / bookings / player form        — fault-tolerant
      3. Incremental ELO update                      — fault-tolerant
      4. News purge + analysis                       — fault-tolerant
      5. Recalculate team strengths                  — mandatory

    Monte Carlo simulations are intentionally excluded — run them
    manually from the UI once data is ready.
    """
    from app.services.features.strengths import calculate_team_strengths
    from app.services.news.availability import run_news_analysis

    job_repo = JobRepository(db_conn)
    summary: dict[str, Any] = {}

    def _progress(p: float) -> None:
        job_repo.update_progress(job_id, p)
        db_conn.commit()

    # Step 1 — API Football incremental
    try:
        from app.services.ingestion.api_football import ingest_api_fixtures
        summary["api_football"] = {"records": ingest_api_fixtures(days_back=7, conn=db_conn)}
    except Exception as exc:
        logger.warning("API Football incremental failed: %s", exc)
        summary["api_football"] = {"status": "failed", "error": str(exc)}
    _progress(0.15)

    # Step 1c — WC2026 bookings / suspensions (fault-tolerant)
    try:
        from app.services.ingestion.football_data_org import fetch_bookings_wc2026
        from app.services.news.availability import run_form_analysis, run_suspension_analysis
        booking_count = fetch_bookings_wc2026(db_conn)
        suspension_result = run_suspension_analysis(db_conn)
        form_result = run_form_analysis(db_conn)
        summary["suspensions"] = {
            "bookings_fetched": booking_count,
            "teams_affected": len(suspension_result.get("affected_teams", [])),
        }
        summary["player_form"] = {
            "boosted": len(form_result.get("boosted_teams", [])),
            "penalised": len(form_result.get("penalised_teams", [])),
        }
    except Exception as exc:
        logger.warning("Suspension ingestion failed (non-fatal): %s", exc)
        summary["suspensions"] = {"status": "failed", "error": str(exc)}
    _progress(0.18)

    # Step 1b — Incremental ELO update (fault-tolerant)
    try:
        from app.services.elo.calculator import update_elos_for_new_matches
        summary["elo_update"] = update_elos_for_new_matches(db_conn)
        db_conn.commit()
    except Exception as exc:
        logger.warning("Incremental ELO update failed: %s", exc)
        summary["elo_update"] = {"status": "failed", "error": str(exc)}
    _progress(0.20)

    # Step 2a — Purge stale availability_claims (> 7 days old)
    try:
        from app.db.repositories.availability import AvailabilityRepository
        deleted = AvailabilityRepository(db_conn).purge_old_claims(days=7)
        db_conn.commit()
        logger.info("[Pipeline] %d stale news claims purged (>7 days)", deleted)
        summary["news_purge"] = {"deleted": deleted}
    except Exception as exc:
        logger.warning("[Pipeline] News purge failed: %s", exc)
        summary["news_purge"] = {"status": "failed", "error": str(exc)}

    # Step 2b — News analysis
    try:
        summary["news"] = run_news_analysis(db_conn)
    except Exception as exc:
        logger.warning("News analysis failed: %s", exc)
        summary["news"] = {"status": "failed", "error": str(exc)}
    _progress(0.40)

    # Step 3 — Team strengths
    strengths = calculate_team_strengths(db_conn)
    summary["features"] = {"n_teams": len(strengths)}
    _progress(1.0)

    return summary
