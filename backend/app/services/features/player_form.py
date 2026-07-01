"""Player form scoring based on StatsBomb xG history.

get_player_form(player_name, team_id, conn, last_n=5)
    → recent xG-based form for a specific player.

get_team_form_adjustment(team_id, conn)
    → attack lambda multiplier (0.92–1.08) derived from the team's
      top-xG player's recent form.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

_AVERAGE_XG_PER_GAME = 0.3   # typical xG for a regular starter
_IN_FORM_THRESHOLD   = 1.2   # form_rating above this → in form
_OUT_OF_FORM_THRESH  = 0.5   # form_rating below this → out of form
_IN_FORM_BONUS       = 1.08  # +8 % attack bonus
_OUT_OF_FORM_PENALTY = 0.92  # −8 % attack penalty


def get_player_form(
    player_name: str,
    team_id: str,
    conn: sqlite3.Connection,
    last_n: int = 5,
) -> dict:
    """Return form data for *player_name* in *team_id*.

    Returns a dict with keys:
        has_data      — bool: whether StatsBomb records exist
        matches_used  — int: number of matches analysed
        avg_xg        — float: average xG per match
        avg_goals     — float: average goals per match
        form_rating   — float: avg_xg / _AVERAGE_XG_PER_GAME (1.0 = average)
        in_form       — bool: form_rating > _IN_FORM_THRESHOLD
        out_of_form   — bool: form_rating < _OUT_OF_FORM_THRESH
    """
    try:
        rows = conn.execute(
            """
            SELECT sps.xg, sps.goals
            FROM sb_player_stats sps
            JOIN sb_matches sm ON sps.match_id = sm.match_id
            WHERE sps.player_name = ?
              AND sps.team_id     = ?
            ORDER BY sm.match_date DESC
            LIMIT ?
            """,
            (player_name, team_id, last_n),
        ).fetchall()
    except Exception as exc:
        logger.debug("get_player_form: query failed for %s/%s: %s", player_name, team_id, exc)
        return _no_data()

    if not rows:
        return _no_data()

    avg_xg   = sum(float(r["xg"]    or 0) for r in rows) / len(rows)
    avg_goals = sum(float(r["goals"] or 0) for r in rows) / len(rows)
    form_rating = avg_xg / _AVERAGE_XG_PER_GAME if _AVERAGE_XG_PER_GAME > 0 else 1.0

    return {
        "has_data":    True,
        "matches_used": len(rows),
        "avg_xg":      round(avg_xg,    3),
        "avg_goals":   round(avg_goals,  3),
        "form_rating": round(form_rating, 3),
        "in_form":     form_rating > _IN_FORM_THRESHOLD,
        "out_of_form": form_rating < _OUT_OF_FORM_THRESH,
    }


def _top_xg_player(team_id: str, conn: sqlite3.Connection, candidate_names: list[str]) -> str | None:
    """Highest cumulative-xG player among *candidate_names* for *team_id*."""
    if not candidate_names:
        return None
    placeholders = ",".join("?" for _ in candidate_names)
    row = conn.execute(
        f"""
        SELECT player_name FROM sb_player_stats
        WHERE team_id = ? AND player_name IN ({placeholders})
        GROUP BY player_name
        ORDER BY SUM(xg) DESC
        LIMIT 1
        """,
        [team_id, *candidate_names],
    ).fetchone()
    return row["player_name"] if row else None


def get_team_form_adjustment(
    team_id: str,
    conn: sqlite3.Connection,
    last_n: int = 5,
) -> float:
    """Return an attack-lambda multiplier based on the team's main striker form.

    Finds the highest-cumulative-xG player restricted to the real WC2026
    squad when known (see get_key_player_pool) and evaluates their recent
    form.

    Returns:
        1.08  if the player is in form (form_rating > 1.2)
        0.92  if the player is out of form (form_rating < 0.5)
        1.0   if no StatsBomb data, no squad match, or form is average
    """
    from app.services.features.squad_pool import get_key_player_pool

    try:
        pool = get_key_player_pool(team_id, conn)
        top_player = _top_xg_player(team_id, conn, pool["players"])
    except Exception as exc:
        logger.debug("get_team_form_adjustment: query failed for %s: %s", team_id, exc)
        return 1.0

    if top_player is None:
        return 1.0

    form = get_player_form(top_player, team_id, conn, last_n=last_n)

    if not form["has_data"]:
        return 1.0

    if form["in_form"]:
        logger.debug(
            "form_adjustment: %s key player %s is IN FORM (rating=%.3f) → +8%%",
            team_id, top_player, form["form_rating"],
        )
        return _IN_FORM_BONUS

    if form["out_of_form"]:
        logger.debug(
            "form_adjustment: %s key player %s is OUT OF FORM (rating=%.3f) → −8%%",
            team_id, top_player, form["form_rating"],
        )
        return _OUT_OF_FORM_PENALTY

    return 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _no_data() -> dict:
    return {
        "has_data":     False,
        "matches_used": 0,
        "avg_xg":       0.0,
        "avg_goals":    0.0,
        "form_rating":  0.0,
        "in_form":      False,
        "out_of_form":  False,
    }
