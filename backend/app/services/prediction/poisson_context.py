"""Poisson model with contextual adjustments.

Inherits from PoissonModel and applies, before lambda computation:
  1. team_context_adjustments from DB (per fixture)
  2. Injury penalties from availability_claims
  3. Venue/stage information passed via context dict
"""

from __future__ import annotations

import logging
import sqlite3

from app.core.config import settings
from app.services.prediction.poisson_model import PoissonModel

logger = logging.getLogger(__name__)

_MAX_INJURY_PENALTY = 3  # cap at 3 injured key players to avoid extreme penalties


class PoissonContextModel(PoissonModel):
    name = "poisson_context"
    version = "1.0"

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
        fixture_id: str | None = ctx.get("fixture_id")

        lam_h, lam_a, used, missing = self._compute_lambdas(
            home_team_id, away_team_id, is_neutral
        )

        # --- DB context adjustments (per fixture) ---
        if fixture_id:
            adj_h = self._get_context_adjustment(home_team_id, fixture_id)
            adj_a = self._get_context_adjustment(away_team_id, fixture_id)
            if adj_h:
                lam_h *= adj_h.get("attack_factor",  1.0)
                lam_a *= adj_h.get("defense_factor", 1.0)
                used.append("context_adj_home")
            if adj_a:
                lam_a *= adj_a.get("attack_factor",  1.0)
                lam_h *= adj_a.get("defense_factor", 1.0)
                used.append("context_adj_away")
        else:
            missing.append("fixture_id_for_context_adj")

        # --- Injury penalties ---
        home_injuries = self._count_active_injuries(home_team_id)
        away_injuries = self._count_active_injuries(away_team_id)

        if home_injuries > 0:
            capped = min(home_injuries, _MAX_INJURY_PENALTY)
            penalty = settings.INJURY_ATTACK_PENALTY * capped
            lam_h *= 1.0 - penalty
            used.append(f"injury_penalty_home(n={home_injuries})")
            logger.info(
                "PoissonContext: home team %s has %d injured — lam_h reduced by %.0f%%",
                home_team_id, home_injuries, penalty * 100,
            )
        else:
            missing.append("injury_data_home")

        if away_injuries > 0:
            capped = min(away_injuries, _MAX_INJURY_PENALTY)
            penalty = settings.INJURY_ATTACK_PENALTY * capped
            lam_a *= 1.0 - penalty
            used.append(f"injury_penalty_away(n={away_injuries})")
        else:
            missing.append("injury_data_away")

        # Clamp lambdas to a reasonable range
        lam_h = max(0.1, lam_h)
        lam_a = max(0.1, lam_a)

        return self._build_prediction(lam_h, lam_a, used, missing)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_context_adjustment(
        self, team_id: str, fixture_id: str
    ) -> dict | None:
        try:
            row = self._conn.execute(
                """
                SELECT attack_factor, defense_factor
                FROM team_context_adjustments
                WHERE team_id = ? AND fixture_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (team_id, fixture_id),
            ).fetchone()
        except Exception as exc:
            logger.warning(
                "PoissonContext: DB error fetching context adj for %s/%s: %s",
                team_id, fixture_id, exc,
            )
            return None
        return dict(row) if row else None

    def _count_active_injuries(self, team_id: str) -> int:
        """Count active key-player injuries within NEWS_DAYS_LOOKBACK days."""
        lookback = settings.NEWS_DAYS_LOOKBACK
        try:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM availability_claims
                WHERE team_id = ?
                  AND status IN ('injured', 'doubtful')
                  AND affects_prediction = 1
                  AND datetime(observed_at) >= datetime('now', ?)
                """,
                (team_id, f"-{lookback} days"),
            ).fetchone()
        except Exception as exc:
            logger.warning(
                "PoissonContext: DB error fetching injuries for %s: %s", team_id, exc
            )
            return 0
        return int(row["n"]) if row else 0
