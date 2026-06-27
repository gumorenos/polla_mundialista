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

        # --- Suspension penalties ---
        home_susp = self._count_active_suspensions(home_team_id)
        away_susp = self._count_active_suspensions(away_team_id)

        if home_susp > 0:
            capped = min(home_susp, _MAX_INJURY_PENALTY)
            lam_h *= (1.0 - settings.SUSPENSION_ATTACK_PENALTY) ** capped
            lam_a *= (1.0 + settings.SUSPENSION_DEFENSE_PENALTY) ** capped
            used.append(f"suspension_penalty_home(n={home_susp})")
            logger.info(
                "PoissonContext: home team %s has %d suspended — attack penalty %.0f%%",
                home_team_id, home_susp, settings.SUSPENSION_ATTACK_PENALTY * capped * 100,
            )
        if away_susp > 0:
            capped = min(away_susp, _MAX_INJURY_PENALTY)
            lam_a *= (1.0 - settings.SUSPENSION_ATTACK_PENALTY) ** capped
            lam_h *= (1.0 + settings.SUSPENSION_DEFENSE_PENALTY) ** capped
            used.append(f"suspension_penalty_away(n={away_susp})")

        # --- Altitude and host-team advantage ---
        venue_id = ctx.get("venue_id") or (
            self._get_venue_id(home_team_id, away_team_id) if not fixture_id else None
        )
        if venue_id is None and fixture_id:
            venue_id = self._get_venue_id_by_fixture(fixture_id)

        if venue_id:
            from app.services.features.altitude_adjustment import get_altitude_adjustment
            adj_h = get_altitude_adjustment(home_team_id, venue_id, self._conn)
            adj_a = get_altitude_adjustment(away_team_id, venue_id, self._conn)
            if adj_h and adj_h["combined"] != 1.0:
                lam_h *= adj_h["combined"]
                used.append(
                    f"altitude_home(venue={venue_id},alt={int(adj_h['altitude_m'])}m,"
                    f"adj={adj_h['combined']:.3f})"
                )
            if adj_a and adj_a["combined"] != 1.0:
                lam_a *= adj_a["combined"]
                used.append(
                    f"altitude_away(venue={venue_id},alt={int(adj_a['altitude_m'])}m,"
                    f"adj={adj_a['combined']:.3f})"
                )
        else:
            missing.append("venue_id")

        # Clamp lambdas to a reasonable range
        lam_h = max(0.1, lam_h)
        lam_a = max(0.1, lam_a)

        result = self._build_prediction(lam_h, lam_a, used, missing)
        if venue_id:
            result["venue_id"] = venue_id
        return result

    # ------------------------------------------------------------------
    # xG-based strength override
    # ------------------------------------------------------------------

    def _get_strength(self, team_id: str) -> tuple[float, float, bool]:
        """Return (attack, defense, found) preferring xG over raw goals.

        Priority:
          1. calculate_xg_strengths() — StatsBomb xG (most predictive)
          2. team_strengths table — goals-based with decay
          3. defaults (1.0, 1.0)
        """
        try:
            from app.services.features.strengths import calculate_xg_strengths
            xg = calculate_xg_strengths(team_id, self._conn)
            if xg is not None:
                logger.debug(
                    "PoissonContext: %s using xG strengths (n=%d) atk=%.3f def=%.3f",
                    team_id, xg["sample_size"], xg["attack_xg"], xg["defense_xg"],
                )
                return xg["attack_xg"], xg["defense_xg"], True
        except Exception as exc:
            logger.debug("PoissonContext: xG strength lookup failed for %s: %s", team_id, exc)

        # Fallback to goals-based strengths from team_strengths table
        return super()._get_strength(team_id)

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

    def _get_venue_id(self, home_team_id: str, away_team_id: str) -> str | None:
        """Return venue_id for the next scheduled fixture between the two teams."""
        try:
            row = self._conn.execute(
                """
                SELECT venue_id FROM fixtures
                WHERE home_team_id = ? AND away_team_id = ?
                  AND venue_id IS NOT NULL
                ORDER BY match_date ASC
                LIMIT 1
                """,
                (home_team_id, away_team_id),
            ).fetchone()
        except Exception as exc:
            logger.debug("PoissonContext: venue lookup failed for %s/%s: %s",
                         home_team_id, away_team_id, exc)
            return None
        return row["venue_id"] if row else None

    def _get_venue_id_by_fixture(self, fixture_id: str) -> str | None:
        """Return venue_id for a specific fixture."""
        try:
            row = self._conn.execute(
                "SELECT venue_id FROM fixtures WHERE id = ?",
                (fixture_id,),
            ).fetchone()
        except Exception as exc:
            logger.debug("PoissonContext: venue lookup failed for fixture %s: %s",
                         fixture_id, exc)
            return None
        return row["venue_id"] if row else None

    def _count_active_suspensions(self, team_id: str) -> int:
        """Count players under FIFA WC suspension (2+ yellows or red card)."""
        try:
            yellow_row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM (
                    SELECT player_name
                    FROM player_bookings
                    WHERE team_id = ? AND competition = 'WC2026' AND card_type = 'YELLOW'
                    GROUP BY player_name
                    HAVING COUNT(*) >= 2
                )
                """,
                (team_id,),
            ).fetchone()
            red_row = self._conn.execute(
                """
                SELECT COUNT(DISTINCT player_name) AS n
                FROM player_bookings
                WHERE team_id = ? AND competition = 'WC2026'
                  AND card_type IN ('RED', 'YELLOW_RED')
                """,
                (team_id,),
            ).fetchone()
        except Exception as exc:
            logger.warning(
                "PoissonContext: DB error counting suspensions for %s: %s", team_id, exc
            )
            return 0
        yellows = int(yellow_row["n"]) if yellow_row else 0
        reds = int(red_row["n"]) if red_row else 0
        return yellows + reds
