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

        # Pre-compute predictions for all possible WC2026 matchups.
        # 48 teams × 47 opponents = 2256 pairs → 1 batch predict_proba call
        # instead of 4.74M individual calls during Monte Carlo.
        # predict_match() becomes an O(1) dict lookup.
        self._predict_cache: dict[tuple[str, str], tuple[float, float, float]] = {}
        if self._clf is not None:
            self._predict_cache = self._build_predict_cache()
            logger.info(
                "MLCalibratedModel: cache pre-computado — %d pares",
                len(self._predict_cache),
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

        if self._clf is None:
            raise RuntimeError(
                "ml_calibrated: no hay modelo entrenado. "
                "Ejecuta POST /api/ml/train antes de correr esta simulación."
            )

        # O(1) cache lookup — covers all normal Monte Carlo calls
        cached = self._predict_cache.get((home_team_id, away_team_id))
        if cached is not None:
            hw, dr, aw = cached
            exp_h = round(self._elo_map.get(home_team_id, 1500) / 800, 2)
            exp_a = round(self._elo_map.get(away_team_id, 1500) / 800, 2)
            return {
                "home_win":            hw,
                "draw":                dr,
                "away_win":            aw,
                "expected_home_goals": exp_h,
                "expected_away_goals": exp_a,
                "most_likely_score":   f"{round(exp_h)}-{round(exp_a)}",
                "features_used":       ["cache_lookup"],
                "features_missing":    [],
                "explanation":         f"ML cache: {hw:.1%}/{dr:.1%}/{aw:.1%}",
            }

        # Fallback: on-the-fly para pares fuera del cache (no debería ocurrir en MC)
        logger.warning(
            "MLCalibratedModel: cache miss %s vs %s — computando on-the-fly",
            home_team_id, away_team_id,
        )
        from app.services.ml.feature_builder import compute_features
        features, missing = compute_features(
            home_team_id, away_team_id,
            ctx.get("is_neutral", True),
            self._elo_map, self._strength_map, self._sb_map,
        )
        try:
            X     = np.array([features], dtype=np.float64)
            proba = self._clf.predict_proba(X)[0]
            total = float(sum(proba))
            p     = [float(v) / total for v in proba] if total > 0 else [1/3, 1/3, 1/3]
            return {
                "home_win":            p[0],
                "draw":                p[1],
                "away_win":            p[2],
                "expected_home_goals": 1.5,
                "expected_away_goals": 1.0,
                "most_likely_score":   "1-1",
                "features_used":       [],
                "features_missing":    missing,
                "explanation":         "ML on-the-fly (cache miss)",
            }
        except Exception as exc:
            logger.warning("MLCalibratedModel: inference error: %s", exc)
            return self._fallback(home_team_id, away_team_id, ctx)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_predict_cache(self) -> dict[tuple[str, str], tuple[float, float, float]]:
        """Pre-compute win/draw/loss for all (home, away) pairs in one batch call."""
        from app.services.ml.feature_builder import compute_features

        try:
            team_rows = self._conn.execute(
                "SELECT id FROM teams WHERE is_wc2026 = 1"
            ).fetchall()
            team_ids = [r["id"] for r in team_rows]
        except Exception as exc:
            logger.warning("MLCalibratedModel: no se pudo cargar equipos: %s", exc)
            return {}

        if len(team_ids) < 2:
            return {}

        pairs: list[tuple[str, str]] = []
        rows: list[list[float]] = []

        for home_id in team_ids:
            for away_id in team_ids:
                if home_id == away_id:
                    continue
                features, _ = compute_features(
                    home_id, away_id,
                    is_neutral=True,
                    elo_map=self._elo_map,
                    strength_map=self._strength_map,
                    sb_map=self._sb_map,
                )
                pairs.append((home_id, away_id))
                rows.append(features)

        if not rows:
            return {}

        try:
            X      = np.array(rows, dtype=np.float64)
            probas = self._clf.predict_proba(X)
        except Exception as exc:
            logger.warning("MLCalibratedModel: batch predict_proba falló: %s", exc)
            return {}

        cache: dict[tuple[str, str], tuple[float, float, float]] = {}
        for (home_id, away_id), proba in zip(pairs, probas):
            total = float(sum(proba))
            p = [float(v) / total for v in proba] if total > 0 else [1/3, 1/3, 1/3]
            cache[(home_id, away_id)] = (p[0], p[1], p[2])

        return cache

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
