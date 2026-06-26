"""Suspension detector — computes FIFA WC disciplinary bans from player_bookings.

FIFA rules applied:
  - 2 yellow cards in same competition → 1-match ban
  - RED or YELLOW_RED card → minimum 1-match ban

NOTE: This is a simplified model — it does not track whether the suspension
has already been served (which would require knowing the next scheduled match
after each card event). It flags all players currently in a suspension state
based on raw card counts.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


def get_suspended_players(
    team_id: str,
    conn: sqlite3.Connection,
    competition: str = "WC2026",
) -> list[dict]:
    """Return players from *team_id* currently under a FIFA suspension.

    Returns a list of dicts with keys:
        player_name, team_id, reason, card_type
    """
    suspended: list[dict] = []
    seen: set[str] = set()

    # 2+ yellow cards → 1-match ban
    try:
        yellow_rows = conn.execute(
            """
            SELECT player_name, COUNT(*) AS cnt
            FROM player_bookings
            WHERE team_id = ? AND competition = ? AND card_type = 'YELLOW'
            GROUP BY player_name
            HAVING cnt >= 2
            """,
            (team_id, competition),
        ).fetchall()
    except Exception as exc:
        logger.warning("detector: yellow card query failed for %s: %s", team_id, exc)
        yellow_rows = []

    for row in yellow_rows:
        name = row["player_name"]
        seen.add(name)
        suspended.append(
            {
                "player_name": name,
                "team_id": team_id,
                "reason": f"{row['cnt']} tarjetas amarillas (FIFA: 2 = suspensión 1 partido)",
                "card_type": "YELLOW",
            }
        )

    # Red / double-yellow card → immediate ban
    try:
        red_rows = conn.execute(
            """
            SELECT DISTINCT player_name
            FROM player_bookings
            WHERE team_id = ? AND competition = ?
              AND card_type IN ('RED', 'YELLOW_RED')
            """,
            (team_id, competition),
        ).fetchall()
    except Exception as exc:
        logger.warning("detector: red card query failed for %s: %s", team_id, exc)
        red_rows = []

    for row in red_rows:
        name = row["player_name"]
        if name not in seen:
            seen.add(name)
            suspended.append(
                {
                    "player_name": name,
                    "team_id": team_id,
                    "reason": "Tarjeta roja (suspensión mínima 1 partido)",
                    "card_type": "RED",
                }
            )

    return suspended
