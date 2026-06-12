"""Build feature vectors from the DB for ML model training and inference.

Feature set (11 features):
    elo_home, elo_away, elo_diff             — team quality from ELO
    attack_home, defense_home                — Poisson strengths
    attack_away, defense_away
    is_neutral                               — venue context
    lam_home, lam_away                       — Poisson expected goals
    elo_p_home                               — ELO raw win probability

Labels (for training):  0=home_win, 1=draw, 2=away_win
"""

from __future__ import annotations

import logging
import math
import sqlite3

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

FEATURE_NAMES: list[str] = [
    "elo_home",
    "elo_away",
    "elo_diff",
    "attack_home",
    "defense_home",
    "attack_away",
    "defense_away",
    "is_neutral",
    "lam_home",
    "lam_away",
    "elo_p_home",
]

_DEFAULT_ELO = 1500.0
_DEFAULT_ATTACK = 1.0
_DEFAULT_DEFENSE = 1.0


# ---------------------------------------------------------------------------
# DB lookups (pre-loaded once per training/inference run)
# ---------------------------------------------------------------------------

def load_elo_map(conn: sqlite3.Connection) -> dict[str, float]:
    """Return {team_id: elo} using the most recent ELO per team."""
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


def load_strength_map(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    """Return {team_id: {attack, defense}} using the most recent strengths."""
    rows = conn.execute(
        """
        SELECT ts.team_id, ts.attack_strength, ts.defense_vulnerability
        FROM team_strengths ts
        INNER JOIN (
            SELECT team_id, MAX(computed_at) AS max_at
            FROM team_strengths
            GROUP BY team_id
        ) latest ON ts.team_id = latest.team_id
                 AND ts.computed_at = latest.max_at
        """
    ).fetchall()
    return {
        r["team_id"]: {
            "attack": float(r["attack_strength"]),
            "defense": float(r["defense_vulnerability"]),
        }
        for r in rows
    }


# ---------------------------------------------------------------------------
# Single-match feature computation
# ---------------------------------------------------------------------------

def compute_features(
    home_team_id: str,
    away_team_id: str,
    is_neutral: bool,
    elo_map: dict[str, float],
    strength_map: dict[str, dict[str, float]],
) -> tuple[list[float], list[str]]:
    """Return (feature_vector, missing_feature_names) for a single match.

    Uses pre-loaded maps for efficiency in batch contexts.
    """
    missing: list[str] = []

    elo_h = elo_map.get(home_team_id)
    elo_a = elo_map.get(away_team_id)
    if elo_h is None:
        missing.append("elo_home")
        elo_h = _DEFAULT_ELO
    if elo_a is None:
        missing.append("elo_away")
        elo_a = _DEFAULT_ELO

    s_h = strength_map.get(home_team_id, {})
    s_a = strength_map.get(away_team_id, {})
    if not s_h:
        missing.append("strength_home")
    if not s_a:
        missing.append("strength_away")

    atk_h = s_h.get("attack",  _DEFAULT_ATTACK)
    def_h = s_h.get("defense", _DEFAULT_DEFENSE)
    atk_a = s_a.get("attack",  _DEFAULT_ATTACK)
    def_a = s_a.get("defense", _DEFAULT_DEFENSE)

    advantage = (
        settings.LOCAL_ADVANTAGE_NEUTRAL
        if is_neutral
        else settings.LOCAL_ADVANTAGE_HOME
    )
    lam_h = atk_h * def_a * advantage
    lam_a = atk_a * def_h

    elo_diff = elo_h - elo_a
    elo_p_home = 1.0 / (1.0 + 10.0 ** (-elo_diff / 400.0))

    features = [
        elo_h,
        elo_a,
        elo_diff,
        atk_h,
        def_h,
        atk_a,
        def_a,
        1.0 if is_neutral else 0.0,
        lam_h,
        lam_a,
        elo_p_home,
    ]
    return features, missing


def build_match_features(
    home_team_id: str,
    away_team_id: str,
    conn: sqlite3.Connection,
    is_neutral: bool = True,
) -> tuple[list[float], list[str]]:
    """Convenience wrapper — loads maps from DB and computes one match's features."""
    elo_map = load_elo_map(conn)
    strength_map = load_strength_map(conn)
    return compute_features(
        home_team_id, away_team_id, is_neutral, elo_map, strength_map
    )


# ---------------------------------------------------------------------------
# Training dataset builder
# ---------------------------------------------------------------------------

def build_training_dataset(
    conn: sqlite3.Connection,
    train_start_year: int | None = None,
    train_end_date: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (X, y) arrays from historical results.

    y labels: 0=home_win, 1=draw, 2=away_win.

    Note: ELO and strengths are current values, not at-time-of-match values.
    This is an acceptable approximation for predicting upcoming World Cup matches.
    """
    start_year = train_start_year or settings.ML_TRAIN_START_YEAR
    end_date   = train_end_date or "9999-12-31"
    start_date = f"{start_year}-01-01"

    rows = conn.execute(
        """
        SELECT home_team_id, away_team_id, home_goals, away_goals,
               match_date, is_wc
        FROM results
        WHERE match_date >= ?
          AND match_date <= ?
          AND home_goals  IS NOT NULL
          AND away_goals  IS NOT NULL
        ORDER BY match_date ASC
        """,
        (start_date, end_date),
    ).fetchall()

    elo_map      = load_elo_map(conn)
    strength_map = load_strength_map(conn)

    X_rows: list[list[float]] = []
    y_rows: list[int] = []
    skipped = 0

    for row in rows:
        home_id = row["home_team_id"]
        away_id = row["away_team_id"]
        hg      = row["home_goals"]
        ag      = row["away_goals"]
        is_wc   = bool(row["is_wc"])

        try:
            features, _ = compute_features(
                home_id, away_id, is_wc, elo_map, strength_map
            )
        except Exception as exc:
            logger.debug("Skipping %s vs %s: %s", home_id, away_id, exc)
            skipped += 1
            continue

        label = 0 if hg > ag else (1 if hg == ag else 2)
        X_rows.append(features)
        y_rows.append(label)

    logger.info(
        "build_training_dataset: %d samples, %d skipped (start=%s end=%s)",
        len(X_rows), skipped, start_date, end_date,
    )

    if not X_rows:
        return np.empty((0, len(FEATURE_NAMES)), dtype=float), np.empty(0, dtype=int)

    return np.array(X_rows, dtype=float), np.array(y_rows, dtype=int)
