"""Own ELO calculator — computed from historical match results.

The computed ELO is written back to the `ratings` table with source='own_elo'
so EloModel picks it up automatically (it queries ORDER BY effective_date DESC).
The `elo_history` table stores per-match snapshots for the timeline chart.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

K_FACTOR = 32
_DEFAULT_ELO = 1500.0


# ---------------------------------------------------------------------------
# Pure math — no DB access
# ---------------------------------------------------------------------------

def expected_score(rating_a: float, rating_b: float) -> float:
    """Expected win probability for team A given ratings A and B."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo(
    rating_home: float,
    rating_away: float,
    goals_home: int,
    goals_away: int,
    k_factor: float = K_FACTOR,
) -> tuple[float, float]:
    """Return (new_elo_home, new_elo_away) after one match.

    Applies a goal-difference multiplier to amplify the K update for
    lopsided results, matching the method used by eloratings.net.
    """
    exp_home = expected_score(rating_home, rating_away)
    exp_away = 1.0 - exp_home

    if goals_home > goals_away:
        actual_home, actual_away = 1.0, 0.0
    elif goals_home < goals_away:
        actual_home, actual_away = 0.0, 1.0
    else:
        actual_home, actual_away = 0.5, 0.5

    goal_diff = abs(goals_home - goals_away)
    if goal_diff <= 1:
        goal_factor = 1.0
    elif goal_diff == 2:
        goal_factor = 1.5
    else:
        goal_factor = 1.75 + (goal_diff - 3) * 0.1  # caps growth beyond 3-goal leads

    delta_home = k_factor * goal_factor * (actual_home - exp_home)
    new_home = rating_home + delta_home
    new_away = rating_away - delta_home  # zero-sum

    return new_home, new_away


# ---------------------------------------------------------------------------
# Full recalculation — called in full_refresh
# ---------------------------------------------------------------------------

def recalculate_all_elos(conn: sqlite3.Connection) -> dict[str, Any]:
    """Recompute all ELOs from scratch using every result in the DB.

    Uses scraped/CSV ELOs as the starting point (source != 'own_elo') so
    repeated runs don't compound into drift.  Writes final values back to
    the `ratings` table and stores per-match snapshots in `elo_history`.
    """
    from app.db.repositories.elo_history import EloHistoryRepository
    from app.db.repositories.ratings import RatingRepository

    elo_history_repo = EloHistoryRepository(conn)
    rating_repo = RatingRepository(conn)

    # Initial ratings: prefer scraper/CSV, fall back to 1500
    seed_ratings = rating_repo.list_latest_excluding_source("elo", "own_elo")
    elos: dict[str, float] = {r["team_id"]: float(r["value"]) for r in seed_ratings}

    matches = elo_history_repo.get_all_results_ordered()
    elo_history_repo.clear_all()

    history: list[dict[str, Any]] = []
    updated_teams: set[str] = set()

    for match in matches:
        home_id = match["home_team_id"]
        away_id = match["away_team_id"]

        elo_h = elos.get(home_id, _DEFAULT_ELO)
        elo_a = elos.get(away_id, _DEFAULT_ELO)

        new_h, new_a = update_elo(elo_h, elo_a, int(match["home_goals"]), int(match["away_goals"]))

        history.append({
            "team_id":      home_id,
            "elo_rating":   round(new_h, 2),
            "match_date":   match["match_date"],
            "opponent_id":  away_id,
            "goals_for":    int(match["home_goals"]),
            "goals_against": int(match["away_goals"]),
            "elo_change":   round(new_h - elo_h, 2),
        })
        history.append({
            "team_id":      away_id,
            "elo_rating":   round(new_a, 2),
            "match_date":   match["match_date"],
            "opponent_id":  home_id,
            "goals_for":    int(match["away_goals"]),
            "goals_against": int(match["home_goals"]),
            "elo_change":   round(new_a - elo_a, 2),
        })

        elos[home_id] = new_h
        elos[away_id] = new_a
        updated_teams.add(home_id)
        updated_teams.add(away_id)

    elo_history_repo.save_batch(history)

    # Persist final values so EloModel picks them up
    now = datetime.now(timezone.utc).isoformat()
    for team_id, value in elos.items():
        rating_repo.upsert_elo(team_id, value, now, source="own_elo")

    logger.info(
        "ELO recalculation complete: %d matches processed, %d teams updated",
        len(matches), len(updated_teams),
    )
    return {"matches_processed": len(matches), "teams_updated": len(updated_teams)}


# ---------------------------------------------------------------------------
# Incremental update — called in daily_update
# ---------------------------------------------------------------------------

def update_elos_for_new_matches(conn: sqlite3.Connection) -> dict[str, Any]:
    """Process only matches that occurred after the last elo_history entry.

    Safe to call repeatedly — skips matches already recorded.
    """
    from app.db.repositories.elo_history import EloHistoryRepository
    from app.db.repositories.ratings import RatingRepository

    elo_history_repo = EloHistoryRepository(conn)
    rating_repo = RatingRepository(conn)

    last_date = elo_history_repo.get_latest_match_date()
    new_matches = elo_history_repo.get_results_since(last_date)

    if not new_matches:
        logger.debug("update_elos_for_new_matches: no new matches to process")
        return {"matches_processed": 0}

    # Use current ratings (including own_elo) as starting state
    current = rating_repo.list_latest_all("elo")
    elos: dict[str, float] = {r["team_id"]: float(r["value"]) for r in current}

    history: list[dict[str, Any]] = []
    updated_teams: set[str] = set()

    for match in new_matches:
        home_id = match["home_team_id"]
        away_id = match["away_team_id"]

        elo_h = elos.get(home_id, _DEFAULT_ELO)
        elo_a = elos.get(away_id, _DEFAULT_ELO)

        new_h, new_a = update_elo(elo_h, elo_a, int(match["home_goals"]), int(match["away_goals"]))

        history.append({
            "team_id":      home_id,
            "elo_rating":   round(new_h, 2),
            "match_date":   match["match_date"],
            "opponent_id":  away_id,
            "goals_for":    int(match["home_goals"]),
            "goals_against": int(match["away_goals"]),
            "elo_change":   round(new_h - elo_h, 2),
        })
        history.append({
            "team_id":      away_id,
            "elo_rating":   round(new_a, 2),
            "match_date":   match["match_date"],
            "opponent_id":  home_id,
            "goals_for":    int(match["away_goals"]),
            "goals_against": int(match["home_goals"]),
            "elo_change":   round(new_a - elo_a, 2),
        })

        elos[home_id] = new_h
        elos[away_id] = new_a
        updated_teams.add(home_id)
        updated_teams.add(away_id)

    elo_history_repo.save_batch(history)

    now = datetime.now(timezone.utc).isoformat()
    for team_id in updated_teams:
        rating_repo.upsert_elo(team_id, elos[team_id], now, source="own_elo")

    logger.info(
        "Incremental ELO update: %d new matches, %d teams updated",
        len(new_matches), len(updated_teams),
    )
    return {"matches_processed": len(new_matches), "teams_updated": len(updated_teams)}
