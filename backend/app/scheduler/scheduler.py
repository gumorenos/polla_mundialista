"""APScheduler configuration and lifecycle management."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        from app.core.config import settings
        _scheduler = BackgroundScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    return _scheduler


def start_scheduler() -> None:
    from apscheduler.triggers.cron import CronTrigger

    from app.core.config import settings
    from app.scheduler.jobs import (
        enqueue_daily_update,
        enqueue_full_refresh,
        enqueue_news_update,
        enqueue_nightly_update_and_simulations,
        fetch_odds_job,
        reconcile_jobs,
    )

    s = get_scheduler()
    if s.running:
        logger.debug("Scheduler already running — skipping start")
        return

    s.add_job(
        enqueue_full_refresh,
        CronTrigger.from_crontab(settings.SCHEDULER_FULL_REFRESH_CRON),
        id="full_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    s.add_job(
        enqueue_news_update,
        CronTrigger.from_crontab(settings.SCHEDULER_NEWS_CRON),
        id="news_update",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    s.add_job(
        fetch_odds_job,
        CronTrigger.from_crontab("0 */6 * * *"),
        id="fetch_odds",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Madrugada Perú (UTC-5): daily_update a las 08:30 UTC (03:30 Perú), y
    # simulaciones nocturnas a las 09:00 UTC (04:00 Perú) — 30 min después,
    # dando tiempo a que daily_update termine antes de disparar Monte Carlo.
    # enqueue_nightly_update_and_simulations verifica que el daily_update de
    # hoy haya terminado 'completed' antes de encolar nada; si no, se salta
    # con un job 'skipped' visible en Jobs UI (ver scheduler/jobs.py).
    s.add_job(
        enqueue_daily_update,
        CronTrigger.from_crontab(settings.SCHEDULER_DAILY_UPDATE_CRON),
        id="daily_update",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    s.add_job(
        enqueue_nightly_update_and_simulations,
        CronTrigger.from_crontab(settings.SCHEDULER_NIGHTLY_SIMULATIONS_CRON),
        id="nightly_update_and_simulations",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    # check_and_snapshot (pre-match simulations) intentionally removed —
    # simulations are run on-demand from the UI only.
    # FIX 3: reconcile abandoned RQ jobs every 5 minutes
    s.add_job(
        reconcile_jobs,
        "interval",
        minutes=5,
        id="reconcile_jobs",
        replace_existing=True,
        misfire_grace_time=120,
    )
    s.start()
    logger.info("Scheduler started — %d jobs registered", len(s.get_jobs()))


def stop_scheduler() -> None:
    s = get_scheduler()
    if s.running:
        s.shutdown(wait=False)
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    import time

    start_scheduler()
    logger.info("Scheduler started, entering main loop")
    while True:
        time.sleep(60)
