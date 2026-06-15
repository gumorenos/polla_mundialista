"""Background task definitions for RQ workers.

Each public function here is safe to enqueue via rq.Queue.enqueue().
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30.0  # seconds between DB heartbeat writes


class _HeartbeatUpdater:
    """Background thread that writes last_heartbeat to the jobs table every 30 s.

    Opens its own DB connection so it never contends with the main task
    connection. Safe to use as a context manager::

        with _HeartbeatUpdater(job_id):
            do_long_work()
    """

    def __init__(self, job_id: str, interval: float = _HEARTBEAT_INTERVAL) -> None:
        self._job_id = job_id
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"hb-{job_id[:8]}")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 5)

    def __enter__(self) -> "_HeartbeatUpdater":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                from app.db.connection import db_transaction
                from app.db.repositories.jobs import JobRepository

                with db_transaction() as conn:
                    JobRepository(conn).update_heartbeat(self._job_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Heartbeat update failed for job %s: %s", self._job_id, exc)


def ping_task() -> str:
    """Sanity-check task: logs execution and returns 'pong'."""
    logger.info("ping_task executed")
    return "pong"


def run_ingestion_pipeline() -> dict:
    """Full ingestion pipeline: teams → groups → fixtures → ELO → historical results.

    Runs sequentially in a single RQ worker process.
    Returns a summary dict with record counts per step.
    """
    from app.services.ingestion.csv_loader import (
        load_fixtures_from_csv,
        load_groups_from_csv,
        load_historical_results_from_csv,
        load_ratings_from_csv,
        load_teams_from_csv,
    )
    from app.services.ingestion.elo_scraper import ingest_elo_ratings

    logger.info("Starting full ingestion pipeline")

    summary: dict[str, int] = {}
    summary["teams"]   = load_teams_from_csv()
    summary["groups"]  = load_groups_from_csv()
    summary["fixtures"] = load_fixtures_from_csv()
    summary["ratings_csv"] = load_ratings_from_csv()
    summary["elo_live"]    = ingest_elo_ratings()
    summary["historical"]  = load_historical_results_from_csv()

    logger.info("Ingestion pipeline complete: %s", summary)
    return summary


def run_simulation_task(
    model_name: str,
    iterations: int,
    seed: int,
    job_id: str,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """RQ task: run Monte Carlo simulation and track progress in jobs table.

    Args:
        model_name: prediction model to use.
        iterations: number of bracket simulations.
        seed:       RNG seed.
        job_id:     jobs table record id (for progress updates).
        _conn:      optional DB connection override (used in tests only).

    Returns:
        {"simulation_run_id": str, "progress": 1.0}
    """
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.services.simulation.monte_carlo import run_monte_carlo

    def _do_run(conn: sqlite3.Connection) -> str:
        job_repo = JobRepository(conn)

        def _progress(p: float) -> None:
            job_repo.update_progress(job_id, p)
            conn.commit()

        job_repo.update_status(
            job_id, "running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()

        run_id: str | None = None
        try:
            with _HeartbeatUpdater(job_id):
                run_id = run_monte_carlo(
                    model_name=model_name,
                    conn=conn,
                    iterations=iterations,
                    seed=seed,
                    progress_callback=_progress,
                )
            job_repo.update_progress(job_id, 1.0)
            job_repo.update_status(
                job_id, "completed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                result_ref=run_id,
            )
            conn.commit()
        except Exception as exc:
            logger.exception("run_simulation_task failed for job %s: %s", job_id, exc)
            job_repo.update_status(
                job_id, "failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error_message=str(exc),
            )
            conn.commit()
            raise
        return run_id  # type: ignore[return-value]

    if _conn is not None:
        run_id = _do_run(_conn)
    else:
        with db_transaction() as conn:
            run_id = _do_run(conn)

    logger.info("Simulation task completed: run_id=%s model=%s", run_id, model_name)
    return {"simulation_run_id": run_id, "progress": 1.0}


def run_full_refresh_task(
    job_id: str,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """RQ task: run the full data refresh pipeline."""
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.services.jobs.pipeline import run_full_refresh

    def _do_run(conn: sqlite3.Connection) -> dict:
        job_repo = JobRepository(conn)
        job_repo.update_status(
            job_id, "running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()
        try:
            with _HeartbeatUpdater(job_id):
                result = run_full_refresh(conn, job_id)
            job_repo.update_status(
                job_id, "completed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            conn.commit()
            return result
        except Exception as exc:
            logger.exception("run_full_refresh_task failed for job %s: %s", job_id, exc)
            job_repo.update_status(
                job_id, "failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error_message=str(exc),
            )
            conn.commit()
            raise

    if _conn is not None:
        return _do_run(_conn)
    with db_transaction() as conn:
        return _do_run(conn)


def run_daily_update_task(
    job_id: str,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """RQ task: run the incremental daily update pipeline."""
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.services.jobs.pipeline import run_daily_update

    def _do_run(conn: sqlite3.Connection) -> dict:
        job_repo = JobRepository(conn)
        job_repo.update_status(
            job_id, "running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()
        try:
            with _HeartbeatUpdater(job_id):
                result = run_daily_update(conn, job_id)
            job_repo.update_status(
                job_id, "completed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            conn.commit()
            return result
        except Exception as exc:
            logger.exception("run_daily_update_task failed for job %s: %s", job_id, exc)
            job_repo.update_status(
                job_id, "failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error_message=str(exc),
            )
            conn.commit()
            raise

    if _conn is not None:
        return _do_run(_conn)
    with db_transaction() as conn:
        return _do_run(conn)


def run_ml_training_task(
    job_id: str,
    algorithm: str | None = None,
    train_start_year: int | None = None,
    validation_split: float | None = None,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """RQ task: train the ML calibrated model and track progress in jobs table.

    Args:
        job_id:           jobs table record id (for progress updates).
        algorithm:        'lightgbm', 'xgboost', or 'random_forest'.
        train_start_year: include historical results from this year onward.
        validation_split: fraction of data reserved for validation (temporal split).
        _conn:            optional DB connection override (used in tests only).

    Returns:
        {"training_run_id": str, "model_id": str, "metrics": dict}
    """
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.services.ml.trainer import train_ml_model

    def _do_run(conn: sqlite3.Connection) -> dict:
        job_repo = JobRepository(conn)
        job_repo.update_status(
            job_id, "running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()
        try:
            result = train_ml_model(
                conn,
                algorithm=algorithm,
                train_start_year=train_start_year,
                validation_split=validation_split,
            )
            job_repo.update_progress(job_id, 1.0)
            job_repo.update_status(
                job_id, "completed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                result_ref=result.get("model_id"),
            )
            conn.commit()
            return result
        except Exception as exc:
            logger.exception("run_ml_training_task failed for job %s: %s", job_id, exc)
            job_repo.update_status(
                job_id, "failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error_message=str(exc),
            )
            conn.commit()
            raise

    if _conn is not None:
        return _do_run(_conn)
    with db_transaction() as conn:
        return _do_run(conn)


def run_pre_match_snapshot_task(
    label: str,
    model_name: str = "poisson",
) -> dict:
    """RQ task: run simulation and save a pre-match snapshot.

    Called automatically by the scheduler 24h before each fixture.
    """
    from app.core.config import settings
    from app.db.connection import db_transaction
    from app.db.repositories.simulations import SimulationRepository
    from app.services.simulation.monte_carlo import run_monte_carlo

    with db_transaction() as conn:
        run_id = run_monte_carlo(
            model_name=model_name,
            conn=conn,
            iterations=settings.MONTECARLO_ITERATIONS,
            seed=settings.MONTECARLO_SEED,
        )
        SimulationRepository(conn).create_snapshot(
            {
                "label": label,
                "trigger": "pre_match",
                "simulation_run_id": run_id,
            }
        )
        conn.commit()

    logger.info("Pre-match snapshot task completed: label=%s run_id=%s", label, run_id)
    return {"run_id": run_id, "label": label}


def run_news_task(
    job_id: str,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """RQ task for 'news' queue: run injury detection pipeline and update job."""
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.services.news.availability import run_news_analysis

    def _do_run(conn: sqlite3.Connection) -> dict:
        job_repo = JobRepository(conn)
        job_repo.update_status(
            job_id, "running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()
        try:
            result = run_news_analysis(conn)
            job_repo.update_progress(job_id, 1.0)
            job_repo.update_status(
                job_id, "completed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            conn.commit()
            return result
        except Exception as exc:
            logger.exception("run_news_task failed for job %s: %s", job_id, exc)
            job_repo.update_status(
                job_id, "failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error_message=str(exc),
            )
            conn.commit()
            raise

    if _conn is not None:
        return _do_run(_conn)
    with db_transaction() as conn:
        return _do_run(conn)
