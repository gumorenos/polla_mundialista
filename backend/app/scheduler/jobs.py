"""Scheduled job functions — called by APScheduler in a background thread."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("enqueued", "started", "running")


def _job_exists_today(conn: sqlite3.Connection, job_type: str, statuses: tuple[str, ...] | None = None) -> bool:
    """True if a job of *job_type* already exists today (UTC), optionally
    restricted to *statuses*. Used to avoid double-dispatching the same
    scheduled work (e.g. a misfire retry firing twice)."""
    query = "SELECT 1 FROM jobs WHERE job_type = ? AND date(created_at) = date('now')"
    params: list = [job_type]
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        query += f" AND status IN ({placeholders})"
        params.extend(statuses)
    return conn.execute(query, params).fetchone() is not None


def enqueue_full_refresh() -> None:
    """Create a DB job record and enqueue full-refresh in the 'long' RQ queue."""
    from redis import Redis
    from rq import Queue

    from app.core.config import settings
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.workers.tasks import run_full_refresh_task

    try:
        with db_transaction() as conn:
            job_id = JobRepository(conn).create({"job_type": "full_refresh", "status": "enqueued"})
            conn.commit()

        redis_conn = Redis.from_url(settings.REDIS_URL)
        q = Queue("long", connection=redis_conn)
        rq_job = q.enqueue(run_full_refresh_task, job_id, job_timeout=settings.RQ_LONG_TIMEOUT)
        try:
            with db_transaction() as conn:
                JobRepository(conn).update_rq_job_id(job_id, rq_job.id)
                conn.commit()
        except Exception:
            logger.exception("Scheduled full_refresh enqueued in RQ but rq_job_id update failed: db_job=%s rq=%s", job_id, rq_job.id)
        logger.info("Scheduled full_refresh enqueued — rq=%s db_job=%s", rq_job.id, job_id)
    except Exception:
        logger.exception("enqueue_full_refresh failed")


def enqueue_news_update() -> None:
    """Create a DB job record and enqueue news analysis in the 'news' RQ queue."""
    from redis import Redis
    from rq import Queue

    from app.core.config import settings
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.workers.tasks import run_news_task

    try:
        with db_transaction() as conn:
            job_id = JobRepository(conn).create({"job_type": "news", "status": "enqueued"})
            conn.commit()

        redis_conn = Redis.from_url(settings.REDIS_URL)
        q = Queue("news", connection=redis_conn)
        rq_job = q.enqueue(run_news_task, job_id, job_timeout=settings.RQ_DEFAULT_TIMEOUT)
        try:
            with db_transaction() as conn:
                JobRepository(conn).update_rq_job_id(job_id, rq_job.id)
                conn.commit()
        except Exception:
            logger.exception("Scheduled news_update enqueued in RQ but rq_job_id update failed: db_job=%s rq=%s", job_id, rq_job.id)
        logger.info("Scheduled news_update enqueued — rq=%s db_job=%s", rq_job.id, job_id)
    except Exception:
        logger.exception("enqueue_news_update failed")


def enqueue_daily_update() -> None:
    """Create a DB job record and enqueue daily_update in the 'default' RQ queue.

    Scheduled at SCHEDULER_DAILY_UPDATE_CRON (default 08:30 UTC = 03:30 Perú),
    30 min before nightly simulations so data is ready first.
    """
    from app.core.config import settings
    from app.core.job_helper import enqueue_job
    from app.db.connection import db_transaction
    from app.workers.tasks import run_daily_update_task

    try:
        with db_transaction() as conn:
            if _job_exists_today(conn, "daily_update", _ACTIVE_STATUSES):
                logger.info("enqueue_daily_update: ya hay un daily_update activo hoy — omitiendo")
                return

        result = enqueue_job(
            "default", run_daily_update_task,
            job_type="daily_update", timeout=settings.RQ_DEFAULT_TIMEOUT,
        )
        logger.info("Scheduled daily_update enqueued — rq=%s db_job=%s", result["rq_job_id"], result["job_id"])
    except Exception:
        logger.exception("enqueue_daily_update failed")


def enqueue_nightly_update_and_simulations() -> None:
    """Dispatch nightly simulations after verifying today's daily_update completed.

    Scheduled at SCHEDULER_NIGHTLY_SIMULATIONS_CRON (default 09:00 UTC = 04:00
    Perú), 30 min after enqueue_daily_update. Does NOT wait inside the
    scheduler thread for daily_update to finish — instead it checks the jobs
    table for a 'daily_update' row completed today. If none is found, this
    dispatch is skipped (not failed) with a clear reason, and simulations are
    left for the next manual run or the following night.

    Dispatch order (all via the 'long' RQ queue, single worker in
    docker-compose.prod.yml — FIFO on that queue means bracket sims, then
    per-model full Monte Carlo, then consensus run strictly in that order,
    so consensus always aggregates freshly-completed results, not stale ones):
      1. bracket simulations per NIGHTLY_BRACKET_MODELS (if NIGHTLY_RUN_BRACKET)
      2. full Monte Carlo per NIGHTLY_SIMULATION_MODELS (if NIGHTLY_RUN_FULL_MONTE_CARLO),
         excluding 'consensus' — dispatched first
      3. 'consensus' full Monte Carlo (aggregation-only, near-instant) — dispatched last

    A model failing (e.g. ml_calibrated with no trained model) only fails
    that one RQ job — it does not block or cancel the rest of the run.
    """
    from app.core.config import settings
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository

    with db_transaction() as conn:
        if _job_exists_today(conn, "nightly_update_and_simulations"):
            logger.info(
                "enqueue_nightly_update_and_simulations: ya se despachó hoy — omitiendo "
                "(evita duplicados por reintentos de misfire)"
            )
            return

        daily_update_ok = conn.execute(
            "SELECT 1 FROM jobs WHERE job_type = 'daily_update' "
            "AND status = 'completed' AND date(created_at) = date('now')"
        ).fetchone() is not None

        job_repo = JobRepository(conn)

        if not daily_update_ok:
            message = (
                "daily_update de hoy no está 'completed' (falló, sigue corriendo, o nunca "
                "se encoló) — simulaciones nocturnas omitidas para no correr sobre datos "
                "potencialmente inconsistentes."
            )
            skipped_job_id = job_repo.create({
                "job_type": "nightly_update_and_simulations",
                "status": "enqueued",
            })
            job_repo.update_status(
                skipped_job_id, "skipped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error_message=message,
            )
            conn.commit()
            logger.warning("enqueue_nightly_update_and_simulations: %s", message)
            return

        nightly_job_id = job_repo.create({
            "job_type": "nightly_update_and_simulations",
            "status": "enqueued",
        })
        job_repo.update_status(
            nightly_job_id, "running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()

    dispatched: list[str] = []
    skipped: list[str] = []

    if settings.NIGHTLY_RUN_BRACKET:
        for model_name in settings.NIGHTLY_BRACKET_MODELS:
            job_type = f"simulation_bracket_{model_name}"
            if _dispatch_if_not_active(job_type, _enqueue_bracket_job, model_name):
                dispatched.append(job_type)
            else:
                skipped.append(job_type)

    if settings.NIGHTLY_RUN_FULL_MONTE_CARLO:
        base_models = [m for m in settings.NIGHTLY_SIMULATION_MODELS if m != "consensus"]
        for model_name in base_models:
            job_type = f"simulation_full_{model_name}"
            if _dispatch_if_not_active(job_type, _enqueue_full_simulation_job, model_name):
                dispatched.append(job_type)
            else:
                skipped.append(job_type)

        if "consensus" in settings.NIGHTLY_SIMULATION_MODELS:
            job_type = "simulation_full_consensus"
            if _dispatch_if_not_active(job_type, _enqueue_full_simulation_job, "consensus"):
                dispatched.append(job_type)
            else:
                skipped.append(job_type)

    with db_transaction() as conn:
        JobRepository(conn).update_status(
            nightly_job_id, "completed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error_message=(
                f"dispatched={dispatched} skipped_duplicates={skipped}" if skipped else None
            ),
        )
        conn.commit()

    logger.info(
        "enqueue_nightly_update_and_simulations: dispatched=%s skipped=%s",
        dispatched, skipped,
    )


def _dispatch_if_not_active(job_type: str, enqueue_fn, model_name: str) -> bool:
    """Enqueue *model_name* via *enqueue_fn* unless a job of *job_type* is
    already active today. Returns True if dispatched, False if skipped."""
    from app.db.connection import db_transaction

    with db_transaction() as conn:
        if _job_exists_today(conn, job_type, _ACTIVE_STATUSES):
            logger.info("nightly dispatch: %s ya activo hoy — omitiendo duplicado", job_type)
            return False
    try:
        enqueue_fn(model_name)
        return True
    except Exception:
        logger.exception("nightly dispatch: fallo al encolar %s (continuando)", job_type)
        return False


def _enqueue_full_simulation_job(model_name: str) -> None:
    from redis import Redis
    from rq import Queue

    from app.core.config import settings
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.workers.tasks import run_simulation_task

    with db_transaction() as conn:
        job_id = JobRepository(conn).create({
            "job_type": f"simulation_full_{model_name}",
            "status": "enqueued",
        })
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("long", connection=redis_conn)
    rq_job = q.enqueue(
        run_simulation_task, model_name, settings.MONTECARLO_ITERATIONS,
        settings.MONTECARLO_SEED, job_id, job_timeout=settings.RQ_LONG_TIMEOUT,
    )
    with db_transaction() as conn:
        JobRepository(conn).update_rq_job_id(job_id, rq_job.id)
        conn.commit()
    logger.info("Nightly full simulation enqueued — model=%s rq=%s db_job=%s", model_name, rq_job.id, job_id)


def _enqueue_bracket_job(model_name: str) -> None:
    from redis import Redis
    from rq import Queue

    from app.core.config import settings
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.workers.tasks import run_bracket_simulation_task

    with db_transaction() as conn:
        job_id = JobRepository(conn).create({
            "job_type": f"simulation_bracket_{model_name}",
            "status": "enqueued",
        })
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("long", connection=redis_conn)
    rq_job = q.enqueue(
        run_bracket_simulation_task, job_id, model_name, "scheduled",
        job_timeout=settings.RQ_LONG_TIMEOUT,
    )
    with db_transaction() as conn:
        JobRepository(conn).update_rq_job_id(job_id, rq_job.id)
        conn.commit()
    logger.info("Nightly bracket simulation enqueued — model=%s rq=%s db_job=%s", model_name, rq_job.id, job_id)


def check_and_snapshot() -> None:
    """Hourly: look for fixtures within 25h and create pre-match snapshots if missing."""
    from app.db.connection import db_transaction

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=25)
    today = now.strftime("%Y-%m-%d")

    try:
        with db_transaction() as conn:
            fixtures = conn.execute(
                """
                SELECT f.id, f.match_date, f.home_team_id, f.away_team_id,
                       ht.name AS home_name, at_.name AS away_name
                FROM fixtures f
                LEFT JOIN teams ht  ON f.home_team_id = ht.id
                LEFT JOIN teams at_ ON f.away_team_id = at_.id
                WHERE f.match_date >= ?
                  AND f.match_date <= ?
                  AND f.home_team_id IS NOT NULL
                  AND f.away_team_id IS NOT NULL
                """,
                (
                    now.strftime("%Y-%m-%dT%H:%M:%S"),
                    window_end.strftime("%Y-%m-%dT%H:%M:%S"),
                ),
            ).fetchall()

        if not fixtures:
            logger.debug("check_and_snapshot: no upcoming fixtures in 25h window")
            return

        for fixture in fixtures:
            home = fixture["home_name"] or fixture["home_team_id"]
            away = fixture["away_name"] or fixture["away_team_id"]
            date_str = (fixture["match_date"] or "")[:10]
            label = f"Pre-match: {home} vs {away} ({date_str})"

            with db_transaction() as conn:
                existing = conn.execute(
                    """
                    SELECT id FROM snapshots
                    WHERE trigger = 'pre_match'
                      AND label = ?
                      AND created_at >= ?
                    """,
                    (label, f"{today}T00:00:00"),
                ).fetchone()

            if existing:
                logger.debug("Pre-match snapshot already exists for: %s", label)
                continue

            _enqueue_pre_match_snapshot(label)
            logger.info("Pre-match snapshot enqueued: %s", label)

    except Exception:
        logger.exception("check_and_snapshot failed")


def fetch_odds_job() -> None:
    """Fetch market odds from The Odds API (runs directly, no RQ queue)."""
    from app.services.ingestion.odds_api import fetch_and_store_odds

    try:
        result = fetch_and_store_odds()
        if not result.get("skipped"):
            logger.info("fetch_odds_job: %s", result)
    except Exception:
        logger.exception("fetch_odds_job failed")


def reconcile_jobs() -> None:
    """Reconcile abandoned RQ jobs with DB records. Called every 5 min by scheduler."""
    from app.jobs.reconciler import reconcile_rq_jobs

    try:
        result = reconcile_rq_jobs()
        if result["updated"] > 0:
            logger.info("reconcile_jobs (scheduled): %s", result)
    except Exception:
        logger.exception("reconcile_jobs failed")


def _enqueue_pre_match_snapshot(label: str) -> None:
    """Enqueue a pre-match simulation+snapshot task."""
    from redis import Redis
    from rq import Queue

    from app.core.config import settings
    from app.workers.tasks import run_pre_match_snapshot_task

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("long", connection=redis_conn)
    q.enqueue(run_pre_match_snapshot_task, label, job_timeout=settings.RQ_LONG_TIMEOUT)
