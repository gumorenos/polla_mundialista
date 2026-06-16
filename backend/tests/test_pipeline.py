"""Tests for Prompt 9 — metrics, backtesting, and full pipeline."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from app.db.migrations import run_migrations
from app.services.evaluation.metrics import (
    accuracy,
    brier_score,
    calibration_data,
    log_loss,
    ranked_probability_score,
)


# ---------------------------------------------------------------------------
# Shared DB helpers
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


def _insert_result(conn, home: str, away: str, hg: int, ag: int, year: int = 2022) -> None:
    conn.execute(
        """
        INSERT INTO results
            (id, home_team_id, away_team_id, home_goals, away_goals,
             match_date, outcome, is_wc)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            str(uuid.uuid4()), home, away, hg, ag,
            f"{year}-06-{str((hg + ag) % 28 + 1).zfill(2)}",
            "W" if hg > ag else ("D" if hg == ag else "L"),
        ),
    )


# ---------------------------------------------------------------------------
# Shared module-scoped DB with enough data for pipeline
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_pipe() -> sqlite3.Connection:
    conn = _make_db()
    for tid, name in [("BRA", "Brasil"), ("ARG", "Argentina"),
                      ("SMR", "San Marino"), ("GER", "Alemania")]:
        _insert_team(conn, tid, name)

    for tid, elo in [("BRA", 2030.0), ("ARG", 2074.0),
                     ("SMR", 1200.0), ("GER", 1950.0)]:
        _insert_elo(conn, tid, elo)

    for tid, atk, dfn in [("BRA", 1.8, 0.6), ("ARG", 1.7, 0.7),
                           ("SMR", 0.3, 2.5), ("GER", 1.5, 0.8)]:
        _insert_strength(conn, tid, atk, dfn)

    # Enough historical results for training AND backtesting
    outcomes = [
        ("BRA", "ARG", 2, 1, 2020), ("BRA", "ARG", 1, 1, 2021),
        ("BRA", "SMR", 3, 0, 2020), ("BRA", "SMR", 4, 0, 2021),
        ("ARG", "GER", 1, 0, 2020), ("ARG", "GER", 2, 0, 2022),
        ("GER", "SMR", 5, 0, 2021), ("GER", "SMR", 3, 1, 2022),
        ("BRA", "GER", 1, 0, 2022), ("ARG", "SMR", 6, 0, 2022),
        ("BRA", "ARG", 0, 1, 2022), ("GER", "ARG", 1, 2, 2023),
        ("BRA", "SMR", 2, 0, 2023), ("SMR", "BRA", 0, 3, 2023),
        ("ARG", "BRA", 1, 0, 2023), ("GER", "BRA", 0, 2, 2024),
        ("BRA", "ARG", 2, 2, 2024), ("ARG", "SMR", 3, 0, 2024),
        ("GER", "SMR", 4, 0, 2024), ("BRA", "GER", 1, 1, 2024),
        ("ARG", "GER", 0, 1, 2024), ("SMR", "ARG", 0, 2, 2024),
        ("BRA", "SMR", 5, 0, 2024), ("ARG", "GER", 2, 1, 2025),
    ]
    for home, away, hg, ag, yr in outcomes:
        _insert_result(conn, home, away, hg, ag, yr)

    conn.commit()
    yield conn
    conn.close()


# ===========================================================================
# 1. Metric functions
# ===========================================================================

class TestBrierScore:
    def test_perfect_predictions_give_zero(self):
        preds   = [{"home_win": 1.0, "draw": 0.0, "away_win": 0.0}]
        actuals = ["home_win"]
        assert brier_score(preds, actuals) == pytest.approx(0.0)

    def test_worst_predictions_give_one(self):
        preds   = [{"home_win": 0.0, "draw": 0.0, "away_win": 1.0}]
        actuals = ["home_win"]
        assert brier_score(preds, actuals) == pytest.approx(1.0)

    def test_always_in_0_1(self):
        import random
        rng = random.Random(42)
        for _ in range(100):
            h = rng.random()
            d = rng.random()
            a = rng.random()
            outcome = rng.choice(["home_win", "draw", "away_win"])
            bs = brier_score(
                [{"home_win": h, "draw": d, "away_win": a}], [outcome]
            )
            assert 0.0 <= bs <= 1.0 + 1e-9, f"brier_score={bs} out of range"

    def test_uniform_predictor(self):
        preds   = [{"home_win": 1/3, "draw": 1/3, "away_win": 1/3}] * 3
        actuals = ["home_win", "draw", "away_win"]
        bs = brier_score(preds, actuals)
        assert 0.0 <= bs <= 1.0

    def test_empty_returns_zero(self):
        assert brier_score([], []) == 0.0


class TestLogLoss:
    def test_perfect_gives_near_zero(self):
        preds   = [{"home_win": 1.0, "draw": 0.0, "away_win": 0.0}]
        actuals = ["home_win"]
        assert log_loss(preds, actuals) < 1e-6

    def test_never_negative(self):
        preds   = [{"home_win": 0.7, "draw": 0.2, "away_win": 0.1}] * 10
        actuals = ["home_win"] * 5 + ["draw"] * 5
        assert log_loss(preds, actuals) >= 0.0

    def test_empty_returns_zero(self):
        assert log_loss([], []) == 0.0


class TestRankedProbabilityScore:
    def test_perfect_gives_zero(self):
        preds   = [{"home_win": 1.0, "draw": 0.0, "away_win": 0.0}]
        actuals = ["home_win"]
        assert ranked_probability_score(preds, actuals) == pytest.approx(0.0)

    def test_always_in_0_1(self):
        preds   = [{"home_win": 0.6, "draw": 0.3, "away_win": 0.1}]
        actuals = ["away_win"]
        rps = ranked_probability_score(preds, actuals)
        assert 0.0 <= rps <= 1.0

    def test_empty_returns_zero(self):
        assert ranked_probability_score([], []) == 0.0


class TestAccuracy:
    def test_all_correct(self):
        preds   = [{"home_win": 0.8, "draw": 0.1, "away_win": 0.1}] * 3
        actuals = ["home_win", "home_win", "home_win"]
        assert accuracy(preds, actuals) == pytest.approx(1.0)

    def test_all_wrong(self):
        preds   = [{"home_win": 0.8, "draw": 0.1, "away_win": 0.1}] * 3
        actuals = ["away_win", "draw", "away_win"]
        assert accuracy(preds, actuals) == pytest.approx(0.0)

    def test_empty_returns_zero(self):
        assert accuracy([], []) == 0.0


class TestCalibrationData:
    def test_returns_n_bins(self):
        preds   = [{"home_win": 0.4, "draw": 0.3, "away_win": 0.3}] * 30
        actuals = ["home_win"] * 15 + ["draw"] * 15
        cal = calibration_data(preds, actuals, n_bins=10)
        assert len(cal) == 10

    def test_each_bin_has_required_keys(self):
        preds   = [{"home_win": 0.5, "draw": 0.3, "away_win": 0.2}] * 10
        actuals = ["home_win"] * 5 + ["away_win"] * 5
        cal = calibration_data(preds, actuals, n_bins=10)
        for b in cal:
            assert "bin_center"     in b
            assert "predicted_freq" in b
            assert "observed_freq"  in b
            assert "count"          in b

    def test_observed_freq_in_0_1(self):
        preds   = [{"home_win": i / 10, "draw": 0.3, "away_win": 0.7 - i / 10}
                   for i in range(10)]
        actuals = ["home_win" if i < 5 else "away_win" for i in range(10)]
        cal = calibration_data(preds, actuals)
        for b in cal:
            assert 0.0 <= b["observed_freq"] <= 1.0

    def test_counts_sum_to_n_predictions(self):
        n = 30
        preds   = [{"home_win": 0.4, "draw": 0.3, "away_win": 0.3}] * n
        actuals = ["home_win"] * n
        cal = calibration_data(preds, actuals, n_bins=10)
        assert sum(b["count"] for b in cal) == n


# ===========================================================================
# 2. Backtesting
# ===========================================================================

class TestBacktesting:
    def test_returns_dict_per_model(self, db_pipe):
        from app.services.evaluation.backtesting import run_backtesting
        result = run_backtesting(
            db_pipe,
            models=["baseline", "elo", "poisson"],
            start_year=2020,
        )
        assert isinstance(result, dict)
        for model in ["baseline", "elo", "poisson"]:
            assert model in result
            assert "brier_score" in result[model]
            assert "n_matches" in result[model]

    def test_metrics_in_valid_ranges(self, db_pipe):
        from app.services.evaluation.backtesting import run_backtesting
        result = run_backtesting(db_pipe, models=["poisson"], start_year=2020)
        if not result:
            pytest.skip("No backtesting data")
        m = result["poisson"]
        assert 0.0 <= m["brier_score"] <= 1.0
        assert m["log_loss"] >= 0.0
        assert 0.0 <= m["rps"] <= 1.0
        assert 0.0 <= m["accuracy"] <= 1.0

    def test_calibration_data_has_10_bins(self, db_pipe):
        from app.services.evaluation.backtesting import run_backtesting
        result = run_backtesting(db_pipe, models=["baseline"], start_year=2020)
        if not result:
            pytest.skip("No backtesting data")
        assert len(result["baseline"]["calibration_data"]) == 10

    def test_empty_db_returns_empty_dict(self):
        conn = _make_db()
        conn.commit()
        from app.services.evaluation.backtesting import run_backtesting
        result = run_backtesting(conn, models=["baseline"])
        assert result == {}
        conn.close()

    def test_stores_evaluations_in_db(self, db_pipe):
        from app.db.repositories.evaluations import EvaluationRepository
        from app.services.evaluation.backtesting import run_backtesting
        run_backtesting(db_pipe, models=["elo"], start_year=2023)
        rows = EvaluationRepository(db_pipe).get_by_model("elo")
        assert len(rows) >= 1

    def test_exports_calibration_json(self, db_pipe, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.DATA_EXPORTS_PATH", str(tmp_path))
        from app.services.evaluation.backtesting import run_backtesting
        run_backtesting(db_pipe, models=["poisson"], start_year=2020)
        cal_file = tmp_path / "calibration_poisson.json"
        assert cal_file.exists()


# ===========================================================================
# 3. Pipeline — full refresh fault tolerance
# ===========================================================================

class TestFullRefreshPipeline:
    def _make_job(self, conn) -> str:
        from app.db.repositories.jobs import JobRepository
        job_id = JobRepository(conn).create({
            "job_type": "full_refresh",
            "status": "enqueued",
        })
        conn.commit()
        return job_id

    def test_full_refresh_completes_with_small_dataset(
        self, db_pipe, tmp_path, monkeypatch
    ):
        """Pipeline should complete without error on a small in-memory DB."""
        monkeypatch.setattr("app.core.config.settings.ML_MODELS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.DATA_EXPORTS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.MONTECARLO_ITERATIONS", 20)

        # Stub out network / I/O steps that require real files or internet
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_teams_from_csv", lambda: 1
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_groups_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_fixtures_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_ratings_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_historical_results_from_csv", lambda **kw: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.elo_scraper.ingest_elo_ratings", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.api_football.ingest_api_fixtures",
            lambda **kw: 0,
        )
        monkeypatch.setattr(
            "app.services.news.availability.run_news_analysis",
            lambda conn: {"analyzed": 0},
        )

        from app.services.jobs.pipeline import run_full_refresh
        job_id = self._make_job(db_pipe)
        result = run_full_refresh(db_pipe, job_id)

        assert result is not None
        assert "simulations" in result
        assert "snapshot" in result

    def test_news_failure_is_tolerated(self, db_pipe, tmp_path, monkeypatch):
        """If news analysis raises, the pipeline should continue."""
        monkeypatch.setattr("app.core.config.settings.ML_MODELS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.DATA_EXPORTS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.MONTECARLO_ITERATIONS", 20)

        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_teams_from_csv", lambda: 1
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_groups_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_fixtures_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_ratings_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_historical_results_from_csv", lambda **kw: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.elo_scraper.ingest_elo_ratings", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.api_football.ingest_api_fixtures", lambda **kw: 0
        )
        # Make news analysis raise an exception
        monkeypatch.setattr(
            "app.services.news.availability.run_news_analysis",
            lambda conn: (_ for _ in ()).throw(RuntimeError("News service down")),
        )

        from app.services.jobs.pipeline import run_full_refresh
        job_id = self._make_job(db_pipe)
        result = run_full_refresh(db_pipe, job_id)

        assert result["news"]["status"] == "failed"
        assert "simulations" in result  # Pipeline continued after news failure

    def test_ml_failure_is_tolerated_and_base_models_run(
        self, db_pipe, tmp_path, monkeypatch
    ):
        """If ML training fails, base model simulations should still complete."""
        monkeypatch.setattr("app.core.config.settings.ML_MODELS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.DATA_EXPORTS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.MONTECARLO_ITERATIONS", 20)

        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_teams_from_csv", lambda: 1
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_groups_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_fixtures_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_ratings_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_historical_results_from_csv", lambda **kw: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.elo_scraper.ingest_elo_ratings", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.api_football.ingest_api_fixtures", lambda **kw: 0
        )
        monkeypatch.setattr(
            "app.services.news.availability.run_news_analysis",
            lambda conn: {"analyzed": 0},
        )
        # Make ML training raise
        monkeypatch.setattr(
            "app.services.ml.trainer.train_ml_model",
            lambda conn, **kw: (_ for _ in ()).throw(ValueError("Not enough data")),
        )

        from app.services.jobs.pipeline import run_full_refresh
        job_id = self._make_job(db_pipe)
        result = run_full_refresh(db_pipe, job_id)

        assert result["ml_training"]["status"] == "failed"
        # Pipeline must reach the simulation step (results present for each model)
        # Simulations may fail in tests due to missing WC2026 teams in test DB,
        # but the pipeline should not abort — all models must be attempted.
        sims = result["simulations"]
        for base_model in ["baseline", "elo", "poisson"]:
            assert base_model in sims, f"Model {base_model} not in simulation results"


# ===========================================================================
# 4. Pipeline task (RQ task — sync test)
# ===========================================================================

class TestPipelineTasks:
    def test_full_refresh_task_sync(self, db_pipe, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.ML_MODELS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.DATA_EXPORTS_PATH", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.MONTECARLO_ITERATIONS", 20)

        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_teams_from_csv", lambda: 1
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_groups_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_fixtures_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_ratings_from_csv", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.csv_loader.load_historical_results_from_csv", lambda **kw: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.elo_scraper.ingest_elo_ratings", lambda: 0
        )
        monkeypatch.setattr(
            "app.services.ingestion.api_football.ingest_api_fixtures", lambda **kw: 0
        )
        monkeypatch.setattr(
            "app.services.news.availability.run_news_analysis",
            lambda conn: {"analyzed": 0},
        )

        from app.db.repositories.jobs import JobRepository
        from app.workers.tasks import run_full_refresh_task

        job_id = JobRepository(db_pipe).create({
            "job_type": "full_refresh", "status": "enqueued"
        })
        db_pipe.commit()

        result = run_full_refresh_task(job_id, _conn=db_pipe)
        assert result is not None

        row = db_pipe.execute(
            "SELECT status, progress FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        assert row["status"] == "completed"
        assert row["progress"] == pytest.approx(1.0)
