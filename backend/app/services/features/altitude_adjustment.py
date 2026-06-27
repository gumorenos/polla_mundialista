"""Altitude and host-team advantage adjustments for match prediction.

Rules:
- Teams accustomed to altitude (COL, ECU, MEX, BOL, PER) receive no penalty.
- Other teams at venues above 1 000 m receive a λ penalty of
  (altitude_m / 1 000) * 3.5 %, capped at 12 %.
- The team that is the host of the venue (host_team_id == team_id) gets a
  +5 % bonus on their attacking lambda.
- Returns a dict so callers can log details without re-querying.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# Teams that train/play at high altitude regularly — no adjustment applied.
_HIGH_ALTITUDE_TEAMS: frozenset[str] = frozenset({"COL", "ECU", "MEX", "BOL", "PER"})

_ALTITUDE_THRESHOLD_M = 1_000      # metres — below this no penalty
_PENALTY_PER_1000M    = 0.035      # 3.5 % per 1 000 m of altitude
_MAX_PENALTY          = 0.12       # cap at 12 %
_HOST_BONUS           = 0.05       # 5 % attack boost for the home-country team


def get_altitude_adjustment(
    team_id: str,
    venue_id: str,
    conn: sqlite3.Connection,
) -> dict[str, float] | None:
    """Return adjustment factors for *team_id* playing at *venue_id*.

    Returns None if the venue is not found in the DB.

    Keys in the returned dict:
        altitude_m          — venue altitude in metres
        altitude_adjustment — multiplier for attack λ (< 1.0 means penalty)
        host_bonus          — multiplier for attack λ (> 1.0 means bonus)
        combined            — altitude_adjustment * host_bonus
    """
    try:
        row = conn.execute(
            "SELECT altitude_m, host_team_id FROM venues WHERE venue_id = ?",
            (venue_id,),
        ).fetchone()
    except Exception as exc:
        logger.debug("altitude_adjustment: DB query failed for venue %s: %s", venue_id, exc)
        return None

    if row is None:
        logger.debug("altitude_adjustment: venue %s not found in DB", venue_id)
        return None

    altitude_m: int = int(row["altitude_m"] or 0)
    host_team_id: str | None = row["host_team_id"]

    # Altitude penalty
    if altitude_m > _ALTITUDE_THRESHOLD_M and team_id not in _HIGH_ALTITUDE_TEAMS:
        raw_penalty = (altitude_m / 1_000.0) * _PENALTY_PER_1000M
        penalty = min(raw_penalty, _MAX_PENALTY)
        altitude_adjustment = 1.0 - penalty
    else:
        altitude_adjustment = 1.0

    # Host-team bonus
    host_bonus = 1.0 + _HOST_BONUS if host_team_id == team_id else 1.0

    combined = altitude_adjustment * host_bonus

    logger.debug(
        "altitude_adjustment: team=%s venue=%s alt=%dm adj=%.4f host=%.4f combined=%.4f",
        team_id, venue_id, altitude_m, altitude_adjustment, host_bonus, combined,
    )

    return {
        "altitude_m":           float(altitude_m),
        "altitude_adjustment":  round(altitude_adjustment, 4),
        "host_bonus":           round(host_bonus, 4),
        "combined":             round(combined, 4),
    }
