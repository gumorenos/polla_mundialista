"""Live bracket simulator — Monte Carlo from actual R32 qualifiers,
respecting already-played knockout results.

Unlike WC2026Bracket (which simulates group stage + knockout from scratch
for the full per-model Monte Carlo), this starts from the real 32
qualifiers in wc2026_standings and any knockout matches already played in
`results`, and only runs Monte Carlo on matches that haven't happened yet.

Real knockout matches are matched by team-pair (frozenset of the two real
team ids) rather than by a fixed bracket-position index: fixtures.csv only
holds 'TBD' placeholders for knockout rounds, and results.stage is not
populated by the API-Football ingestion, so team identity is the only
reliable join key once the R32 draw is known.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict

import numpy as np

from app.core.config import settings
from app.services.prediction.base import PredictionModel
from app.services.prediction.match_engine import simulate_match
from app.services.simulation.constants import (
    R32_BRACKET,
    ROUND_CHAMPION,
    ROUND_FINAL,
    ROUND_QF,
    ROUND_R16,
    ROUND_R32,
    ROUND_RUNNER_UP,
    ROUND_SF,
)

logger = logging.getLogger(__name__)

_BRACKET_ITERATIONS = 10_000  # menos que el MC completo (30k) — solo bracket restante

# Round progression used to turn "round eliminated in" into cumulative
# "reached round X" probabilities.
_ROUND_ORDER = [ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF, ROUND_FINAL, ROUND_CHAMPION]
_ROUND_RANK = {name: i for i, name in enumerate(_ROUND_ORDER)}

# A team eliminated/finishing with this label achieved this rank (inclusive).
_ACHIEVED_RANK = {
    ROUND_R32:       _ROUND_RANK[ROUND_R32],
    ROUND_R16:       _ROUND_RANK[ROUND_R16],
    ROUND_QF:        _ROUND_RANK[ROUND_QF],
    ROUND_SF:        _ROUND_RANK[ROUND_SF],
    ROUND_RUNNER_UP: _ROUND_RANK[ROUND_FINAL],
    ROUND_CHAMPION:  _ROUND_RANK[ROUND_CHAMPION],
}


def load_r32_qualifiers(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {bracket_position: team_id} for the 32 teams that qualified
    to the Round of 32, based on real wc2026_standings data.

    All 12 groups must be finished (positions 1 and 2 marked 'qualified')
    before the 32 can be determined — otherwise returns {} so the caller
    can fall back to the fully-simulated WC2026Bracket.
    """
    rows = conn.execute(
        "SELECT team_id, group_id, position, points, goals_for, goals_against, status "
        "FROM wc2026_standings ORDER BY group_id, position"
    ).fetchall()
    if not rows:
        return {}

    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        groups[r["group_id"]].append(r)

    if len(groups) < 12:
        return {}

    qualifiers: dict[str, str] = {}
    thirds: list[dict] = []
    for gid, grows in groups.items():
        by_pos = {r["position"]: r for r in grows}
        first, second = by_pos.get(1), by_pos.get(2)
        if first is None or second is None:
            return {}
        if first["status"] != "qualified" or second["status"] != "qualified":
            return {}  # group not finished yet
        qualifiers[f"1{gid}"] = first["team_id"]
        qualifiers[f"2{gid}"] = second["team_id"]

        third = by_pos.get(3)
        if third is not None:
            thirds.append({
                "team_id": third["team_id"],
                "pts": third["points"],
                "gd":  third["goals_for"] - third["goals_against"],
                "gf":  third["goals_for"],
            })

    thirds_sorted = sorted(
        thirds, key=lambda x: (x["pts"], x["gd"], x["gf"]), reverse=True
    )
    for i, t in enumerate(thirds_sorted[:8]):
        qualifiers[f"T{i + 1}"] = t["team_id"]

    if len(qualifiers) < 32:
        logger.warning(
            "load_r32_qualifiers: solo %d/32 posiciones resueltas — abortando",
            len(qualifiers),
        )
        return {}

    return qualifiers


def load_knockout_winners(
    conn: sqlite3.Connection, qualifier_ids: set[str]
) -> dict[frozenset[str], str]:
    """Return {frozenset({team_a, team_b}): winner_team_id} for knockout
    matches already played between two real R32 qualifiers.

    Matches tied on goals (likely decided by penalties, which `results`
    does not record) are skipped — treated as not-yet-resolved.
    """
    if not qualifier_ids:
        return {}

    ids = list(qualifier_ids)
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT home_team_id, away_team_id, home_goals, away_goals
        FROM results
        WHERE is_wc = 1
          AND home_team_id IN ({placeholders})
          AND away_team_id IN ({placeholders})
          AND home_goals IS NOT NULL AND away_goals IS NOT NULL
        """,
        ids + ids,
    ).fetchall()

    winners: dict[frozenset[str], str] = {}
    for r in rows:
        h, a, hg, ag = r["home_team_id"], r["away_team_id"], r["home_goals"], r["away_goals"]
        if hg == ag:
            logger.warning(
                "load_knockout_winners: %s vs %s empatado en goles (¿penales?) — "
                "no se puede determinar ganador, se trata como pendiente", h, a,
            )
            continue
        winners[frozenset((h, a))] = h if hg > ag else a
    return winners


class BracketSimulator:
    """Simulate the remaining WC2026 knockout bracket from real data."""

    def __init__(
        self,
        model: PredictionModel,
        r32_qualifiers: dict[str, str],
        winners_by_pair: dict[frozenset[str], str],
        rng: np.random.Generator,
        penalty_home_prob: float = 0.5,
    ) -> None:
        self.model = model
        self.r32 = r32_qualifiers
        self.played = winners_by_pair
        self.rng = rng
        self.penalty_home_prob = penalty_home_prob

    def simulate_once(self) -> dict[str, str]:
        """Run one full bracket simulation from current real state.

        Returns {team_id: round_reached} for this single run, where
        round_reached is the round in which the team was eliminated, or
        ROUND_RUNNER_UP / ROUND_CHAMPION for the finalists.
        """
        rounds_reached: dict[str, str] = {}

        slots: list[str | None] = []
        for pos_h, pos_a in R32_BRACKET:
            slots.append(self.r32.get(pos_h))
            slots.append(self.r32.get(pos_a))

        for round_name in (ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF, ROUND_FINAL):
            next_slots: list[str | None] = []
            loser_label = ROUND_RUNNER_UP if round_name == ROUND_FINAL else round_name
            for i in range(0, len(slots), 2):
                h = slots[i]
                a = slots[i + 1] if i + 1 < len(slots) else None
                if h is None or a is None:
                    next_slots.append(None)
                    continue
                pair = frozenset((h, a))
                winner = self.played.get(pair) or self._play(h, a)
                loser = a if winner == h else h
                rounds_reached[loser] = loser_label
                next_slots.append(winner)
            slots = next_slots

        if slots and slots[0] is not None:
            rounds_reached[slots[0]] = ROUND_CHAMPION

        return rounds_reached

    def _play(self, home_id: str, away_id: str) -> str:
        pred = self.model.predict_match(home_id, away_id)
        lam_h = max(0.1, pred["expected_home_goals"])
        lam_a = max(0.1, pred["expected_away_goals"])
        hg, ag = simulate_match(lam_h, lam_a, self.rng)
        if hg > ag:
            return home_id
        if ag > hg:
            return away_id
        return home_id if self.rng.random() < self.penalty_home_prob else away_id


def _resolve_pending_matches(
    model: PredictionModel,
    r32: dict[str, str],
    winners_by_pair: dict[frozenset[str], str],
) -> tuple[dict[str, str], dict[str, tuple[str, str, float]]]:
    """Deterministically walk the real bracket (no Monte Carlo).

    Returns:
        eliminated: {team_id: round_name} — real elimination round so far.
        pending: {team_id: (round_name, opponent_id, match_win_prob)} for
            the next live match of each team whose opponent is already
            known but hasn't played yet.
    """
    eliminated: dict[str, str] = {}
    pending: dict[str, tuple[str, str, float]] = {}

    slots: list[str | None] = []
    for pos_h, pos_a in R32_BRACKET:
        slots.append(r32.get(pos_h))
        slots.append(r32.get(pos_a))

    for round_name in (ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF, ROUND_FINAL):
        next_slots: list[str | None] = []
        loser_label = ROUND_RUNNER_UP if round_name == ROUND_FINAL else round_name
        for i in range(0, len(slots), 2):
            h = slots[i]
            a = slots[i + 1] if i + 1 < len(slots) else None
            if h is None or a is None:
                next_slots.append(None)
                continue
            pair = frozenset((h, a))
            winner = winners_by_pair.get(pair)
            if winner is not None:
                loser = a if winner == h else h
                eliminated[loser] = loser_label
                next_slots.append(winner)
            else:
                pred = model.predict_match(h, a)
                h_win = float(pred["home_win"]) + 0.5 * float(pred["draw"])
                a_win = float(pred["away_win"]) + 0.5 * float(pred["draw"])
                pending[h] = (round_name, a, round(h_win, 4))
                pending[a] = (round_name, h, round(a_win, 4))
                next_slots.append(None)
        slots = next_slots

    return eliminated, pending


def _try_refresh_standings(conn: sqlite3.Connection) -> str | None:
    """Best-effort refresh of wc2026_standings from whatever provider is
    available, so a bracket run doesn't give up just because standings are
    stale. Returns an ISO timestamp if anything was refreshed, else None."""
    from datetime import datetime, timezone

    refreshed = False
    try:
        from app.services.ingestion.api_football import fetch_wc2026_standings
        fetch_wc2026_standings(conn)
        refreshed = True
    except Exception as exc:
        logger.debug("_try_refresh_standings: API-Football fetch failed: %s", exc)

    try:
        from app.services.ingestion.standings_calculator import calculate_standings_from_results
        calculate_standings_from_results(conn)
        refreshed = True
    except Exception as exc:
        logger.debug("_try_refresh_standings: local calculator failed: %s", exc)

    return datetime.now(timezone.utc).isoformat() if refreshed else None


_NO_R32_MESSAGE = (
    "No hay 32 clasificados definidos todavía. Se actualizó standings, "
    "pero la fase de grupos sigue incompleta."
)


def run_bracket_simulation(
    conn: sqlite3.Connection,
    model_name: str,
    n_iterations: int = _BRACKET_ITERATIONS,
    source: str = "manual",
) -> dict[str, Any]:
    """Run Monte Carlo on the live bracket and persist a historical
    bracket_run + bracket_simulation_results (see db/repositories/bracket.py).

    If the R32 draw isn't resolved yet, makes one best-effort attempt to
    refresh wc2026_standings before giving up — never fails silently.

    Returns:
        {
          "run_id": str,
          "status": "completed" | "no_r32",
          "message": str | None,
          "teams": {team_id: {round_name: advance_prob, ...}},  # {} if no_r32
        }
    """
    from app.db.repositories.bracket import BracketRepository
    from app.services.simulation.monte_carlo import _init_model

    repo = BracketRepository(conn)
    run_id = repo.create_run(model_name, n_iterations, source=source)
    conn.commit()

    r32 = load_r32_qualifiers(conn)
    r32_source = "wc2026_standings"
    r32_fetched_at: str | None = None

    if not r32:
        logger.info(
            "run_bracket_simulation: %s — R32 no resuelto, intentando refrescar standings",
            model_name,
        )
        r32_fetched_at = _try_refresh_standings(conn)
        conn.commit()
        r32 = load_r32_qualifiers(conn)

    if not r32:
        repo.finish_run(
            run_id, status="no_r32", error_message=_NO_R32_MESSAGE,
            r32_source=r32_source, r32_fetched_at=r32_fetched_at,
        )
        conn.commit()
        logger.warning("run_bracket_simulation: %s — %s", model_name, _NO_R32_MESSAGE)
        return {"run_id": run_id, "status": "no_r32", "message": _NO_R32_MESSAGE, "teams": {}}

    qualifier_ids = set(r32.values())
    winners_by_pair = load_knockout_winners(conn, qualifier_ids)
    model = _init_model(model_name, conn)
    rng = np.random.default_rng(settings.MONTECARLO_SEED)

    achieved_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for _ in range(n_iterations):
        sim = BracketSimulator(model, r32, winners_by_pair, rng)
        result = sim.simulate_once()
        for team_id, round_name in result.items():
            rank = _ACHIEVED_RANK[round_name]
            achieved_counts[team_id][rank] += 1

    eliminated, pending = _resolve_pending_matches(model, r32, winners_by_pair)

    history_rows: list[tuple] = []
    summary: dict[str, dict] = {}
    for team_id in qualifier_ids:
        counts = achieved_counts.get(team_id, {})
        team_summary: dict[str, float] = {}
        for round_name in _ROUND_ORDER:
            rank = _ROUND_RANK[round_name]
            reached = sum(c for r, c in counts.items() if r >= rank)
            advance_prob = reached / n_iterations
            team_summary[round_name] = advance_prob

            opponent_id: str | None = None
            match_win_prob: float | None = None
            if team_id in pending and pending[team_id][0] == round_name:
                _, opponent_id, match_win_prob = pending[team_id]

            is_eliminated = 1 if eliminated.get(team_id) == round_name else 0

            history_rows.append((
                run_id, model_name, round_name, team_id, advance_prob,
                opponent_id, match_win_prob, is_eliminated,
            ))
        summary[team_id] = team_summary

    repo.insert_results(history_rows)
    repo.finish_run(run_id, status="completed", r32_source=r32_source, r32_fetched_at=r32_fetched_at)
    conn.commit()

    logger.info(
        "run_bracket_simulation: %s — run_id=%s %d equipos, %d iteraciones persistidas",
        model_name, run_id, len(summary), n_iterations,
    )
    return {"run_id": run_id, "status": "completed", "message": None, "teams": summary}


_NO_RUN_YET_MESSAGE = "No se ha corrido ninguna simulación de bracket para este modelo todavía."


def get_latest_bracket_view(conn: sqlite3.Connection, model_name: str) -> dict:
    """Build the 'latest bracket' response shared by internal and public
    endpoints: {model, run_id, status, rounds, computed_at, message, meta}.

    status is one of:
      "completed" — a finished run exists, rounds/computed_at are populated.
      "no_r32"    — the most recent attempt found no R32 draw yet.
      None        — no bracket run has ever been attempted for this model.
    """
    from app.db.repositories.bracket import BracketRepository

    repo = BracketRepository(conn)
    run = repo.get_latest_completed_run(model_name)

    if run is None:
        latest_any = repo.get_latest_run(model_name)
        if latest_any is not None:
            return {
                "model": model_name,
                "run_id": None,
                "status": latest_any["status"],
                "rounds": {},
                "computed_at": None,
                "message": latest_any.get("error_message") or _NO_R32_MESSAGE,
                "meta": {
                    "iterations": latest_any["iterations"],
                    "r32_source": latest_any["r32_source"],
                    "r32_fetched_at": latest_any["r32_fetched_at"],
                },
            }
        return {
            "model": model_name, "run_id": None, "status": None,
            "rounds": {}, "computed_at": None, "message": _NO_RUN_YET_MESSAGE,
            "meta": {},
        }

    rounds: dict[str, list[dict]] = {}
    for r in repo.get_run_results(run["id"]):
        rounds.setdefault(r["round_name"], []).append({
            "team_id":        r["team_id"],
            "team_name":      r["team_name"],
            "advance_prob":   round(float(r["advance_prob"]), 4),
            "opponent_id":    r["opponent_id"],
            "opponent_name":  r["opponent_name"],
            "match_win_prob": round(float(r["match_win_prob"]), 4) if r["match_win_prob"] is not None else None,
            "is_eliminated":  bool(r["is_eliminated"]),
        })

    return {
        "model": model_name,
        "run_id": run["id"],
        "status": "completed",
        "rounds": rounds,
        "computed_at": run["finished_at"],
        "message": None,
        "meta": {
            "iterations": run["iterations"],
            "r32_source": run["r32_source"],
            "r32_fetched_at": run["r32_fetched_at"],
        },
    }
