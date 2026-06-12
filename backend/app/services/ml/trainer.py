"""Train and persist an ML model (LightGBM or XGBoost) for match outcome prediction.

Flow:
1. Build (X, y) dataset from DB via feature_builder.
2. Temporal split: train on first (1 - validation_split) fraction, validate on rest.
3. Fit algorithm (lightgbm preferred, xgboost fallback).
4. Compute metrics on validation set.
5. Persist model file with joblib; record run + metrics in ml_* tables.

Returns a dict with training_run_id, model_id, model_path, and metrics.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.db.repositories.ml import MLRepository
from app.services.ml.feature_builder import (
    FEATURE_NAMES,
    build_training_dataset,
)

logger = logging.getLogger(__name__)

_MIN_TRAINING_SAMPLES = 20


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def train_ml_model(
    conn: sqlite3.Connection,
    algorithm: str | None = None,
    train_start_year: int | None = None,
    validation_split: float | None = None,
) -> dict[str, Any]:
    """Train an ML model and persist it.  Returns summary dict."""
    algo    = (algorithm or settings.ML_PREFERRED_ALGORITHM).lower()
    val_split = validation_split if validation_split is not None else settings.ML_VALIDATION_SPLIT
    start_year = train_start_year or settings.ML_TRAIN_START_YEAR

    ml_repo = MLRepository(conn)

    # Create a training run record (pending)
    run_id = ml_repo.create_training_run({
        "algorithm":         algo,
        "train_start_year":  start_year,
        "validation_split":  val_split,
        "feature_set":       json.dumps(FEATURE_NAMES),
        "hyperparams":       json.dumps(_default_hyperparams(algo)),
        "status":            "pending",
    })
    conn.commit()

    try:
        result = _run_training(
            conn, ml_repo, run_id, algo, start_year, val_split
        )
    except Exception as exc:
        logger.error("ML training failed: %s", exc, exc_info=True)
        ml_repo.update_training_run(run_id, "failed", error_message=str(exc))
        conn.commit()
        raise

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_training(
    conn: sqlite3.Connection,
    ml_repo: MLRepository,
    run_id: str,
    algo: str,
    start_year: int,
    val_split: float,
) -> dict[str, Any]:
    ml_repo.update_training_run(
        run_id, "running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.commit()

    # Build dataset
    X, y = build_training_dataset(conn, train_start_year=start_year)

    n = len(X)
    if n < _MIN_TRAINING_SAMPLES:
        raise ValueError(
            f"Not enough training samples: {n} < {_MIN_TRAINING_SAMPLES}. "
            "Ingest historical results first."
        )

    # Temporal split (rows are already sorted by date in build_training_dataset)
    split_idx = max(1, int(n * (1 - val_split)))
    X_train, y_train = X[:split_idx], y[:split_idx]
    X_val,   y_val   = X[split_idx:], y[split_idx:]

    logger.info(
        "Training %s: %d train / %d val samples, %d features",
        algo, len(X_train), len(X_val), X.shape[1],
    )

    # Fit model — use pandas DataFrames so feature names are preserved and
    # LightGBM/XGBoost don't emit "feature names" warnings at inference time.
    import pandas as pd
    X_train_df = pd.DataFrame(X_train, columns=FEATURE_NAMES)
    model = _fit(algo, X_train_df, y_train)

    # Evaluate
    metrics = _evaluate(model, X_val, y_val) if len(X_val) > 0 else {}
    logger.info("Validation metrics: %s", metrics)

    # Persist model file
    model_path = _save_model(model, algo, run_id)

    # Persist model record
    model_id = ml_repo.save_model_path(run_id, algo, model_path, metrics)

    # Feature importances
    importances = _get_feature_importances(model, algo)
    if importances:
        ml_repo.save_feature_snapshot(run_id, FEATURE_NAMES, importances)

    # Mark active
    ml_repo.set_active_model(model_id)

    # Mark run completed
    ml_repo.update_training_run(
        run_id, "completed",
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.commit()

    return {
        "training_run_id": run_id,
        "model_id":        model_id,
        "algorithm":       algo,
        "model_path":      model_path,
        "n_train":         int(len(X_train)),
        "n_val":           int(len(X_val)),
        "metrics":         metrics,
        "feature_importances": importances,
    }


def _fit(algo: str, X: np.ndarray, y: np.ndarray):
    hp = _default_hyperparams(algo)

    if algo == "lightgbm":
        import lightgbm as lgb
        clf = lgb.LGBMClassifier(
            n_estimators=hp["n_estimators"],
            learning_rate=hp["learning_rate"],
            max_depth=hp["max_depth"],
            num_leaves=hp["num_leaves"],
            subsample=hp["subsample"],
            colsample_bytree=hp["colsample_bytree"],
            random_state=42,
            verbose=-1,
        )
    elif algo == "xgboost":
        import xgboost as xgb
        clf = xgb.XGBClassifier(
            n_estimators=hp["n_estimators"],
            learning_rate=hp["learning_rate"],
            max_depth=hp["max_depth"],
            subsample=hp["subsample"],
            colsample_bytree=hp["colsample_bytree"],
            use_label_encoder=False,
            eval_metric="mlogloss",
            verbosity=0,
            random_state=42,
        )
    else:
        from sklearn.ensemble import RandomForestClassifier
        clf = RandomForestClassifier(
            n_estimators=hp.get("n_estimators", 200),
            max_depth=hp.get("max_depth", 8),
            random_state=42,
            n_jobs=-1,
        )

    clf.fit(X, y)
    return clf


def _evaluate(model, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
    import pandas as pd
    from sklearn.metrics import log_loss

    X_df = pd.DataFrame(X, columns=FEATURE_NAMES)
    proba = model.predict_proba(X_df)  # shape (N, 3)
    preds = np.argmax(proba, axis=1)

    # Brier score (multiclass): mean squared error over all class probabilities
    n_classes = proba.shape[1]
    y_onehot = np.zeros_like(proba)
    for i, label in enumerate(y):
        if label < n_classes:
            y_onehot[i, label] = 1.0
    brier = float(np.mean(np.sum((proba - y_onehot) ** 2, axis=1)))

    # Log loss
    ll = float(log_loss(y, proba, labels=[0, 1, 2]))

    # Accuracy
    acc = float(np.mean(preds == y))

    return {
        "brier_score": round(brier, 6),
        "log_loss":    round(ll, 6),
        "accuracy":    round(acc, 6),
    }


def _save_model(model, algo: str, run_id: str) -> str:
    import joblib

    models_dir = Path(settings.ML_MODELS_PATH)
    models_dir.mkdir(parents=True, exist_ok=True)

    filename = f"ml_{algo}_{run_id[:8]}.joblib"
    path = str(models_dir / filename)
    joblib.dump(model, path)
    logger.info("Model saved to %s", path)
    return path


def _get_feature_importances(model, algo: str) -> list[float] | None:
    try:
        if algo in ("lightgbm", "xgboost"):
            imp = model.feature_importances_
        else:
            imp = model.feature_importances_
        total = float(np.sum(imp))
        if total > 0:
            return [round(float(v) / total, 6) for v in imp]
        return [float(v) for v in imp]
    except AttributeError:
        return None


def _default_hyperparams(algo: str) -> dict[str, Any]:
    if algo == "lightgbm":
        return {
            "n_estimators": 300,
            "learning_rate": 0.05,
            "max_depth": 6,
            "num_leaves": 31,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
        }
    if algo == "xgboost":
        return {
            "n_estimators": 300,
            "learning_rate": 0.05,
            "max_depth": 6,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
        }
    return {"n_estimators": 200, "max_depth": 8}
