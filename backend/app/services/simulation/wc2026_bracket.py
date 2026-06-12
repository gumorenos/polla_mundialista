"""WC2026 bracket simulator — group stage + full knockout."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np

from app.services.prediction.base import PredictionModel
from app.services.prediction.match_engine import simulate_match
from app.services.simulation.constants import (
    GROUPS_2026,
    R32_BRACKET,
    ROUND_CHAMPION,
    ROUND_FINAL,
    ROUND_FOURTH,
    ROUND_GROUP_STAGE,
    ROUND_QF,
    ROUND_R16,
    ROUND_R32,
    ROUND_RUNNER_UP,
    ROUND_SF,
    ROUND_THIRD,
)

logger = logging.getLogger(__name__)


class WC2026Bracket:
    """Simulates one full World Cup 2026 tournament."""

    def __init__(
        self,
        model: PredictionModel,
        teams_data: dict[str, list[str]],
        rng: np.random.Generator,
        penalty_home_prob: float = 0.5,
    ) -> None:
        """
        Args:
            model: prediction model (already initialized with DB connection).
            teams_data: {group_letter: [team_id, ...]} — 12 groups × 4 teams.
            rng: seeded numpy Generator for full reproducibility.
            penalty_home_prob: P(home team wins penalty shootout).
        """
        self.model = model
        self.groups = teams_data
        self.rng = rng
        self.penalty_home_prob = penalty_home_prob
        self.rounds_reached: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play_group_stage(self) -> dict[str, str]:
        """Simulate all 12 groups and return the 32 classified teams.

        Returns:
            classified: {"1A": team_id, "2B": team_id, "T1": team_id, ...}
        """
        classified: dict[str, str] = {}
        all_thirds: list[dict[str, Any]] = []

        for letter, team_ids in self.groups.items():
            standings = {
                tid: {"pts": 0, "gd": 0, "gf": 0} for tid in team_ids
            }
            # Round-robin: 4C2 = 6 matches
            for i, home_id in enumerate(team_ids):
                for j in range(i + 1, len(team_ids)):
                    away_id = team_ids[j]
                    pred = self.model.predict_match(home_id, away_id)
                    lam_h = max(0.1, pred["expected_home_goals"])
                    lam_a = max(0.1, pred["expected_away_goals"])
                    hg, ag = simulate_match(lam_h, lam_a, self.rng)
                    _update_standings(standings, home_id, away_id, hg, ag)

            ranked = _rank_group(standings, self.rng)

            # 4th place → eliminated
            self.rounds_reached[ranked[3][0]] = ROUND_GROUP_STAGE

            # 1st and 2nd → straight through
            classified[f"1{letter}"] = ranked[0][0]
            classified[f"2{letter}"] = ranked[1][0]

            # 3rd → candidate for best-third selection
            t3_id, t3_stats = ranked[2]
            all_thirds.append({
                "team_id": t3_id,
                "pts": t3_stats["pts"],
                "gd":  t3_stats["gd"],
                "gf":  t3_stats["gf"],
            })

        # Rank all 12 third-place teams; best 8 qualify
        thirds_sorted = sorted(
            all_thirds,
            key=lambda x: (x["pts"], x["gd"], x["gf"], self.rng.random()),
            reverse=True,
        )
        for rank, t in enumerate(thirds_sorted):
            if rank < 8:
                classified[f"T{rank + 1}"] = t["team_id"]
            else:
                self.rounds_reached[t["team_id"]] = ROUND_GROUP_STAGE

        return classified

    def play_knockout(self, classified: dict[str, str]) -> dict[str, Any]:
        """Simulate the full knockout bracket from R32 to Final.

        Args:
            classified: mapping of bracket positions to team IDs.

        Returns:
            dict with champion, runner_up, third, fourth, rounds_reached.
        """
        # --- Round of 32 (octavos) ---
        r32_winners = self._play_round(classified, R32_BRACKET, ROUND_R32)

        # --- Round of 16 (cuartos) ---
        r16_pairings = _adjacent_pairs(r32_winners)
        r16_winners = self._play_round_direct(r16_pairings, ROUND_R16)

        # --- Quarterfinals (semis) ---
        qf_pairings = _adjacent_pairs(r16_winners)
        qf_winners, qf_losers = self._play_round_with_losers(qf_pairings, ROUND_QF)

        # --- Semifinals ---
        sf_pairings = _adjacent_pairs(qf_winners)
        sf_winners, sf_losers = self._play_round_with_losers(sf_pairings, ROUND_SF)

        # --- Final ---
        champion = runner_up = third = fourth = None
        if len(sf_winners) >= 2:
            champion = self._knockout_match(sf_winners[0], sf_winners[1])
            runner_up = sf_winners[1] if champion == sf_winners[0] else sf_winners[0]
            self.rounds_reached[champion]   = ROUND_CHAMPION
            self.rounds_reached[runner_up]  = ROUND_RUNNER_UP
        elif sf_winners:
            champion = sf_winners[0]
            self.rounds_reached[champion] = ROUND_CHAMPION

        # --- Third-place play-off ---
        if len(sf_losers) >= 2:
            third  = self._knockout_match(sf_losers[0], sf_losers[1])
            fourth = sf_losers[1] if third == sf_losers[0] else sf_losers[0]
            self.rounds_reached[third]  = ROUND_THIRD
            self.rounds_reached[fourth] = ROUND_FOURTH

        return {
            "champion":      champion,
            "runner_up":     runner_up,
            "third":         third,
            "fourth":        fourth,
            "rounds_reached": self.rounds_reached,
        }

    def run(self) -> dict[str, Any]:
        """Run full tournament (group stage + knockout) and return results."""
        classified = self.play_group_stage()
        return self.play_knockout(classified)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _play_round(
        self,
        classified: dict[str, str],
        pairings: list[tuple[str, str]],
        loser_label: str,
    ) -> list[str]:
        """Play all matches in a round from position labels, return winners list."""
        winners: list[str] = []
        for pos_h, pos_a in pairings:
            home_id = classified.get(pos_h)
            away_id = classified.get(pos_a)
            if home_id is None or away_id is None:
                logger.warning("Missing team for positions %s / %s", pos_h, pos_a)
                continue
            winner = self._knockout_match(home_id, away_id)
            loser  = away_id if winner == home_id else home_id
            self.rounds_reached[loser] = loser_label
            winners.append(winner)
        return winners

    def _play_round_direct(
        self,
        pairings: list[tuple[str, str]],
        loser_label: str,
    ) -> list[str]:
        winners: list[str] = []
        for home_id, away_id in pairings:
            winner = self._knockout_match(home_id, away_id)
            loser  = away_id if winner == home_id else home_id
            self.rounds_reached[loser] = loser_label
            winners.append(winner)
        return winners

    def _play_round_with_losers(
        self,
        pairings: list[tuple[str, str]],
        loser_label: str,
    ) -> tuple[list[str], list[str]]:
        winners: list[str] = []
        losers:  list[str] = []
        for home_id, away_id in pairings:
            winner = self._knockout_match(home_id, away_id)
            loser  = away_id if winner == home_id else home_id
            self.rounds_reached[loser] = loser_label
            winners.append(winner)
            losers.append(loser)
        return winners, losers

    def _knockout_match(self, home_id: str, away_id: str) -> str:
        """Simulate a knockout match; penalty shootout if tied after 90 min."""
        pred = self.model.predict_match(home_id, away_id)
        lam_h = max(0.1, pred["expected_home_goals"])
        lam_a = max(0.1, pred["expected_away_goals"])
        hg, ag = simulate_match(lam_h, lam_a, self.rng)
        if hg > ag:
            return home_id
        if ag > hg:
            return away_id
        # Penalties
        return home_id if self.rng.random() < self.penalty_home_prob else away_id


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _update_standings(
    standings: dict[str, dict],
    home_id: str,
    away_id: str,
    hg: int,
    ag: int,
) -> None:
    s_h = standings[home_id]
    s_a = standings[away_id]
    s_h["gf"] += hg;  s_h["gd"] += hg - ag
    s_a["gf"] += ag;  s_a["gd"] += ag - hg
    if hg > ag:
        s_h["pts"] += 3
    elif hg == ag:
        s_h["pts"] += 1
        s_a["pts"] += 1
    else:
        s_a["pts"] += 3


def _rank_group(
    standings: dict[str, dict],
    rng: np.random.Generator,
) -> list[tuple[str, dict]]:
    """Sort group teams: pts → gd → gf → random tiebreaker."""
    return sorted(
        standings.items(),
        key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"], rng.random()),
        reverse=True,
    )


def _adjacent_pairs(teams: list[str]) -> list[tuple[str, str]]:
    """Pair consecutive elements: [A,B,C,D] → [(A,B), (C,D)]."""
    return [(teams[i], teams[i + 1]) for i in range(0, len(teams) - 1, 2)]
