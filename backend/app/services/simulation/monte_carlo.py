"""Monte Carlo WC2026 simulator.

Runs `iterations` full bracket simulations, accumulates per-team reach rates,
persists results via SimulationRepository, and returns the simulation run_id.
"""

from __future__ import annotations

import json
import logging
import signal
import sqlite3
import time
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

# Max seconds allowed for the entire simulation loop (not counting DB writes).
# signal.SIGALRM only works on Unix in the main thread of a process, which is
# exactly the environment RQ workers run in (forked child process per job).
# Configurable via MONTE_CARLO_TIMEOUT_S (default 1800 = 30 min; ARM64 is slower).
_PROGRESS_LOG_INTERVAL = 5_000  # log every N iterations


def _get_timeout() -> int:
    return settings.MONTE_CARLO_TIMEOUT_S


def _alarm_handler(signum: int, frame: object) -> None:  # noqa: ARG001
    timeout = _get_timeout()
    raise TimeoutError(
        f"Monte Carlo simulation timed out after {timeout}s. "
        "Increase MONTE_CARLO_TIMEOUT_S or reduce MONTECARLO_ITERATIONS."
    )


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

    try:
        valid_team_ids = repo.get_existing_team_ids()
        if not valid_team_ids:
            raise RuntimeError(
                "teams table is empty; run full refresh or load data/raw/teams.csv before simulations"
            )

        # Accumulators
        win_count:   Counter[str] = Counter()  # champion wins per team
        rounds_count: dict[str, Counter[str]] = defaultdict(Counter)  # team→{round:count}
        group_win_count:   Counter[str] = Counter()
        qualify_count:     Counter[str] = Counter()

        num_batches = max(1, (n_iter + batch - 1) // batch)

        # Arm a watchdog: if the simulation loop hangs beyond MONTE_CARLO_TIMEOUT_S
        # the SIGALRM handler raises TimeoutError which propagates as a normal failure.
        _timeout_s = _get_timeout()
        _has_sigalrm = hasattr(signal, "SIGALRM")
        if _has_sigalrm:
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(_timeout_s)

        try:
            completed = 0
            _loop_start = time.monotonic()
            for batch_idx in range(num_batches):
                batch_iters = min(batch, n_iter - completed)

                for i in range(batch_iters):
                    global_i = completed + i
                    if global_i % _PROGRESS_LOG_INTERVAL == 0 and global_i > 0:
                        elapsed = time.monotonic() - _loop_start
                        rate = global_i / elapsed
                        remaining = (n_iter - global_i) / rate if rate > 0 else 0
                        logger.info(
                            "[Monte Carlo] %s — %d/%d iteraciones (%.1f%%) "
                            "— %.0fs transcurridos, ~%.0fs restantes",
                            model_name, global_i, n_iter,
                            100 * global_i / n_iter, elapsed, remaining,
                        )

                    iter_seed = rng_seed + global_i
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
        finally:
            if _has_sigalrm:
                signal.alarm(0)  # cancel watchdog regardless of outcome

        try:
            if not repo.run_exists(run_id):
                raise RuntimeError(
                    f"simulation_run '{run_id}' was not persisted before team results insert"
                )

            # Persist per-team results. Missing team rows are skipped to avoid
            # aborting an otherwise valid simulation on reference-data drift.
            skipped = 0
            inserted = 0
            for tid in all_team_ids:
                if tid not in valid_team_ids:
                    logger.warning(
                        "MC run %s: team_id '%s' not in teams table — skipping",
                        run_id, tid,
                    )
                    skipped += 1
                    continue

                rc    = rounds_count[tid]
                wins  = win_count[tid]
                total = n_iter
                result_id = repo.insert_team_result({
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
                if result_id:
                    inserted += 1

            if skipped:
                logger.warning(
                    "MC run %s: skipped %d/%d team result(s)",
                    run_id, skipped, len(all_team_ids),
                )

            if inserted == 0:
                raise RuntimeError(
                    f"Monte Carlo run {run_id} produced no persisted team results"
                )

            repo.update_run_status(
                run_id, "completed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(
                "MC run %s: team result persistence failed; rolled back inserts",
                run_id,
            )
            raise

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
    from app.services.prediction.ml_calibrated import MLCalibratedModel
    from app.services.prediction.poisson_context import PoissonContextModel
    from app.services.prediction.poisson_model import PoissonModel

    models = {
        "baseline":        BaselineModel,
        "elo":             EloModel,
        "poisson":         PoissonModel,
        "poisson_context": PoissonContextModel,
        "ml_calibrated":   MLCalibratedModel,
    }
    if model_name == "consensus":
        from app.services.prediction.consensus import ConsensusModel
        return ConsensusModel(conn)
    if model_name == "ml_calibrated":
        return MLCalibratedModel(conn)
    cls = models.get(model_name)
    if cls is None:
        raise ValueError(f"Unknown model '{model_name}'. Choose from: {list(models) + ['consensus']}")
    return cls(conn)


def _load_groups(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Load group composition from DB; fall back to hard-coded constants only if empty."""
    try:
        rows = conn.execute(
            """
            SELECT g.id AS group_id, gt.team_id
            FROM groups g
            JOIN group_teams gt ON g.id = gt.group_id
            ORDER BY g.id, gt.position
            """
        ).fetchall()
    except Exception as exc:
        logger.error("_load_groups DB query failed: %s — falling back to GROUPS_2026", exc)
        return {k: list(v) for k, v in GROUPS_2026.items()}

    if not rows:
        logger.warning("group_teams table is empty — using hard-coded GROUPS_2026 fallback")
        return {k: list(v) for k, v in GROUPS_2026.items()}

    groups: dict[str, list[str]] = {}
    for row in rows:
        gid = row["group_id"]
        groups.setdefault(gid, []).append(row["team_id"])
    logger.info("_load_groups: loaded %d groups from DB", len(groups))
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
