"""ELO-based prediction model.

P_home_raw  = 1 / (1 + 10^(-ΔElo/400))   — standard ELO win probability
P_draw      = draw_rate_base * balance     — draw rate scaled by match closeness
P_home_win  = P_home_raw * (1 - P_draw)
P_away_win  = (1 - P_home_raw) * (1 - P_draw)

This guarantees P_home_win + P_draw + P_away_win = 1.
"""

from __future__ import annotations

import logging
import sqlite3

from app.services.prediction.base import PredictionModel

logger = logging.getLogger(__name__)

_DEFAULT_ELO = 1500.0
_DEFAULT_DRAW_RATE = 0.25


class EloModel(PredictionModel):
    name = "elo"
    version = "1.0"

    def __init__(
        self,
        conn: sqlite3.Connection,
        draw_rate: float | None = None,
    ) -> None:
        self._conn = conn
        self._draw_rate_base = (
            draw_rate if draw_rate is not None else self._compute_draw_rate()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_match(
        self,
        home_team_id: str,
        away_team_id: str,
        context: dict | None = None,
    ) -> dict:
        elo_h = self._get_elo(home_team_id)
        elo_a = self._get_elo(away_team_id)

        features_used:    list[str] = []
        features_missing: list[str] = []

        if elo_h is not None:
            features_used.append("elo_home")
        else:
            features_missing.append("elo_home")
            logger.warning("EloModel: no ELO for team %s — using default", home_team_id)
            elo_h = _DEFAULT_ELO

        if elo_a is not None:
            features_used.append("elo_away")
        else:
            features_missing.append("elo_away")
            logger.warning("EloModel: no ELO for team %s — using default", away_team_id)
            elo_a = _DEFAULT_ELO

        delta = elo_h - elo_a
        p_home_raw = 1.0 / (1.0 + 10.0 ** (-delta / 400.0))

        # Draw probability decreases as match becomes less balanced
        balance  = 1.0 - 2.0 * abs(0.5 - p_home_raw)
        p_draw   = self._draw_rate_base * balance
        p_home_win = p_home_raw * (1.0 - p_draw)
        p_away_win = (1.0 - p_home_raw) * (1.0 - p_draw)

        # Rough goal estimates proportional to win probability
        exp_h = 1.5 * p_home_raw
        exp_a = 1.5 * (1.0 - p_home_raw)

        score = "1-0" if p_home_win >= p_away_win else "0-1"
        if p_draw >= p_home_win and p_draw >= p_away_win:
            score = "1-1"

        return {
            "home_win":             p_home_win,
            "draw":                 p_draw,
            "away_win":             p_away_win,
            "expected_home_goals":  exp_h,
            "expected_away_goals":  exp_a,
            "most_likely_score":    score,
            "features_used":        features_used,
            "features_missing":     features_missing,
            "explanation": (
                f"ELO home={elo_h:.0f} away={elo_a:.0f} ΔElo={delta:+.0f} "
                f"→ P(home_win)={p_home_win:.2%} P(draw)={p_draw:.2%} "
                f"P(away_win)={p_away_win:.2%}"
            ),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_elo(self, team_id: str) -> float | None:
        try:
            row = self._conn.execute(
                """
                SELECT value FROM ratings
                WHERE team_id = ? AND rating_type = 'elo'
                ORDER BY effective_date DESC
                LIMIT 1
                """,
                (team_id,),
            ).fetchone()
        except Exception as exc:
            logger.warning("EloModel: DB error for team %s: %s", team_id, exc)
            return None
        return float(row["value"]) if row else None

    def _compute_draw_rate(self) -> float:
        try:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN outcome='D' THEN 1 ELSE 0 END) AS draws
                FROM results
                WHERE outcome IN ('W','D','L')
                """
            ).fetchone()
        except Exception:
            return _DEFAULT_DRAW_RATE
        if not row or not row["total"]:
            return _DEFAULT_DRAW_RATE
        rate = row["draws"] / row["total"]
        logger.info("EloModel: historical draw rate = %.1f%%", rate * 100)
        return rate
