"""Consensus ensemble model — weighted average of all 5 prediction models.

Weights are derived from the inverse Brier Score of backtesting results:
lower Brier Score → higher weight.  Falls back to equal weights when
backtesting metrics are unavailable (e.g. fresh install, no history yet).
"""

from __future__ import annotations

import logging
import sqlite3

from app.services.prediction.base import PredictionModel

logger = logging.getLogger(__name__)

_MODEL_NAMES = ["elo", "poisson", "poisson_context", "ml_calibrated"]
# Baseline excluido: asigna probabilidades iguales a todos los partidos
# sin importar equipos — distorsiona el ensemble hacia la media global.

_AGG_COLS = [
    "win_tournament", "reach_final", "reach_semi_final",
    "reach_quarter_final", "reach_round_of_16", "reach_round_of_32",
    "qualify", "win_group",
]


def compute_consensus_from_results(conn: sqlite3.Connection) -> dict[str, dict]:
    """Aggregate stored per-model simulation results into a consensus view.

    For each base model, uses the newest completed run that passes
    validate_simulation_run (see app.services.simulation.validation) — a run
    produced by a buggy Monte Carlo build (e.g. the reach_round_of_32
    double-count bug) is skipped even if it's the most recent, with a
    warning logged, rather than silently poisoning the consensus.

    Returns {team_id: {win_tournament, reach_final, ...}} or empty dict if
    fewer than 2 valid individual model simulations are available.
    """
    from app.services.simulation.validation import get_latest_valid_run

    weights = get_consensus_weights(conn)

    valid_run_ids: dict[str, str] = {}
    for model_name in _MODEL_NAMES:
        run = get_latest_valid_run(conn, model_name)
        if run is None:
            logger.warning(
                "compute_consensus: %s no tiene ningún run completed válido reciente — se omite",
                model_name,
            )
            continue
        valid_run_ids[model_name] = run["id"]

    if not valid_run_ids:
        logger.warning("compute_consensus: no hay simulaciones individuales válidas disponibles")
        return {}

    placeholders = ",".join("?" for _ in valid_run_ids)
    rows = conn.execute(
        f"""
        SELECT str.team_id, sr.model_name,
               str.win_tournament,      str.reach_final,
               str.reach_semi_final,    str.reach_quarter_final,
               str.reach_round_of_16,   str.reach_round_of_32,
               str.qualify,             str.win_group
        FROM simulation_team_results str
        JOIN simulation_runs sr ON str.simulation_run_id = sr.id
        WHERE sr.id IN ({placeholders})
        """,
        list(valid_run_ids.values()),
    ).fetchall()

    if not rows:
        logger.warning("compute_consensus: no hay simulaciones individuales disponibles")
        return {}

    by_team: dict[str, dict[str, dict]] = {}
    models_present: set[str] = set()
    for r in rows:
        tid = r["team_id"]
        m   = r["model_name"]
        models_present.add(m)
        by_team.setdefault(tid, {})[m] = {
            col: float(r[col] or 0) for col in _AGG_COLS
        }

    if len(models_present) < 2:
        logger.warning(
            "compute_consensus: solo %d modelo(s) disponibles — mínimo 2",
            len(models_present),
        )
        return {}

    w_present = {m: weights[m] for m in models_present if m in weights}
    total_w   = sum(w_present.values()) or 1.0
    w_norm    = {m: v / total_w for m, v in w_present.items()}

    result: dict[str, dict] = {}
    for tid, model_probs in by_team.items():
        aggregated: dict[str, object] = {
            col: sum(w_norm.get(m, 0) * probs[col] for m, probs in model_probs.items())
            for col in _AGG_COLS
        }
        aggregated["models_used"]  = sorted(model_probs.keys())
        aggregated["weights_used"] = {m: round(w_norm.get(m, 0), 4) for m in model_probs}
        result[tid] = aggregated

    logger.info(
        "compute_consensus: calculado para %d equipos usando modelos: %s",
        len(result), sorted(models_present),
    )
    return result


def _get_model(model_name: str, conn: sqlite3.Connection) -> PredictionModel:
    from app.services.prediction.baseline import BaselineModel
    from app.services.prediction.elo_model import EloModel
    from app.services.prediction.ml_calibrated import MLCalibratedModel
    from app.services.prediction.poisson_context import PoissonContextModel
    from app.services.prediction.poisson_model import PoissonModel

    cls_map = {
        "baseline":        BaselineModel,
        "elo":             EloModel,
        "poisson":         PoissonModel,
        "poisson_context": PoissonContextModel,
        "ml_calibrated":   MLCalibratedModel,
    }
    return cls_map[model_name](conn)


def get_consensus_weights(conn: sqlite3.Connection) -> dict[str, float]:
    """Return per-model weights derived from inverse Brier Score.

    If no evaluations exist yet, returns equal weights (0.2 each).
    Models missing from the evaluations table receive the mean inverse weight
    of those that do appear, so they are not silently zeroed.
    """
    rows = conn.execute(
        """
        SELECT model_name, AVG(brier_score) AS avg_brier
        FROM model_evaluations
        WHERE model_name IN ('elo','poisson','poisson_context','ml_calibrated')
          AND brier_score IS NOT NULL
          AND brier_score > 0
        GROUP BY model_name
        """
    ).fetchall()

    if not rows:
        return {m: 1.0 / len(_MODEL_NAMES) for m in _MODEL_NAMES}

    inverse: dict[str, float] = {r["model_name"]: 1.0 / r["avg_brier"] for r in rows}

    # Models absent from backtesting get the mean inverse weight of present models
    mean_inv = sum(inverse.values()) / len(inverse)
    for m in _MODEL_NAMES:
        inverse.setdefault(m, mean_inv)

    total = sum(inverse.values())
    return {k: v / total for k, v in inverse.items()}


class ConsensusModel(PredictionModel):
    """Weighted ensemble of the 5 prediction models.

    Weights are computed once at instantiation from backtesting Brier Scores.
    """

    name = "consensus"
    version = "1.0"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._weights = get_consensus_weights(conn)
        self._sub_models: dict[str, PredictionModel] = {
            m: _get_model(m, conn) for m in _MODEL_NAMES
        }
        logger.info(
            "ConsensusModel weights: %s",
            {k: f"{v:.3f}" for k, v in self._weights.items()},
        )

    def predict_match(
        self,
        home_team_id: str,
        away_team_id: str,
        context: dict | None = None,
    ) -> dict:
        individual: dict[str, dict] = {}
        for m_name, model in self._sub_models.items():
            try:
                individual[m_name] = model.predict_match(home_team_id, away_team_id, context)
            except Exception as exc:
                logger.warning("ConsensusModel: sub-model %s failed for %s vs %s: %s",
                               m_name, home_team_id, away_team_id, exc)
                individual[m_name] = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0,
                                      "expected_home_goals": 1.5, "expected_away_goals": 1.0,
                                      "most_likely_score": "1-1",
                                      "features_used": [], "features_missing": [], "explanation": "error"}

        w = self._weights
        hw = sum(w[m] * individual[m]["home_win"] for m in _MODEL_NAMES)
        dr = sum(w[m] * individual[m]["draw"]     for m in _MODEL_NAMES)
        aw = sum(w[m] * individual[m]["away_win"] for m in _MODEL_NAMES)

        # Renormalise to guard against floating-point drift
        total = hw + dr + aw
        if total > 0:
            hw, dr, aw = hw / total, dr / total, aw / total

        exp_h = sum(w[m] * individual[m].get("expected_home_goals", 1.5) for m in _MODEL_NAMES)
        exp_a = sum(w[m] * individual[m].get("expected_away_goals", 1.0) for m in _MODEL_NAMES)

        all_used    = list({f for m in _MODEL_NAMES for f in individual[m].get("features_used",    [])})
        all_missing = list({f for m in _MODEL_NAMES for f in individual[m].get("features_missing", [])})

        return {
            "home_win":             hw,
            "draw":                 dr,
            "away_win":             aw,
            "expected_home_goals":  exp_h,
            "expected_away_goals":  exp_a,
            "most_likely_score":    f"{round(exp_h)}-{round(exp_a)}",
            "features_used":        all_used,
            "features_missing":     all_missing,
            "explanation": (
                f"Consenso ensemble: {hw:.1%}/{dr:.1%}/{aw:.1%} "
                f"(pesos: {', '.join(f'{m}={w[m]:.2f}' for m in _MODEL_NAMES)})"
            ),
        }
