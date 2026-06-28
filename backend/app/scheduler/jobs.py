"""Scheduled job functions — called by APScheduler in a background thread."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


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


def enqueue_daily_simulations() -> None:
    """Enqueue Monte Carlo simulations for all 5 models after the daily full_refresh.

    Called at 4:30am — 30 min after full_refresh — giving the refresh time to
    complete on ARM64. Each model is dispatched as an independent RQ job so a
    failure in one (e.g. ml_calibrated with no trained model) does not block the
    others.
    """
    from redis import Redis
    from rq import Queue

    from app.core.config import settings
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository
    from app.workers.tasks import run_simulation_task

    _MODELS = ["baseline", "elo", "poisson", "poisson_context", "ml_calibrated"]

    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        q = Queue("long", connection=redis_conn)
    except Exception:
        logger.exception("enqueue_daily_simulations: could not connect to Redis")
        return

    for model_name in _MODELS:
        try:
            with db_transaction() as conn:
                job_id = JobRepository(conn).create({
                    "job_type": "simulation",
                    "status": "enqueued",
                })
                conn.commit()

            rq_job = q.enqueue(
                run_simulation_task,
                model_name,
                settings.MONTECARLO_ITERATIONS,
                settings.MONTECARLO_SEED,
                job_id,
                job_timeout=settings.RQ_LONG_TIMEOUT,
            )
            try:
                with db_transaction() as conn:
                    JobRepository(conn).update_rq_job_id(job_id, rq_job.id)
                    conn.commit()
            except Exception:
                logger.exception(
                    "enqueue_daily_simulations: rq_job_id update failed — db_job=%s rq=%s",
                    job_id, rq_job.id,
                )
            logger.info(
                "Daily simulation enqueued — model=%s rq=%s db_job=%s",
                model_name, rq_job.id, job_id,
            )
        except Exception:
            logger.warning(
                "enqueue_daily_simulations: failed to enqueue model=%s (continuing)",
                model_name, exc_info=True,
            )


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
