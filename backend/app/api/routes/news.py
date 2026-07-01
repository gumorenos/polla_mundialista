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
    alive_only: bool = Query(default=True, description="Exclude teams already eliminated from the tournament"),
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

        alive_warning = None
        if alive_only:
            from app.services.features.alive_teams import get_alive_team_ids
            alive_ids, alive_warning = get_alive_team_ids(conn)
            if alive_ids:
                placeholders = ",".join("?" for _ in alive_ids)
                where_clauses.append(f"(ac.team_id IS NULL OR ac.team_id IN ({placeholders}))")
                params.extend(alive_ids)

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
        "alive_only": alive_only,
        "alive_warning": alive_warning,
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
                tca.defense_factor,
                latest.source_url,
                latest.source_name,
                latest.published_at
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
            LEFT JOIN (
                SELECT team_id, source_url, source_name, published_at
                FROM availability_claims
                WHERE affects_prediction = 1
                  AND rowid IN (
                      SELECT MAX(rowid) FROM availability_claims
                      WHERE affects_prediction = 1
                      GROUP BY team_id
                  )
            ) latest ON latest.team_id = ac.team_id
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
        if not entry.get("source_url"):
            entry["source_note"] = "Sin fuente enlazada en availability_claims"
        teams.append(entry)

    return {"teams": teams}


# ---------------------------------------------------------------------------
# GET /api/news/suspensions
# ---------------------------------------------------------------------------

@router.get("/suspensions")
def list_suspensions() -> dict[str, Any]:
    """Return per-team suspension summary for WC2026.

    Reads player_bookings and applies FIFA rules (2 yellows or red card = ban).
    Returns teams that have at least one suspended player.
    """
    from app.services.suspensions.detector import get_suspended_players

    with db_transaction() as conn:
        try:
            team_rows = conn.execute(
                "SELECT t.id, t.name FROM teams t"
            ).fetchall()
        except Exception as exc:
            logger.warning("suspensions: cannot read teams: %s", exc)
            return {"teams": []}

        teams_out = []
        for t in team_rows:
            team_id = t["id"]
            suspended = get_suspended_players(team_id, conn)
            if not suspended:
                continue

            n = len(suspended)
            from app.core.config import settings as _s
            attack_factor = round((1.0 - _s.SUSPENSION_ATTACK_PENALTY) ** n, 4)
            defense_factor = round((1.0 + _s.SUSPENSION_DEFENSE_PENALTY) ** n, 4)

            teams_out.append(
                {
                    "team_id": team_id,
                    "team_name": t["name"],
                    "suspended_count": n,
                    "players_suspended": [p["player_name"] for p in suspended],
                    "details": suspended,
                    "attack_factor": attack_factor,
                    "defense_factor": defense_factor,
                }
            )

    return {"teams": teams_out}


# ---------------------------------------------------------------------------
# GET /api/news/player-form
# ---------------------------------------------------------------------------

@router.get("/player-form")
def get_player_form_summary(
    alive_only: bool = Query(default=True, description="Exclude teams already eliminated from the tournament"),
) -> dict[str, Any]:
    """Return key-player form data for all teams that have StatsBomb stats.

    For each team, finds the player with the most historical xG and returns
    their recent-form metrics derived from the last 5 StatsBomb matches.
    Only teams with StatsBomb data are included in the response.
    """
    from app.services.features.alive_teams import get_alive_team_ids
    from app.services.features.player_form import _top_xg_player, get_player_form
    from app.services.features.squad_pool import get_key_player_pool

    with db_transaction() as conn:
        try:
            team_rows = conn.execute(
                """
                SELECT DISTINCT sps.team_id, t.name AS team_name
                FROM sb_player_stats sps
                JOIN teams t ON t.id = sps.team_id
                """
            ).fetchall()
        except Exception as exc:
            logger.warning("player-form: cannot read team list: %s", exc)
            return {"teams": []}

        alive_ids: set[str] = set()
        alive_warning = None
        if alive_only:
            alive_ids, alive_warning = get_alive_team_ids(conn)

        teams_out = []
        for t in team_rows:
            team_id = t["team_id"]

            if alive_only and alive_ids and team_id not in alive_ids:
                continue

            # Key player = highest cumulative xG restricted to the real
            # WC2026 squad when known (see get_key_player_pool) — a player
            # who topped historical xG but isn't in the final squad is
            # never surfaced here.
            try:
                pool = get_key_player_pool(team_id, conn)
                player_name = _top_xg_player(team_id, conn, pool["players"])
            except Exception as exc:
                logger.warning("player-form: pool resolution failed for %s: %s", team_id, exc)
                teams_out.append({
                    "team_id": team_id, "team_name": t["team_name"], "key_player": None,
                    "squad_status": "error", "uses_fallback_player_pool": False,
                    "squad_warning": "Error resolviendo el pool de jugadores para este equipo.",
                })
                continue

            # A team is never silently dropped: if we can't resolve a key
            # player (no squad match, no xG data), it still appears with
            # key_player=None and a warning explaining why — the frontend
            # must show that state explicitly instead of the team vanishing.
            if not player_name:
                teams_out.append({
                    "team_id": team_id, "team_name": t["team_name"], "key_player": None,
                    "squad_status": pool["squad_status"],
                    "uses_fallback_player_pool": pool["squad_status"] == "missing",
                    "squad_warning": pool["warning"] or "No hay jugador clave disponible con la fuente actual.",
                })
                continue

            form = get_player_form(player_name, team_id, conn)
            if not form["has_data"]:
                teams_out.append({
                    "team_id": team_id, "team_name": t["team_name"], "key_player": player_name,
                    "squad_status": pool["squad_status"],
                    "uses_fallback_player_pool": pool["squad_status"] == "missing",
                    "squad_warning": "Sin datos de forma reciente para este jugador.",
                })
                continue

            teams_out.append(
                {
                    "team_id":     team_id,
                    "team_name":   t["team_name"],
                    "key_player":  player_name,
                    "avg_xg":      form["avg_xg"],
                    "avg_goals":   form["avg_goals"],
                    "form_rating": form["form_rating"],
                    "matches_used": form["matches_used"],
                    "in_form":     form["in_form"],
                    "out_of_form": form["out_of_form"],
                    "squad_status": pool["squad_status"],
                    "uses_fallback_player_pool": pool["squad_status"] == "missing",
                    "squad_warning": pool["warning"],
                }
            )

    key_players_count = sum(1 for t in teams_out if t.get("key_player"))
    return {
        "teams": teams_out,
        "alive_only": alive_only,
        "alive_warning": alive_warning,
        "squads_available": sum(1 for t in teams_out if t["squad_status"] == "confirmed"),
        "key_players_count": key_players_count,
    }


# ---------------------------------------------------------------------------
# DELETE /api/news/{news_id}
# ---------------------------------------------------------------------------

@router.delete("/{news_id}", dependencies=[Depends(require_admin)])
def delete_news_claim(news_id: str) -> dict[str, Any]:
    """Delete a single availability claim by ID. Requires admin auth."""
    from app.db.repositories.availability import AvailabilityRepository
    with db_transaction() as conn:
        deleted = AvailabilityRepository(conn).delete_claim(news_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"News claim '{news_id}' not found")
    return {"deleted": True, "news_id": news_id}


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
