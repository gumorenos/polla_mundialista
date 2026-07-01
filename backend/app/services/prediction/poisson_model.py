"""Poisson + Dixon-Coles prediction model.

Expected goals:
    lam_home = attack_H * defense_A * LOCAL_ADVANTAGE
    lam_away = attack_A * defense_H

Dixon-Coles correction on low-scoring cells (0-0, 1-0, 0-1, 1-1):
    tau(0,0) = 1 - lam_h * lam_a * rho
    tau(1,0) = 1 + lam_a * rho
    tau(0,1) = 1 + lam_h * rho
    tau(1,1) = 1 - rho

Matrix is renormalised after correction.
The inner _compute_probability_matrix is cached by (lam_h, lam_a, rho, max_goals).
"""

from __future__ import annotations

import logging
import math
import sqlite3
from functools import lru_cache

from app.core.config import settings
from app.services.prediction.base import PredictionModel

logger = logging.getLogger(__name__)

_DEFAULT_STRENGTH = 1.0
_DEFAULT_ELO_NEUTRAL = 1500.0
_ELO_PRIOR_SCALE = 1600.0  # spread controlling how far from 1.0 elite/weak ELO priors land
_ELO_PRIOR_BOUNDS = (0.4, 2.0)


def _elo_attack_defense_prior(elo: float) -> tuple[float, float]:
    """Map an ELO rating to (attack_prior, defense_prior) on the same ~1.0-
    centred scale as attack_strength/defense_vulnerability. Higher ELO →
    higher attack prior, lower (better) defense_vulnerability prior."""
    delta = (elo - _DEFAULT_ELO_NEUTRAL) / _ELO_PRIOR_SCALE
    lo, hi = _ELO_PRIOR_BOUNDS
    attack = min(hi, max(lo, 1.0 + delta))
    defense = min(hi, max(lo, 1.0 - delta))
    return attack, defense


def _elo_prior_weight(matches_used: int) -> float:
    """Blend weight for the ELO prior — POISSON_ELO_PRIOR_WEIGHT once
    matches_used reaches POISSON_ELO_PRIOR_MIN_MATCHES, scaling up toward
    POISSON_ELO_PRIOR_MAX_WEIGHT (never a pure ELO prior — some empirical
    signal is always kept) as matches_used approaches 0. Returns 0.0 when
    POISSON_ELO_PRIOR_ENABLED is False."""
    if not settings.POISSON_ELO_PRIOR_ENABLED:
        return 0.0
    base = settings.POISSON_ELO_PRIOR_WEIGHT
    max_weight = settings.POISSON_ELO_PRIOR_MAX_WEIGHT
    min_matches = settings.POISSON_ELO_PRIOR_MIN_MATCHES
    if min_matches <= 0 or matches_used >= min_matches:
        return min(base, max_weight)
    frac_missing = 1.0 - (matches_used / min_matches)
    w = base + (1.0 - base) * frac_missing
    return min(w, max_weight)


# ---------------------------------------------------------------------------
# Module-level cached matrix computation
# ---------------------------------------------------------------------------

@lru_cache(maxsize=512)
def _compute_probability_matrix(
    lam_home: float,
    lam_away: float,
    rho: float,
    max_goals: int,
) -> tuple[tuple[float, ...], ...]:
    """Return (max_goals+1) × (max_goals+1) probability matrix (row=home goals)."""
    n = max_goals + 1

    def pois(k: int, lam: float) -> float:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    matrix: list[list[float]] = [
        [pois(i, lam_home) * pois(j, lam_away) for j in range(n)]
        for i in range(n)
    ]

    # Dixon-Coles corrections — clamped to 0 to prevent negative probabilities
    corrections = {
        (0, 0): max(0.0, 1.0 - lam_home * lam_away * rho),
        (1, 0): max(0.0, 1.0 + lam_away * rho),
        (0, 1): max(0.0, 1.0 + lam_home * rho),
        (1, 1): max(0.0, 1.0 - rho),
    }
    for (i, j), tau in corrections.items():
        if i < n and j < n:
            matrix[i][j] *= tau

    # Renormalise
    total = sum(matrix[i][j] for i in range(n) for j in range(n))
    if total > 0:
        matrix = [[v / total for v in row] for row in matrix]

    return tuple(tuple(row) for row in matrix)


def _matrix_to_outcome_probs(
    matrix: tuple[tuple[float, ...], ...],
) -> tuple[float, float, float]:
    """Return (home_win, draw, away_win) from a goals probability matrix."""
    home_win = draw = away_win = 0.0
    n = len(matrix)
    for i in range(n):
        for j in range(n):
            p = matrix[i][j]
            if i > j:
                home_win += p
            elif i == j:
                draw += p
            else:
                away_win += p
    return home_win, draw, away_win


def _most_likely_score(matrix: tuple[tuple[float, ...], ...]) -> str:
    best_p = -1.0
    best_i = best_j = 0
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            if p > best_p:
                best_p, best_i, best_j = p, i, j
    return f"{best_i}-{best_j}"


# ---------------------------------------------------------------------------
# Model class
# ---------------------------------------------------------------------------

class PoissonModel(PredictionModel):
    name = "poisson"
    version = "1.0"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # Preload team strengths — avoids 2 DB queries per predict_match() call.
        self._strength_map: dict[str, tuple[float, float, int]] = self._load_strength_map()
        self._elo_map: dict[str, float] = self._load_elo_map()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_match(
        self,
        home_team_id: str,
        away_team_id: str,
        context: dict | None = None,
    ) -> dict:
        ctx = context or {}
        is_neutral: bool = ctx.get("is_neutral", False)

        lam_h, lam_a, used, missing = self._compute_lambdas(
            home_team_id, away_team_id, is_neutral
        )
        return self._build_prediction(lam_h, lam_a, used, missing)

    # ------------------------------------------------------------------
    # Shared helpers used by subclass
    # ------------------------------------------------------------------

    def _load_strength_map(self) -> dict[str, tuple[float, float, int]]:
        """Load all team strengths into memory (most recent per team)."""
        try:
            rows = self._conn.execute(
                """
                SELECT ts.team_id, ts.attack_strength, ts.defense_vulnerability, ts.matches_used
                FROM team_strengths ts
                INNER JOIN (
                    SELECT team_id, MAX(computed_at) AS max_at
                    FROM team_strengths GROUP BY team_id
                ) latest ON ts.team_id = latest.team_id
                         AND ts.computed_at = latest.max_at
                """
            ).fetchall()
            return {
                r["team_id"]: (
                    float(r["attack_strength"]),
                    float(r["defense_vulnerability"]),
                    int(r["matches_used"] or 0),
                )
                for r in rows
            }
        except Exception as exc:
            logger.warning("PoissonModel: failed to preload strength map: %s", exc)
            return {}

    def _load_elo_map(self) -> dict[str, float]:
        try:
            from app.services.ml.feature_builder import load_elo_map
            return load_elo_map(self._conn)
        except Exception as exc:
            logger.warning("PoissonModel: failed to preload ELO map: %s", exc)
            return {}

    def _get_strength(self, team_id: str) -> tuple[float, float, bool]:
        """Return (attack, defense, found) for a team, blended with an
        ELO-derived prior (see POISSON_ELO_PRIOR_WEIGHT/_MIN_MATCHES) so a
        small or noisy historical sample doesn't value a team far from its
        known ELO tier. The blend weight is small once matches_used is
        healthy, and grows toward a pure ELO prior as data thins out."""
        entry = self._strength_map.get(team_id)
        elo = self._elo_map.get(team_id)

        if entry is None:
            if elo is not None and settings.POISSON_ELO_PRIOR_ENABLED:
                attack, defense = _elo_attack_defense_prior(elo)
                return attack, defense, True
            logger.warning(
                "PoissonModel: no strength data for team %s — using defaults", team_id
            )
            return _DEFAULT_STRENGTH, _DEFAULT_STRENGTH, False

        attack, defense, matches_used = entry
        if elo is None:
            return attack, defense, True

        w = _elo_prior_weight(matches_used)
        elo_attack, elo_defense = _elo_attack_defense_prior(elo)
        blended_attack = (1 - w) * attack + w * elo_attack
        blended_defense = (1 - w) * defense + w * elo_defense
        return blended_attack, blended_defense, True

    def _compute_lambdas(
        self,
        home_id: str,
        away_id: str,
        is_neutral: bool,
    ) -> tuple[float, float, list[str], list[str]]:
        atk_h, def_h, found_h = self._get_strength(home_id)
        atk_a, def_a, found_a = self._get_strength(away_id)

        used:    list[str] = []
        missing: list[str] = []

        if found_h:
            used += ["attack_strength_home", "defense_vulnerability_home"]
        else:
            missing.append("team_strengths_home")

        if found_a:
            used += ["attack_strength_away", "defense_vulnerability_away"]
        else:
            missing.append("team_strengths_away")

        advantage = (
            settings.LOCAL_ADVANTAGE_NEUTRAL
            if is_neutral
            else settings.LOCAL_ADVANTAGE_HOME
        )
        used.append("local_advantage_neutral" if is_neutral else "local_advantage_home")

        lam_h = atk_h * def_a * advantage
        lam_a = atk_a * def_h
        return lam_h, lam_a, used, missing

    def _build_prediction(
        self,
        lam_h: float,
        lam_a: float,
        used: list[str],
        missing: list[str],
    ) -> dict:
        rho = settings.DIXON_COLES_RHO
        matrix = _compute_probability_matrix(
            round(lam_h, 4), round(lam_a, 4), rho, settings.POISSON_MAX_GOALS
        )
        home_win, draw, away_win = _matrix_to_outcome_probs(matrix)
        score = _most_likely_score(matrix)

        return {
            "home_win":             home_win,
            "draw":                 draw,
            "away_win":             away_win,
            "expected_home_goals":  lam_h,
            "expected_away_goals":  lam_a,
            "most_likely_score":    score,
            "features_used":        used,
            "features_missing":     missing,
            "explanation": (
                f"Poisson+DC: λ_home={lam_h:.2f} λ_away={lam_a:.2f} ρ={rho} "
                f"→ {home_win:.1%}/{draw:.1%}/{away_win:.1%}"
            ),
        }
