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
from app.services.prediction.poisson_model import (
    PoissonModel,
    _elo_attack_defense_prior,
    _elo_prior_weight,
)

logger = logging.getLogger(__name__)

_MAX_INJURY_PENALTY = 3  # cap at 3 injured key players to avoid extreme penalties


class PoissonContextModel(PoissonModel):
    name = "poisson_context"
    version = "1.0"

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__(conn)  # hereda _strength_map de PoissonModel
        self._xg_map:         dict[str, tuple[float, float, int]] = self._load_xg_map()
        self._injury_map:     dict[str, int]                 = self._load_injury_map()
        self._suspension_map: dict[str, int]                 = self._load_suspension_map()
        self._venue_map:      dict[tuple[str, str], str]     = self._load_venue_map()
        self._altitude_map:   dict[tuple[str, str], dict]    = self._load_altitude_map()
        logger.debug(
            "PoissonContextModel: preloaded xG=%d teams, injuries=%d, "
            "suspensions=%d, venues=%d, altitude=%d pairs",
            len(self._xg_map), len(self._injury_map),
            len(self._suspension_map), len(self._venue_map), len(self._altitude_map),
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
            adj_h = self._altitude_map.get((home_team_id, venue_id))
            adj_a = self._altitude_map.get((away_team_id, venue_id))
            if adj_h and adj_h.get("combined", 1.0) != 1.0:
                lam_h *= adj_h["combined"]
                used.append(
                    f"altitude_home(venue={venue_id},alt={int(adj_h['altitude_m'])}m,"
                    f"adj={adj_h['combined']:.3f})"
                )
            if adj_a and adj_a.get("combined", 1.0) != 1.0:
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
        """Return (attack, defense, found) preferring preloaded xG over
        goals-based strength. The xG sample (StatsBomb historical matches)
        can be just as small/noisy as the goals-based one — e.g. a team
        with only 3-4 World Cup matches on record — so it gets the same
        ELO-prior blend treatment as the base model instead of being used
        as a raw, unblended override."""
        xg = self._xg_map.get(team_id)
        if xg is not None:
            atk_xg, def_xg, n = xg
            elo = self._elo_map.get(team_id)
            if elo is None or not settings.POISSON_ELO_PRIOR_ENABLED:
                return atk_xg, def_xg, True
            w = _elo_prior_weight(n)
            elo_attack, elo_defense = _elo_attack_defense_prior(elo)
            return (1 - w) * atk_xg + w * elo_attack, (1 - w) * def_xg + w * elo_defense, True
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
        return self._injury_map.get(team_id, 0)

    def _count_active_suspensions(self, team_id: str) -> int:
        return self._suspension_map.get(team_id, 0)

    def _get_venue_id(self, home_team_id: str, away_team_id: str) -> str | None:
        return self._venue_map.get((home_team_id, away_team_id))

    def _get_venue_id_by_fixture(self, fixture_id: str) -> str | None:
        """Return venue_id for a specific fixture (used for real fixtures, not MC)."""
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

    # ------------------------------------------------------------------
    # Preload methods — called once in __init__
    # ------------------------------------------------------------------

    def _load_xg_map(self) -> dict[str, tuple[float, float, int]]:
        """Load xG-based strengths for all teams with sufficient StatsBomb
        data. Keeps the match count (n) so _get_strength can blend with the
        ELO prior for teams whose xG sample is itself small."""
        try:
            g = self._conn.execute(
                """SELECT AVG(xg) AS avg_xg, AVG(xg_conceded) AS avg_xgc
                   FROM sb_match_stats WHERE xg > 0 OR xg_conceded > 0"""
            ).fetchone()
            global_avg_xg  = float(g["avg_xg"]  or 1.0) if g else 1.0
            global_avg_xgc = float(g["avg_xgc"] or 1.0) if g else 1.0
            if global_avg_xg <= 0:  global_avg_xg  = 1.0
            if global_avg_xgc <= 0: global_avg_xgc = 1.0

            rows = self._conn.execute(
                """
                SELECT team_id,
                       AVG(xg)          AS avg_xg,
                       AVG(xg_conceded) AS avg_xgc,
                       COUNT(*)         AS n
                FROM sb_match_stats
                GROUP BY team_id
                HAVING COUNT(*) >= 3
                """
            ).fetchall()

            from app.services.features.strengths import _STRENGTH_MIN, _STRENGTH_MAX
            result: dict[str, tuple[float, float, int]] = {}
            for r in rows:
                atk = max(_STRENGTH_MIN, min(_STRENGTH_MAX,
                          float(r["avg_xg"])  / global_avg_xg))
                def_ = max(_STRENGTH_MIN, min(_STRENGTH_MAX,
                          float(r["avg_xgc"]) / global_avg_xgc))
                result[r["team_id"]] = (atk, def_, int(r["n"]))
            return result
        except Exception as exc:
            logger.warning("PoissonContext: failed to preload xG map: %s", exc)
            return {}

    def _load_injury_map(self) -> dict[str, int]:
        """Load active injury counts per team."""
        lookback = settings.NEWS_DAYS_LOOKBACK
        try:
            rows = self._conn.execute(
                f"""
                SELECT team_id, COUNT(*) AS n
                FROM availability_claims
                WHERE status IN ('injured', 'doubtful')
                  AND affects_prediction = 1
                  AND datetime(observed_at) >= datetime('now', '-{lookback} days')
                GROUP BY team_id
                """
            ).fetchall()
            return {r["team_id"]: int(r["n"]) for r in rows}
        except Exception as exc:
            logger.warning("PoissonContext: failed to preload injury map: %s", exc)
            return {}

    def _load_suspension_map(self) -> dict[str, int]:
        """Load active suspension counts per team (yellows×2 + reds)."""
        try:
            yellow_rows = self._conn.execute(
                """
                SELECT team_id, COUNT(*) AS n FROM (
                    SELECT team_id, player_name
                    FROM player_bookings
                    WHERE competition = 'WC2026' AND card_type = 'YELLOW'
                    GROUP BY team_id, player_name HAVING COUNT(*) >= 2
                ) GROUP BY team_id
                """
            ).fetchall()
            red_rows = self._conn.execute(
                """
                SELECT team_id, COUNT(DISTINCT player_name) AS n
                FROM player_bookings
                WHERE competition = 'WC2026' AND card_type IN ('RED', 'YELLOW_RED')
                GROUP BY team_id
                """
            ).fetchall()
            result: dict[str, int] = {}
            for r in yellow_rows:
                result[r["team_id"]] = result.get(r["team_id"], 0) + int(r["n"])
            for r in red_rows:
                result[r["team_id"]] = result.get(r["team_id"], 0) + int(r["n"])
            return result
        except Exception as exc:
            logger.warning("PoissonContext: failed to preload suspension map: %s", exc)
            return {}

    def _load_venue_map(self) -> dict[tuple[str, str], str]:
        """Load venue_id for all scheduled fixtures."""
        try:
            rows = self._conn.execute(
                """SELECT home_team_id, away_team_id, venue_id
                   FROM fixtures WHERE venue_id IS NOT NULL"""
            ).fetchall()
            return {
                (r["home_team_id"], r["away_team_id"]): r["venue_id"]
                for r in rows
            }
        except Exception as exc:
            logger.warning("PoissonContext: failed to preload venue map: %s", exc)
            return {}

    def _load_altitude_map(self) -> dict[tuple[str, str], dict]:
        """Pre-compute altitude adjustments for all (team, venue) combinations."""
        try:
            from app.services.features.altitude_adjustment import get_altitude_adjustment
            venue_ids = set(self._venue_map.values())
            team_ids  = set(self._strength_map.keys())
            result: dict[tuple[str, str], dict] = {}
            for venue_id in venue_ids:
                for team_id in team_ids:
                    adj = get_altitude_adjustment(team_id, venue_id, self._conn)
                    if adj and adj.get("combined", 1.0) != 1.0:
                        result[(team_id, venue_id)] = adj
            return result
        except Exception as exc:
            logger.warning("PoissonContext: failed to preload altitude map: %s", exc)
            return {}
