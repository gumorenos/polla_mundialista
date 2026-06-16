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
_ALL_MODELS  = _BASE_MODELS + ["ml_calibrated"]


# ---------------------------------------------------------------------------
# Full refresh (9 steps)
# ---------------------------------------------------------------------------

def run_full_refresh(
    db_conn: sqlite3.Connection,
    job_id: str,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Full data refresh pipeline.

    Steps (with progress milestones):
      1. CSV ingestion        0.05  — mandatory
      2. ELO scraping         0.15  — fault-tolerant
      3. API Football         0.25  — fault-tolerant
      4. Team strengths       0.35  — mandatory
      5. News analysis        0.45  — fault-tolerant
      6. Backtesting          0.60  — mandatory
      7. ML training          0.75  — fault-tolerant
      8. Monte Carlo sims     0.95  — mandatory
      9. Snapshot             1.00  — mandatory
    """
    from app.core.config import settings
    from app.db.repositories.simulations import SimulationRepository
    from app.services.evaluation.backtesting import run_backtesting
    from app.services.features.strengths import calculate_team_strengths
    from app.services.ingestion.csv_loader import (
        load_fixtures_from_csv,
        load_groups_from_csv,
        load_historical_results_from_csv,
        load_ratings_from_csv,
        load_teams_from_csv,
    )
    from app.services.ingestion.elo_scraper import ingest_elo_ratings
    from app.services.ml.trainer import train_ml_model
    from app.services.news.availability import run_news_analysis
    from app.services.simulation.monte_carlo import run_monte_carlo

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
    with _StepTimer("CSV ingestion", 1, 9):
        teams    = load_teams_from_csv()
        groups   = load_groups_from_csv()
        fixtures = load_fixtures_from_csv()
        ratings  = load_ratings_from_csv()
        history  = load_historical_results_from_csv()
        summary["ingest_csv"] = {
            "teams": teams, "groups": groups,
            "fixtures": fixtures, "ratings": ratings, "history": history,
        }
        if teams == 0:
            raise RuntimeError(
                "Full refresh aborted: teams.csv loaded 0 rows. "
                "Check DATA_RAW_PATH and that data/raw/teams.csv exists."
            )
    _progress(0.05)

    # ------------------------------------------------------------------
    # Step 2 — ELO scraping (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("ELO scraping", 2, 9):
            summary["elo_scrape"] = {"records": ingest_elo_ratings()}
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("ELO scraping failed (non-fatal): %s", exc)
        summary["elo_scrape"] = {"status": "failed", "error": str(exc)}
    _progress(0.15)

    # ------------------------------------------------------------------
    # Step 3 — API Football (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("API Football", 3, 9):
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
    with _StepTimer("Team strengths", 4, 9):
        strengths = calculate_team_strengths(db_conn)
        summary["features"] = {"n_teams": len(strengths)}
    _progress(0.35)

    # ------------------------------------------------------------------
    # Step 5 — News / injuries (fault-tolerant)
    # ------------------------------------------------------------------
    try:
        with _StepTimer("News analysis", 5, 9):
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
    with _StepTimer("Backtesting", 6, 9):
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
        with _StepTimer("ML training", 7, 9):
            summary["ml_training"] = train_ml_model(db_conn)
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("ML training failed (non-fatal): %s", exc)
        summary["ml_training"] = {"status": "failed", "error": str(exc)}
    _progress(0.75)

    # ------------------------------------------------------------------
    # Step 8 — Monte Carlo for all models (mandatory)
    # ------------------------------------------------------------------
    sim_run_ids: dict[str, str] = {}
    with _StepTimer("Monte Carlo simulations", 8, 9):
        for model_name in _ALL_MODELS:
            try:
                run_id = run_monte_carlo(
                    model_name=model_name,
                    conn=db_conn,
                    iterations=settings.MONTECARLO_ITERATIONS,
                    seed=settings.MONTECARLO_SEED,
                )
                sim_run_ids[model_name] = run_id
            except Exception as exc:
                logger.warning("Simulation for %s failed: %s", model_name, exc)
                sim_run_ids[model_name] = f"failed:{exc}"
    summary["simulations"] = sim_run_ids
    _progress(0.95)

    # ------------------------------------------------------------------
    # Step 9 — Snapshot (mandatory)
    # ------------------------------------------------------------------
    with _StepTimer("Snapshot", 9, 9):
        best_run_id = next(
            (rid for rid in sim_run_ids.values() if not rid.startswith("failed:")),
            None,
        )
        snap_id = SimulationRepository(db_conn).create_snapshot({
            "label":             f"full-refresh-{started[:10]}",
            "description":       "Auto-snapshot after full refresh",
            "trigger":           "full_refresh",
            "simulation_run_id": best_run_id,
        })
        db_conn.commit()
        summary["snapshot"] = {"id": snap_id}
    _progress(1.0)

    logger.info("Full refresh complete: %s", {k: type(v).__name__ for k, v in summary.items()})
    return summary


# ---------------------------------------------------------------------------
# Daily update (5 steps, incremental)
# ---------------------------------------------------------------------------

def run_daily_update(
    db_conn: sqlite3.Connection,
    job_id: str,
) -> dict[str, Any]:
    """Incremental daily update pipeline.

    Steps:
      1. API Football incremental (últimos 7 días)  — fault-tolerant
      2. News analysis                               — fault-tolerant
      3. Recalculate team strengths                  — mandatory
      4. Monte Carlo for base models                 — mandatory
      5. ML simulation if active model exists        — fault-tolerant
    """
    from app.core.config import settings
    from app.db.repositories.ml import MLRepository
    from app.services.features.strengths import calculate_team_strengths
    from app.services.news.availability import run_news_analysis
    from app.services.simulation.monte_carlo import run_monte_carlo

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
    _progress(0.20)

    # Step 2 — News analysis
    try:
        summary["news"] = run_news_analysis(db_conn)
    except Exception as exc:
        logger.warning("News analysis failed: %s", exc)
        summary["news"] = {"status": "failed", "error": str(exc)}
    _progress(0.40)

    # Step 3 — Team strengths
    strengths = calculate_team_strengths(db_conn)
    summary["features"] = {"n_teams": len(strengths)}
    _progress(0.55)

    # Step 4 — Simulations for base models
    sim_run_ids: dict[str, str] = {}
    for model_name in _BASE_MODELS:
        try:
            run_id = run_monte_carlo(
                model_name=model_name,
                conn=db_conn,
                iterations=settings.MONTECARLO_ITERATIONS,
                seed=settings.MONTECARLO_SEED,
            )
            sim_run_ids[model_name] = run_id
        except Exception as exc:
            logger.warning("Simulation for %s failed: %s", model_name, exc)
            sim_run_ids[model_name] = f"failed:{exc}"
    summary["simulations"] = sim_run_ids
    _progress(0.90)

    # Step 5 — ML calibrated simulation (if active model exists)
    try:
        if MLRepository(db_conn).get_best_model() is not None:
            run_id = run_monte_carlo(
                model_name="ml_calibrated",
                conn=db_conn,
                iterations=settings.MONTECARLO_ITERATIONS,
                seed=settings.MONTECARLO_SEED,
            )
            sim_run_ids["ml_calibrated"] = run_id
    except Exception as exc:
        logger.warning("ML calibrated simulation failed: %s", exc)
        sim_run_ids["ml_calibrated"] = f"failed:{exc}"
    _progress(1.0)

    return summary
