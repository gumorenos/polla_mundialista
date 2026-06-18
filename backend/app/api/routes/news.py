"""News & injuries endpoints — availability claims, team summaries, and job trigger."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import require_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.db.connection import db_transaction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news", tags=["news"])


# ---------------------------------------------------------------------------
# GET /api/news
# ---------------------------------------------------------------------------

@router.get("")
def list_news(
    team_id: str | None = Query(default=None),
    classification: str | None = Query(default=None, description="injured|doubtful|available|unknown"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return latest news/injury claims with optional filters.

    FIX 6: last_updated comes from MAX(jobs.finished_at) WHERE job_type='news'
    AND status='completed', falling back to MAX(availability_claims.observed_at).
    """
    with db_transaction() as conn:
        where_clauses = ["1=1"]
        params: list[Any] = []

        if team_id:
            where_clauses.append("ac.team_id = ?")
            params.append(team_id)
        if classification:
            where_clauses.append("ac.status = ?")
            params.append(classification)

        where_sql = " AND ".join(where_clauses)
        params.append(limit)

        rows = conn.execute(
            f"""
            SELECT
                ac.id,
                ac.team_id,
                t.name AS team_name,
                ac.player_name,
                ac.status,
                ac.reason,
                ac.source_url,
                ac.source_name,
                ac.confidence,
                ac.evidence_level,
                ac.affects_prediction,
                ac.observed_at,
                ac.published_at,
                ac.created_at
            FROM availability_claims ac
            LEFT JOIN teams t ON ac.team_id = t.id
            WHERE {where_sql}
            ORDER BY ac.observed_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        # FIX 6: use most recent completed news job as last_updated
        job_row = conn.execute(
            """
            SELECT MAX(finished_at) AS ts
            FROM jobs
            WHERE job_type = 'news' AND status = 'completed'
            """
        ).fetchone()
        last_updated = job_row["ts"] if job_row and job_row["ts"] else None

        # Fallback to claims timestamp if no completed job exists
        if not last_updated:
            claim_row = conn.execute(
                "SELECT MAX(observed_at) AS ts FROM availability_claims"
            ).fetchone()
            last_updated = claim_row["ts"] if claim_row else None

        total = conn.execute(
            "SELECT COUNT(*) FROM availability_claims"
        ).fetchone()[0]

    return {
        "items": [dict(r) for r in rows],
        "last_updated": last_updated,
        "total": total,
    }


# ---------------------------------------------------------------------------
# GET /api/news/summary
# ---------------------------------------------------------------------------

@router.get("/summary")
def news_summary() -> dict[str, Any]:
    """Return injury summary per team (only teams with active predictions-affecting claims)."""
    with db_transaction() as conn:
        rows = conn.execute(
            """
            SELECT
                ac.team_id,
                t.name AS team_name,
                COUNT(DISTINCT ac.player_name) AS injury_count,
                GROUP_CONCAT(DISTINCT ac.player_name) AS players_affected,
                tca.attack_factor,
                tca.defense_factor
            FROM availability_claims ac
            LEFT JOIN teams t ON ac.team_id = t.id
            LEFT JOIN (
                SELECT team_id, attack_factor, defense_factor
                FROM team_context_adjustments
                WHERE adjustment_type = 'injury'
                  AND rowid IN (
                      SELECT MAX(rowid) FROM team_context_adjustments
                      WHERE adjustment_type = 'injury'
                      GROUP BY team_id
                  )
            ) tca ON tca.team_id = ac.team_id
            WHERE ac.affects_prediction = 1
            GROUP BY ac.team_id
            ORDER BY injury_count DESC
            """
        ).fetchall()

    teams = []
    for r in rows:
        entry = dict(r)
        if entry.get("players_affected"):
            entry["players_affected"] = [
                p.strip() for p in entry["players_affected"].split(",") if p.strip()
            ]
        else:
            entry["players_affected"] = []
        teams.append(entry)

    return {"teams": teams}


# ---------------------------------------------------------------------------
# POST /api/news/trigger
# ---------------------------------------------------------------------------

@router.post("/trigger", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def trigger_news_update(request: Request) -> dict[str, Any]:
    """Enqueue a news analysis job. FIX 2: uses enqueue_job helper with lock-retry."""
    from app.core.job_helper import enqueue_job
    from app.workers.tasks import run_news_task

    result = enqueue_job(
        "default",
        run_news_task,
        job_type="news",
        timeout=settings.RQ_DEFAULT_TIMEOUT,
    )
    logger.info("News update enqueued: rq=%s db_job=%s", result["rq_job_id"], result["job_id"])
    return result
