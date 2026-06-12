"""Baseline model — global historical win/draw/loss frequency."""

from __future__ import annotations

import logging
import sqlite3

from app.services.prediction.base import PredictionModel

logger = logging.getLogger(__name__)

_UNIFORM = {"home_win": 1 / 3, "draw": 1 / 3, "away_win": 1 / 3}


class BaselineModel(PredictionModel):
    name = "baseline"
    version = "1.0"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._rates = self._compute_rates()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_match(
        self,
        home_team_id: str,
        away_team_id: str,
        context: dict | None = None,
    ) -> dict:
        r = self._rates
        is_uniform = r == _UNIFORM
        return {
            "home_win":             r["home_win"],
            "draw":                 r["draw"],
            "away_win":             r["away_win"],
            "expected_home_goals":  1.5,
            "expected_away_goals":  1.0,
            "most_likely_score":    "1-1",
            "features_used":        [] if is_uniform else ["historical_results"],
            "features_missing":     ["historical_results"] if is_uniform else [],
            "explanation": (
                "Uniform 1/3 probabilities (no historical data)"
                if is_uniform
                else (
                    f"Global historical rates: "
                    f"W={r['home_win']:.1%} D={r['draw']:.1%} L={r['away_win']:.1%}"
                )
            ),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_rates(self) -> dict:
        try:
            rows = self._conn.execute(
                "SELECT outcome FROM results WHERE outcome IN ('W','D','L')"
            ).fetchall()
        except Exception as exc:
            logger.warning("Baseline: failed to read results (%s) — using uniform", exc)
            return dict(_UNIFORM)

        if not rows:
            logger.warning("Baseline: no historical results found — using uniform probs")
            return dict(_UNIFORM)

        total = len(rows)
        wins  = sum(1 for r in rows if r["outcome"] == "W")
        draws = sum(1 for r in rows if r["outcome"] == "D")
        losses = total - wins - draws
        rates = {
            "home_win": wins  / total,
            "draw":     draws / total,
            "away_win": losses / total,
        }
        logger.info(
            "Baseline rates from %d matches: W=%.1f%% D=%.1f%% L=%.1f%%",
            total,
            rates["home_win"] * 100,
            rates["draw"] * 100,
            rates["away_win"] * 100,
        )
        return rates
