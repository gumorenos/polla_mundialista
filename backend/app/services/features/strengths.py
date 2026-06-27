"""Team strength calculator — attack/defense with temporal decay.

For each match involving team X:
    days   = (as_of_date - match_date).days
    weight = exp(-decay * days)
    rival_factor = 1 + (rival_elo / 3000)
    attack_raw  += goals_for  * weight * rival_factor
    defense_raw += goals_against * weight * rival_factor
    weight_total += weight

Post-normalisation: global mean is scaled to 1.0 for both attack and defence.
Teams with no history receive neutral values (1.0 / 1.0).
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import date, datetime, timezone
from statistics import mean, stdev
from typing import Any

from app.core.config import settings
from app.db.repositories.strengths import StrengthRepository

logger = logging.getLogger(__name__)

_MIN_WEIGHT = 1e-6       # below this a match is considered negligible
_STRENGTH_MIN = 0.30    # hard floor after normalisation
_STRENGTH_MAX = 3.00    # hard ceiling after normalisation
_XG_MIN_MATCHES = 3     # minimum StatsBomb matches to trust xG strengths


def calculate_xg_strengths(
    team_id: str,
    conn: sqlite3.Connection,
    last_n_matches: int = 30,
    decay_factor: float | None = None,
) -> dict[str, Any] | None:
    """Compute attack/defense strengths based on xG (expected goals) from StatsBomb.

    xG is more stable and predictive than actual goals.
    Returns None if fewer than _XG_MIN_MATCHES records exist for this team.
    """
    decay = decay_factor if decay_factor is not None else settings.TIME_DECAY_FACTOR
    today = date.today()

    try:
        rows = conn.execute(
            """
            SELECT sms.xg, sms.xg_conceded, sm.match_date
            FROM sb_match_stats sms
            JOIN sb_matches sm ON sms.match_id = sm.match_id
            WHERE sms.team_id = ?
            ORDER BY sm.match_date DESC
            LIMIT ?
            """,
            (team_id, last_n_matches),
        ).fetchall()
    except Exception as exc:
        logger.debug("calculate_xg_strengths: query failed for %s: %s", team_id, exc)
        return None

    if len(rows) < _XG_MIN_MATCHES:
        return None

    # Global averages for normalisation
    try:
        g = conn.execute(
            """
            SELECT AVG(xg) AS avg_xg, AVG(xg_conceded) AS avg_xgc
            FROM sb_match_stats
            WHERE xg > 0 OR xg_conceded > 0
            """
        ).fetchone()
        global_avg_xg  = float(g["avg_xg"]  or 1.0)
        global_avg_xgc = float(g["avg_xgc"] or 1.0)
    except Exception:
        global_avg_xg  = 1.0
        global_avg_xgc = 1.0

    if global_avg_xg <= 0:
        global_avg_xg = 1.0
    if global_avg_xgc <= 0:
        global_avg_xgc = 1.0

    # Temporally-decayed weighted average
    xg_weighted  = 0.0
    xgc_weighted = 0.0
    weight_total = 0.0

    for row in rows:
        try:
            match_date = date.fromisoformat(row["match_date"][:10])
        except (ValueError, TypeError):
            continue
        days = max(0, (today - match_date).days)
        weight = math.exp(-decay * days)
        xg_weighted  += float(row["xg"])          * weight
        xgc_weighted += float(row["xg_conceded"]) * weight
        weight_total += weight

    if weight_total <= 0:
        return None

    avg_xg  = xg_weighted  / weight_total
    avg_xgc = xgc_weighted / weight_total

    attack_xg  = max(_STRENGTH_MIN, min(_STRENGTH_MAX, avg_xg  / global_avg_xg))
    defense_xg = max(_STRENGTH_MIN, min(_STRENGTH_MAX, avg_xgc / global_avg_xgc))

    return {
        "attack_xg":   round(attack_xg,  4),
        "defense_xg":  round(defense_xg, 4),
        "sample_size": len(rows),
    }


def calculate_team_strengths(
    conn: sqlite3.Connection,
    as_of_date: date | None = None,
    decay_factor: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute and persist attack/defense strengths for all WC2026 teams.

    Returns a dict keyed by team_id with the computed strength values.
    """
    cutoff = as_of_date or date.today()
    decay = decay_factor if decay_factor is not None else settings.TIME_DECAY_FACTOR
    cutoff_iso = cutoff.isoformat()

    teams = _load_teams(conn)
    elo_map = _load_elo_map(conn)
    results = _load_results(conn, cutoff_iso)

    # Build per-team accumulators
    # { team_id: {attack_bruto, defense_bruto, weight_total, matches_used,
    #             matches_with_elo, matches_total, goals_for_sum, goals_against_sum} }
    acc: dict[str, dict[str, float | int]] = {
        tid: {
            "attack_bruto": 0.0,
            "defense_bruto": 0.0,
            "weight_total": 0.0,
            "matches_used": 0,
            "matches_with_elo": 0,
            "matches_total": 0,
            "goals_for_sum": 0.0,
            "goals_against_sum": 0.0,
        }
        for tid in teams
    }

    for row in results:
        match_date_str = row["match_date"][:10]  # strip time component if present
        try:
            match_date = date.fromisoformat(match_date_str)
        except ValueError:
            continue

        dias = (cutoff - match_date).days
        if dias < 0:
            continue  # future result — skip

        weight = math.exp(-decay * dias)

        home_id = row["home_team_id"]
        away_id = row["away_team_id"]
        home_goals = row["home_goals"] or 0
        away_goals = row["away_goals"] or 0

        for team_id, goals_for, goals_against, rival_id in (
            (home_id, home_goals, away_goals, away_id),
            (away_id, away_goals, home_goals, home_id),
        ):
            if team_id not in acc:
                continue  # result involves a team not in our 48-team set; skip

            rival_elo = elo_map.get(rival_id)
            has_elo = rival_elo is not None
            rival_factor = 1.0 + ((rival_elo or 1500.0) / 3000.0)

            a = acc[team_id]
            a["attack_bruto"]  += goals_for  * weight * rival_factor
            a["defense_bruto"] += goals_against * weight * rival_factor
            a["weight_total"]  += weight
            a["matches_total"] += 1
            a["goals_for_sum"] += goals_for
            a["goals_against_sum"] += goals_against
            if weight > _MIN_WEIGHT:
                a["matches_used"] += 1
            if has_elo:
                a["matches_with_elo"] += 1

    # Raw averages per team (0.0 for teams with no history)
    raw_attack: dict[str, float] = {}
    raw_defense: dict[str, float] = {}

    for tid, a in acc.items():
        wt = a["weight_total"]
        if wt > 0:
            raw_attack[tid]  = a["attack_bruto"]  / wt
            raw_defense[tid] = a["defense_bruto"] / wt
        else:
            raw_attack[tid]  = None  # type: ignore[assignment]
            raw_defense[tid] = None  # type: ignore[assignment]

    # Global means (exclude teams with no data so they don't skew the average)
    valid_atk = [v for v in raw_attack.values() if v is not None]
    valid_def = [v for v in raw_defense.values() if v is not None]

    global_mean_atk = mean(valid_atk) if valid_atk else 1.0
    global_mean_def = mean(valid_def) if valid_def else 1.0

    # Avoid division by zero
    if global_mean_atk == 0:
        global_mean_atk = 1.0
    if global_mean_def == 0:
        global_mean_def = 1.0

    # Build final results and persist
    repo = StrengthRepository(conn)
    output: dict[str, dict[str, Any]] = {}

    for tid in teams:
        a = acc[tid]
        has_history = a["weight_total"] > 0

        if has_history:
            norm_atk = max(_STRENGTH_MIN, min(_STRENGTH_MAX, raw_attack[tid]  / global_mean_atk))
            norm_def = max(_STRENGTH_MIN, min(_STRENGTH_MAX, raw_defense[tid] / global_mean_def))
            matches_total = a["matches_total"]
            dq_score = a["matches_with_elo"] / matches_total if matches_total else 0.0
            avg_gf = a["goals_for_sum"] / matches_total
            avg_ga = a["goals_against_sum"] / matches_total
        else:
            norm_atk = 1.0
            norm_def = 1.0
            dq_score = 0.0
            avg_gf = 0.0
            avg_ga = 0.0

        strength = {
            "team_id":              tid,
            "attack_strength":      norm_atk,
            "defense_vulnerability": norm_def,
            "matches_used":         int(a["matches_used"]),
            "cutoff_date":          cutoff_iso,
            "decay_factor":         decay,
            # extra computed fields (not persisted in this schema but returned)
            "avg_goals_for":        avg_gf,
            "avg_goals_against":    avg_ga,
            "data_quality_score":   dq_score,
            "calculated_at":        datetime.now(timezone.utc).isoformat(),
        }
        repo.upsert(strength)
        output[tid] = strength

    conn.commit()

    _log_summary(output)
    return output


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _load_teams(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {team_id: team_name} for all teams in DB."""
    rows = conn.execute("SELECT id, name FROM teams").fetchall()
    return {r["id"]: r["name"] for r in rows}


def _load_elo_map(conn: sqlite3.Connection) -> dict[str, float]:
    """Return {team_id: elo_value} using the most recent ELO rating per team."""
    rows = conn.execute(
        """
        SELECT r.team_id, r.value
        FROM ratings r
        INNER JOIN (
            SELECT team_id, MAX(effective_date) AS max_date
            FROM ratings WHERE rating_type = 'elo'
            GROUP BY team_id
        ) latest ON r.team_id = latest.team_id
                 AND r.effective_date = latest.max_date
                 AND r.rating_type = 'elo'
        """
    ).fetchall()
    return {r["team_id"]: float(r["value"]) for r in rows}


def _load_results(conn: sqlite3.Connection, cutoff_iso: str) -> list[sqlite3.Row]:
    """Return all results on or before cutoff_iso with complete goal data."""
    return conn.execute(
        """
        SELECT home_team_id, away_team_id, home_goals, away_goals, match_date
        FROM results
        WHERE match_date <= ?
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
        ORDER BY match_date ASC
        """,
        (cutoff_iso,),
    ).fetchall()


def _log_summary(output: dict[str, dict[str, Any]]) -> None:
    attacks  = [v["attack_strength"]      for v in output.values()]
    defenses = [v["defense_vulnerability"] for v in output.values()]

    def _stats(vals: list[float]) -> str:
        if not vals:
            return "n/a"
        mn = min(vals)
        mx = max(vals)
        mu = mean(vals)
        sd = stdev(vals) if len(vals) > 1 else 0.0
        return f"min={mn:.3f} max={mx:.3f} mean={mu:.3f} std={sd:.3f}"

    logger.info(
        "Team strengths computed for %d teams | attack [%s] | defense [%s]",
        len(output),
        _stats(attacks),
        _stats(defenses),
    )
