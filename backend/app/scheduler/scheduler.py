"""APScheduler configuration and lifecycle management."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    from apscheduler.triggers.cron import CronTrigger

    from app.core.config import settings
    from app.scheduler.jobs import check_and_snapshot, enqueue_full_refresh, enqueue_news_update

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
        check_and_snapshot,
        "interval",
        hours=1,
        id="check_and_snapshot",
        replace_existing=True,
        misfire_grace_time=600,
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
