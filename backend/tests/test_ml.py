"""Tests for Prompt 8 — ML calibrated model: feature_builder, trainer, ml_calibrated."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import numpy as np
import pytest

from app.db.migrations import run_migrations
from app.services.ml.feature_builder import (
    FEATURE_NAMES,
    build_match_features,
    build_training_dataset,
    compute_features,
    load_elo_map,
    load_strength_map,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


def _insert_team(conn, tid: str, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (tid, name))


def _insert_elo(conn, tid: str, value: float) -> None:
    conn.execute(
        "INSERT INTO ratings (id, team_id, rating_type, value, effective_date) "
        "VALUES (?, ?, 'elo', ?, '2025-01-01')",
        (str(uuid.uuid4()), tid, value),
    )


def _insert_strength(conn, tid: str, attack: float, defense: float) -> None:
    conn.execute(
        """
        INSERT INTO team_strengths
            (id, team_id, attack_strength, defense_vulnerability,
             matches_used, cutoff_date, decay_factor)
        VALUES (?, ?, ?, ?, 20, '2025-01-01', 0.001)
        """,
        (str(uuid.uuid4()), tid, attack, defense),
    )


def _insert_result(conn, home: str, away: str, hg: int, ag: int,
                   year: int = 2020) -> None:
    conn.execute(
        """
        INSERT INTO results
            (id, home_team_id, away_team_id, home_goals, away_goals,
             match_date, outcome, is_wc)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            str(uuid.uuid4()), home, away, hg, ag,
            f"{year}-06-01",
            "W" if hg > ag else ("D" if hg == ag else "L"),
        ),
    )


# ---------------------------------------------------------------------------
# Module-scoped populated DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_ml() -> sqlite3.Connection:
    conn = _make_db()
    for tid, name in [("BRA", "Brasil"), ("SMR", "San Marino"), ("ARG", "Argentina")]:
        _insert_team(conn, tid, name)

    _insert_elo(conn, "BRA", 2030.0)
    _insert_elo(conn, "SMR", 1200.0)
    _insert_elo(conn, "ARG", 2074.0)

    _insert_strength(conn, "BRA", 1.8, 0.6)
    _insert_strength(conn, "SMR", 0.3, 2.5)
    _insert_strength(conn, "ARG", 1.7, 0.7)

    # Historical results for training (≥50 to satisfy _MIN_TRAINING_SAMPLES)
    outcomes = [
        (2, 0), (3, 0), (1, 0), (2, 1), (1, 1), (0, 0),
        (0, 1), (1, 2), (0, 2), (3, 1), (2, 2), (1, 3),
        (4, 0), (0, 0), (2, 0), (1, 0), (0, 3), (1, 1),
        (2, 1), (3, 2), (1, 0), (0, 1), (2, 0), (1, 2),
        (1, 0), (2, 1), (3, 0), (0, 2), (1, 1), (2, 0),
        (0, 1), (1, 0), (3, 1), (2, 2), (0, 0), (1, 3),
        (2, 0), (1, 1), (0, 1), (3, 0), (1, 2), (2, 1),
        (0, 0), (1, 0), (2, 3), (1, 1), (3, 2), (0, 1),
        (2, 0), (1, 0), (0, 2), (3, 1), (1, 1), (2, 0),
    ]
    for i, (hg, ag) in enumerate(outcomes):
        home = "BRA" if i % 2 == 0 else "ARG"
        away = "SMR" if i % 3 != 0 else "ARG"
        _insert_result(conn, home, away, hg, ag, year=2020 + (i // 12))

    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# 1. feature_builder: correct shape and no crash
# ---------------------------------------------------------------------------

class TestFeatureBuilder:
    def test_load_elo_map(self, db_ml):
        elo_map = load_elo_map(db_ml)
        assert "BRA" in elo_map
        assert elo_map["BRA"] == pytest.approx(2030.0)

    def test_load_strength_map(self, db_ml):
        s_map = load_strength_map(db_ml)
        assert "BRA" in s_map
        assert s_map["BRA"]["attack"] == pytest.approx(1.8)
        assert s_map["BRA"]["defense"] == pytest.approx(0.6)

    def test_compute_features_length(self, db_ml):
        elo_map = load_elo_map(db_ml)
        s_map = load_strength_map(db_ml)
        features, missing = compute_features("BRA", "SMR", True, elo_map, s_map)
        assert len(features) == len(FEATURE_NAMES), (
            f"Expected {len(FEATURE_NAMES)} features, got {len(features)}"
        )
        assert missing == []

    def test_compute_features_missing_elo(self, db_ml):
        s_map = load_strength_map(db_ml)
        features, missing = compute_features("UNKNOWN", "SMR", True, {}, s_map)
        assert len(features) == len(FEATURE_NAMES)
        assert "elo_home" in missing

    def test_neutral_vs_home_lam_home(self, db_ml):
        elo_map = load_elo_map(db_ml)
        s_map = load_strength_map(db_ml)
        feat_neutral, _ = compute_features("BRA", "SMR", True, elo_map, s_map)
        feat_home, _ = compute_features("BRA", "SMR", False, elo_map, s_map)
        # lam_home is index 8; home advantage should make it higher
        assert feat_home[8] > feat_neutral[8], "Home advantage should increase lam_home"

    def test_build_match_features_wrapper(self, db_ml):
        features, missing = build_match_features("BRA", "ARG", db_ml, is_neutral=True)
        assert len(features) == len(FEATURE_NAMES)

    def test_elo_p_home_is_in_01(self, db_ml):
        elo_map = load_elo_map(db_ml)
        s_map = load_strength_map(db_ml)
        features, _ = compute_features("BRA", "SMR", True, elo_map, s_map)
        elo_p_home = features[10]  # last feature
        assert 0.0 <= elo_p_home <= 1.0


# ---------------------------------------------------------------------------
# 2. build_training_dataset
# ---------------------------------------------------------------------------

class TestTrainingDataset:
    def test_returns_correct_shape(self, db_ml):
        X, y = build_training_dataset(db_ml)
        assert X.ndim == 2
        assert X.shape[1] == len(FEATURE_NAMES)
        assert len(y) == len(X)
        assert len(X) > 0

    def test_labels_are_0_1_2(self, db_ml):
        _, y = build_training_dataset(db_ml)
        assert set(y).issubset({0, 1, 2})

    def test_empty_db_returns_empty_arrays(self):
        conn = _make_db()
        conn.commit()
        X, y = build_training_dataset(conn)
        assert X.shape[0] == 0
        assert y.shape[0] == 0
        conn.close()

    def test_year_filter_works(self, db_ml):
        X_all, _ = build_training_dataset(db_ml, train_start_year=2020)
        X_recent, _ = build_training_dataset(db_ml, train_start_year=2022)
        assert len(X_all) >= len(X_recent)


# ---------------------------------------------------------------------------
# 3. trainer: end-to-end training on synthetic data
# ---------------------------------------------------------------------------

class TestTrainer:
    def test_train_returns_valid_result(self, db_ml, tmp_path, monkeypatch):
        """Train on the in-memory DB (small dataset) with tmp model directory."""
        monkeypatch.setattr(
            "app.core.config.settings.ML_MODELS_PATH", str(tmp_path)
        )

        from app.services.ml.trainer import train_ml_model
        result = train_ml_model(
            db_ml,
            algorithm="lightgbm",
            train_start_year=2020,
            validation_split=0.3,
        )

        assert "training_run_id" in result
        assert "model_id" in result
        assert "model_path" in result
        assert "metrics" in result
        assert Path(result["model_path"]).exists()

        metrics = result["metrics"]
        # Brier score for multiclass is bounded [0, 2]
        if "brier_score" in metrics:
            assert 0.0 <= metrics["brier_score"] <= 2.0
        if "accuracy" in metrics:
            assert 0.0 <= metrics["accuracy"] <= 1.0

    def test_train_marks_model_active(self, db_ml, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.ML_MODELS_PATH", str(tmp_path)
        )
        from app.db.repositories.ml import MLRepository
        from app.services.ml.trainer import train_ml_model

        train_ml_model(db_ml, algorithm="lightgbm", train_start_year=2020)
        active = MLRepository(db_ml).get_best_model()
        assert active is not None
        assert active["is_active"] == 1

    def test_train_fails_with_no_data(self):
        conn = _make_db()
        conn.commit()
        from app.services.ml.trainer import train_ml_model
        with pytest.raises(ValueError, match="Not enough training samples"):
            train_ml_model(conn, algorithm="lightgbm")
        conn.close()


# ---------------------------------------------------------------------------
# 4. MLCalibratedModel: inference
# ---------------------------------------------------------------------------

class TestMLCalibratedModel:
    def _setup_trained_model(self, db, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.core.config.settings.ML_MODELS_PATH", str(tmp_path)
        )
        from app.services.ml.trainer import train_ml_model
        train_ml_model(db, algorithm="lightgbm", train_start_year=2020)

    def test_fallback_when_no_model(self, db_ml):
        """Without a trained model, predict_match must raise RuntimeError (no silent fallback)."""
        import pytest
        conn = _make_db()
        for tid, name in [("A", "TeamA"), ("B", "TeamB")]:
            _insert_team(conn, tid, name)
        _insert_strength(conn, "A", 1.5, 0.8)
        _insert_strength(conn, "B", 1.0, 1.0)
        conn.commit()

        from app.services.prediction.ml_calibrated import MLCalibratedModel
        model = MLCalibratedModel(conn)
        with pytest.raises(RuntimeError, match="no hay modelo entrenado"):
            model.predict_match("A", "B")
        conn.close()

    def test_predicts_valid_probabilities(self, db_ml, tmp_path, monkeypatch):
        self._setup_trained_model(db_ml, tmp_path, monkeypatch)
        # Re-load model from a fresh instance that reads the DB
        from app.services.prediction.ml_calibrated import MLCalibratedModel
        model = MLCalibratedModel(db_ml)
        pred = model.predict_match("BRA", "SMR", context={"is_neutral": True})

        total = pred["home_win"] + pred["draw"] + pred["away_win"]
        assert abs(total - 1.0) < 1e-5, f"Probs sum to {total}"
        for key in ("home_win", "draw", "away_win"):
            assert 0.0 <= pred[key] <= 1.0

    def test_strong_team_wins_more_often(self, db_ml, tmp_path, monkeypatch):
        self._setup_trained_model(db_ml, tmp_path, monkeypatch)
        from app.services.prediction.ml_calibrated import MLCalibratedModel
        model = MLCalibratedModel(db_ml)
        pred = model.predict_match("BRA", "SMR")
        assert pred["home_win"] > pred["away_win"], (
            f"Strong team (BRA) should win more: home={pred['home_win']:.3f} "
            f"away={pred['away_win']:.3f}"
        )

    def test_missing_features_handled_gracefully(self, db_ml, tmp_path, monkeypatch):
        self._setup_trained_model(db_ml, tmp_path, monkeypatch)
        from app.services.prediction.ml_calibrated import MLCalibratedModel
        model = MLCalibratedModel(db_ml)
        # 'UNKNOWN' team has no ELO or strengths
        pred = model.predict_match("BRA", "UNKNOWN")
        total = pred["home_win"] + pred["draw"] + pred["away_win"]
        assert abs(total - 1.0) < 1e-4

    def test_model_implements_prediction_interface(self, db_ml):
        from app.services.prediction.base import PredictionModel
        from app.services.prediction.ml_calibrated import MLCalibratedModel
        model = MLCalibratedModel(db_ml)
        assert isinstance(model, PredictionModel)
        assert model.name == "ml_calibrated"


# ---------------------------------------------------------------------------
# 5. RQ task function (synchronous / unit test without RQ broker)
# ---------------------------------------------------------------------------

class TestMLTrainingTask:
    def test_run_ml_training_task_sync(self, db_ml, tmp_path, monkeypatch):
        """Call run_ml_training_task directly (bypassing RQ) via _conn override."""
        monkeypatch.setattr(
            "app.core.config.settings.ML_MODELS_PATH", str(tmp_path)
        )
        from app.db.repositories.jobs import JobRepository
        from app.workers.tasks import run_ml_training_task

        job_id = JobRepository(db_ml).create({
            "job_type": "ml_training",
            "status": "enqueued",
        })
        db_ml.commit()

        result = run_ml_training_task(
            job_id,
            algorithm="lightgbm",
            train_start_year=2020,
            _conn=db_ml,
        )

        assert "training_run_id" in result
        assert "model_id" in result

        row = db_ml.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        assert row["status"] == "completed"
