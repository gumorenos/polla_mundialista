"""Monte Carlo WC2026 simulator.

Runs `iterations` full bracket simulations, accumulates per-team reach rates,
persists results via SimulationRepository, and returns the simulation run_id.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Callable

import numpy as np

from app.core.config import settings
from app.db.repositories.simulations import SimulationRepository
from app.services.simulation.constants import (
    GROUPS_2026,
    ROUND_CHAMPION,
    ROUND_FINAL,
    ROUND_FOURTH,
    ROUND_QF,
    ROUND_R16,
    ROUND_R32,
    ROUND_RUNNER_UP,
    ROUND_SF,
    ROUND_THIRD,
)
from app.services.simulation.wc2026_bracket import WC2026Bracket

logger = logging.getLogger(__name__)

# Map round labels → simulation_team_results column names
_ROUND_TO_COL: dict[str, str] = {
    ROUND_R32:       "reach_round_of_32",
    ROUND_R16:       "reach_round_of_16",
    ROUND_QF:        "reach_quarter_final",
    ROUND_SF:        "reach_semi_final",
    ROUND_FINAL:     "reach_final",
    ROUND_RUNNER_UP: "reach_final",
    ROUND_CHAMPION:  "reach_final",   # champion also reached final
    ROUND_THIRD:     "reach_semi_final",  # 3rd-place team also reached SF
    ROUND_FOURTH:    "reach_semi_final",
}


def run_monte_carlo(
    model_name: str,
    conn: sqlite3.Connection,
    iterations: int | None = None,
    seed: int | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> str:
    """Run Monte Carlo simulation and persist results.

    Args:
        model_name:         One of baseline / elo / poisson / poisson_context.
        conn:               Live SQLite connection (caller manages lifecycle).
        iterations:         Number of full-tournament simulations; defaults to
                            settings.MONTECARLO_ITERATIONS.
        seed:               RNG seed; defaults to settings.MONTECARLO_SEED.
        progress_callback:  Optional callable(float 0–1) invoked after each batch.

    Returns:
        simulation run_id (str).
    """
    n_iter  = iterations or settings.MONTECARLO_ITERATIONS
    rng_seed = seed if seed is not None else settings.MONTECARLO_SEED
    batch   = settings.SIMULATION_BATCH_SIZE

    model = _init_model(model_name, conn)
    groups = _load_groups(conn)
    all_team_ids = [tid for tids in groups.values() for tid in tids]

    repo = SimulationRepository(conn)
    run_id = repo.create_run({
        "model_name": model_name,
        "status":     "running",
        "iterations": n_iter,
        "seed":       rng_seed,
        "config_snapshot": json.dumps({
            "decay": settings.TIME_DECAY_FACTOR,
            "rho":   settings.DIXON_COLES_RHO,
        }),
    })
    repo.update_run_status(
        run_id, "running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.commit()

    # Accumulators
    win_count:   Counter[str] = Counter()  # champion wins per team
    rounds_count: dict[str, Counter[str]] = defaultdict(Counter)  # team→{round:count}
    group_win_count:   Counter[str] = Counter()
    qualify_count:     Counter[str] = Counter()

    num_batches = max(1, (n_iter + batch - 1) // batch)

    try:
        completed = 0
        for batch_idx in range(num_batches):
            batch_iters = min(batch, n_iter - completed)

            for i in range(batch_iters):
                iter_seed = rng_seed + completed + i
                iter_rng  = np.random.default_rng(iter_seed)
                bracket   = WC2026Bracket(model, groups, iter_rng)

                classified    = bracket.play_group_stage()
                ko_result     = bracket.play_knockout(classified)
                rounds_reached = ko_result["rounds_reached"]

                if ko_result["champion"]:
                    win_count[ko_result["champion"]] += 1

                # Group winners and qualifiers
                for pos, tid in classified.items():
                    if pos.startswith("1"):
                        group_win_count[tid] += 1
                    qualify_count[tid] += 1

                # Accumulate round-reach counts
                for tid, rnd in rounds_reached.items():
                    rounds_count[tid][rnd] += 1
                    if rnd in (ROUND_CHAMPION, ROUND_RUNNER_UP,
                               ROUND_THIRD, ROUND_FOURTH, ROUND_SF):
                        rounds_count[tid][ROUND_SF] += 1
                    if rnd in (ROUND_CHAMPION, ROUND_RUNNER_UP):
                        rounds_count[tid][ROUND_FINAL] += 1
                    if rnd == ROUND_CHAMPION:
                        rounds_count[tid][ROUND_CHAMPION] += 1

            completed += batch_iters
            progress = completed / n_iter
            if progress_callback:
                progress_callback(progress)

            logger.info(
                "MC batch %d/%d done — %d/%d iterations",
                batch_idx + 1, num_batches, completed, n_iter,
            )

        # Persist per-team results
        for tid in all_team_ids:
            rc    = rounds_count[tid]
            wins  = win_count[tid]
            total = n_iter
            repo.insert_team_result({
                "simulation_run_id":   run_id,
                "team_id":             tid,
                "win_group":           group_win_count[tid] / total,
                "qualify":             qualify_count[tid]   / total,
                "reach_round_of_32":   (rc.get(ROUND_R32, 0) + qualify_count[tid]) / total,
                "reach_round_of_16":   rc.get(ROUND_R16, 0)  / total,
                "reach_quarter_final": rc.get(ROUND_QF,  0)  / total,
                "reach_semi_final":    rc.get(ROUND_SF,  0)  / total,
                "reach_final":         rc.get(ROUND_FINAL, 0) / total,
                "win_tournament":      wins / total,
                "expected_group_points": None,
            })

        repo.update_run_status(
            run_id, "completed",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()

        _log_top_5(all_team_ids, win_count, n_iter)

    except Exception as exc:
        logger.exception("Monte Carlo run %s failed: %s", run_id, exc)
        repo.update_run_status(run_id, "failed", error_message=str(exc))
        conn.commit()
        raise

    return run_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_model(model_name: str, conn: sqlite3.Connection) -> object:
    """Instantiate the requested prediction model."""
    from app.services.prediction.baseline import BaselineModel
    from app.services.prediction.elo_model import EloModel
    from app.services.prediction.poisson_context import PoissonContextModel
    from app.services.prediction.poisson_model import PoissonModel

    models = {
        "baseline":       BaselineModel,
        "elo":            EloModel,
        "poisson":        PoissonModel,
        "poisson_context": PoissonContextModel,
    }
    cls = models.get(model_name)
    if cls is None:
        raise ValueError(f"Unknown model '{model_name}'. Choose from: {list(models)}")
    return cls(conn)


def _load_groups(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Load group composition from DB; fall back to hard-coded constants."""
    try:
        rows = conn.execute(
            """
            SELECT g.id AS group_id, gt.team_id
            FROM groups g
            JOIN group_teams gt ON g.id = gt.group_id
            ORDER BY g.id, gt.position
            """
        ).fetchall()
    except Exception:
        rows = []

    if not rows:
        logger.warning("No groups in DB — using hard-coded GROUPS_2026 constants")
        return {k: list(v) for k, v in GROUPS_2026.items()}

    groups: dict[str, list[str]] = {}
    for row in rows:
        gid = row["group_id"]
        groups.setdefault(gid, []).append(row["team_id"])
    return groups


def _log_top_5(
    all_team_ids: list[str],
    win_count: Counter[str],
    n_iter: int,
) -> None:
    top = sorted(all_team_ids, key=lambda t: win_count.get(t, 0), reverse=True)[:5]
    lines = [f"  {t}: {win_count.get(t, 0) / n_iter:.1%}" for t in top]
    logger.info("Top-5 win probabilities:\n%s", "\n".join(lines))


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)
