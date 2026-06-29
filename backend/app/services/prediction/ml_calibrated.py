"""ML-calibrated prediction model (LightGBM / XGBoost).

Loads the best active model from the DB, builds the feature vector for a
given match using feature_builder, and returns probabilities calibrated by the
trained classifier.

Falls back to Poisson+DC probabilities if no trained model is available.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.prediction.base import PredictionModel

logger = logging.getLogger(__name__)

_FALLBACK_MODEL_NAME = "poisson"

# ---------------------------------------------------------------------------
# Module-level model cache — avoids joblib.load on every request
# ---------------------------------------------------------------------------
_model_cache: dict = {}
_cache_lock = threading.Lock()


def _safe_load_model(model_path: str):
    """Load a model file only if it is inside the allowed directory.

    Prevents path-traversal attacks where a tampered DB row points to an
    arbitrary file on the filesystem.
    """
    path = Path(model_path).resolve()
    allowed_dir = Path(settings.ML_MODELS_PATH).resolve()

    try:
        inside_allowed_dir = path == allowed_dir or path.is_relative_to(allowed_dir)
    except AttributeError:
        inside_allowed_dir = path == allowed_dir or allowed_dir in path.parents

    if not inside_allowed_dir:
        raise ValueError(
            f"Model path '{path}' is outside the allowed directory '{allowed_dir}'"
        )
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")
    if path.suffix not in (".pkl", ".joblib"):
        raise ValueError(f"Disallowed model file extension: {path.suffix}")

    import joblib
    return joblib.load(path)


def get_cached_model(conn: sqlite3.Connection) -> "MLCalibratedModel":
    """Return the active model from cache if the model_path has not changed.

    Thread-safe for concurrent FastAPI workers.
    """
    from app.db.repositories.ml import MLRepository

    try:
        row = MLRepository(conn).get_best_model()
    except Exception as exc:
        logger.warning("get_cached_model: could not query active model: %s", exc)
        return MLCalibratedModel(conn)

    current_path = row.get("model_path") if row else None

    with _cache_lock:
        cached = _model_cache.get("instance")
        if cached is not None and cached.model_path == current_path:
            return cached
        instance = MLCalibratedModel(conn)
        _model_cache["instance"] = instance
        return instance


class MLCalibratedModel(PredictionModel):
    name = "ml_calibrated"
    version = "1.0"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._clf = None
        self._model_meta: dict | None = None
        self.model_path: str | None = None  # exposed for cache invalidation
        self._load_model()

        # Preload de mapas una sola vez — evita 14.2M queries en Monte Carlo.
        # Los mapas son estables durante una simulación (datos no cambian mid-run).
        from app.services.ml.feature_builder import (
            FEATURE_NAMES,
            load_elo_map,
            load_strength_map,
            load_statsbomb_map,
        )
        self._elo_map       = load_elo_map(conn)
        self._strength_map  = load_strength_map(conn)
        self._sb_map        = load_statsbomb_map(conn)
        self._feature_names = FEATURE_NAMES
        logger.debug(
            "MLCalibratedModel: maps cargados — %d ELO, %d strengths, %d StatsBomb",
            len(self._elo_map), len(self._strength_map), len(self._sb_map),
        )

    # ------------------------------------------------------------------
    # Public API (PredictionModel interface)
    # ------------------------------------------------------------------

    def predict_match(
        self,
        home_team_id: str,
        away_team_id: str,
        context: dict | None = None,
    ) -> dict:
        ctx = context or {}
        is_neutral: bool = ctx.get("is_neutral", True)

        if self._clf is None:
            raise RuntimeError(
                "ml_calibrated: no hay modelo entrenado. "
                "Ejecuta POST /api/ml/train antes de correr esta simulación."
            )

        from app.services.ml.feature_builder import compute_features
        features, missing = compute_features(
            home_team_id, away_team_id, is_neutral,
            self._elo_map, self._strength_map, self._sb_map,
        )

        try:
            X = np.array([features], dtype=np.float64)
            proba = self._clf.predict_proba(X)[0]  # shape (3,)
            total = float(sum(proba))
            if total > 0:
                proba = [float(p) / total for p in proba]
            else:
                proba = [1 / 3, 1 / 3, 1 / 3]
        except Exception as exc:
            logger.warning("MLCalibratedModel: inference error: %s", exc)
            return self._fallback(home_team_id, away_team_id, ctx)

        home_win, draw, away_win = proba[0], proba[1], proba[2]
        algo = (self._model_meta or {}).get("algorithm", "ml")

        return {
            "home_win":             home_win,
            "draw":                 draw,
            "away_win":             away_win,
            "expected_home_goals":  _rough_goals(home_win, draw, away_win, home=True),
            "expected_away_goals":  _rough_goals(home_win, draw, away_win, home=False),
            "most_likely_score":    _most_likely_score(home_win, draw, away_win),
            "features_used":        [f for f in self._feature_names if f not in missing],
            "features_missing":     missing,
            "explanation": (
                f"{algo.upper()}: P(home_win)={home_win:.2%} "
                f"P(draw)={draw:.2%} P(away_win)={away_win:.2%}"
            ),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Load the best active ML model from the DB (if any)."""
        try:
            from app.db.repositories.ml import MLRepository
            row = MLRepository(self._conn).get_best_model()
        except Exception as exc:
            logger.warning("MLCalibratedModel: could not query active model: %s", exc)
            return

        if row is None:
            logger.info("MLCalibratedModel: no active model in DB — will fall back to Poisson")
            return

        model_path = row.get("model_path")
        if not model_path:
            logger.warning("MLCalibratedModel: active model has no model_path")
            return

        try:
            self._clf = _safe_load_model(model_path)
            self._model_meta = dict(row)
            self.model_path = model_path
            logger.info(
                "MLCalibratedModel: loaded %s from %s (brier=%.4f)",
                row.get("algorithm"), model_path, row.get("brier_score") or 0,
            )
        except Exception as exc:
            logger.warning("MLCalibratedModel: failed to load model file %s: %s", model_path, exc)

    def _fallback(
        self,
        home_team_id: str,
        away_team_id: str,
        context: dict,
    ) -> dict:
        from app.services.prediction.poisson_model import PoissonModel
        result = PoissonModel(self._conn).predict_match(home_team_id, away_team_id, context)
        result["explanation"] = "[fallback-poisson] " + result.get("explanation", "")
        return result


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _feature_names() -> list[str]:
    from app.services.ml.feature_builder import FEATURE_NAMES
    return FEATURE_NAMES


def _rough_goals(hw: float, draw: float, aw: float, home: bool) -> float:
    if home:
        return round(1.5 * (hw + 0.5 * draw), 3)
    return round(1.5 * (aw + 0.5 * draw), 3)


def _most_likely_score(hw: float, draw: float, aw: float) -> str:
    if hw >= draw and hw >= aw:
        return "1-0"
    if aw >= draw and aw >= hw:
        return "0-1"
    return "1-1"
