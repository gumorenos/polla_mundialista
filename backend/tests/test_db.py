"""DB integration tests — run against an in-memory SQLite database.

All repositories receive the same in-memory connection so FK constraints
and cross-table queries are exercised without touching the filesystem.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from app.db.migrations import run_migrations
from app.db.repositories.availability import AvailabilityRepository
from app.db.repositories.evaluations import EvaluationRepository
from app.db.repositories.fixtures import FixtureRepository, ResultRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.ml import MLRepository
from app.db.repositories.predictions import PredictionRepository
from app.db.repositories.ratings import RatingRepository
from app.db.repositories.simulations import SimulationRepository
from app.db.repositories.strengths import StrengthRepository
from app.db.repositories.teams import TeamRepository


# ---------------------------------------------------------------------------
# Fixture: shared in-memory DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_team(db, name="Brazil", team_id="BRA") -> str:
    repo = TeamRepository(db)
    repo.upsert({"id": team_id, "name": name, "confederation": "CONMEBOL"})
    db.commit()
    return team_id


def _seed_fixture(db, fixture_id="F001", home="BRA", away="ARG") -> str:
    repo = FixtureRepository(db)
    repo.upsert({
        "id": fixture_id,
        "stage": "group",
        "home_team_id": home,
        "away_team_id": away,
        "match_date": "2026-06-15",
    })
    db.commit()
    return fixture_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMigrations:
    def test_all_tables_exist(self, db):
        expected = {
            "teams", "groups", "group_teams", "fixtures", "results",
            "ratings", "team_strengths",
            "availability_claims", "team_context_adjustments",
            "prediction_runs", "match_predictions",
            "simulation_runs", "simulation_team_results",
            "jobs", "job_logs",
            "ml_training_runs", "ml_models", "ml_feature_snapshots",
            "model_evaluations",
            "data_sources", "snapshots",
        }
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        existing = {r["name"] for r in rows}
        assert expected <= existing, f"Missing tables: {expected - existing}"

    def test_idempotent(self, db):
        """Running migrations twice must not raise."""
        run_migrations(db)


class TestTeamRepository:
    def test_upsert_and_get(self, db):
        repo = TeamRepository(db)
        repo.upsert({"id": "ESP", "name": "Spain", "confederation": "UEFA"})
        db.commit()
        team = repo.get_by_id("ESP")
        assert team is not None
        assert team["name"] == "Spain"

    def test_get_by_name(self, db):
        repo = TeamRepository(db)
        result = repo.get_by_name("Spain")
        assert result is not None
        assert result["id"] == "ESP"

    def test_list_all(self, db):
        repo = TeamRepository(db)
        teams = repo.list_all()
        assert any(t["id"] == "ESP" for t in teams)

    def test_upsert_update(self, db):
        repo = TeamRepository(db)
        repo.upsert({"id": "ESP", "name": "Spain", "confederation": "UEFA", "is_host": True})
        db.commit()
        team = repo.get_by_id("ESP")
        assert team["is_host"] == 1


class TestFixtureRepository:
    def setup_method(self):
        pass

    def test_upsert_and_get(self, db):
        _seed_team(db, "Brazil", "BRA")
        _seed_team(db, "Argentina", "ARG")
        fixture_id = _seed_fixture(db, "F001", "BRA", "ARG")
        repo = FixtureRepository(db)
        f = repo.get_by_id(fixture_id)
        assert f is not None
        assert f["stage"] == "group"

    def test_list_by_stage(self, db):
        repo = FixtureRepository(db)
        fixtures = repo.list_by_stage("group")
        assert len(fixtures) >= 1

    def test_list_by_group(self, db):
        repo = FixtureRepository(db)
        # group_id is None for seeded fixture — returns empty list
        fixtures = repo.list_by_group("A")
        assert isinstance(fixtures, list)


class TestResultRepository:
    def test_insert_and_list(self, db):
        _seed_team(db, "Brazil", "BRA")
        _seed_team(db, "Germany", "GER")
        repo = ResultRepository(db)
        repo.insert({
            "home_team_id": "BRA",
            "away_team_id": "GER",
            "home_goals": 7,
            "away_goals": 1,
            "outcome": "W",
            "match_date": "2014-07-08",
            "tournament": "WC2014",
            "is_wc": True,
        })
        db.commit()
        results = repo.list_by_team("BRA")
        assert any(r["home_goals"] == 7 for r in results)

    def test_list_since_date(self, db):
        repo = ResultRepository(db)
        results = repo.list_since_date("2014-01-01", team_id="BRA")
        assert len(results) >= 1


class TestRatingRepository:
    def test_upsert_elo_and_get(self, db):
        _seed_team(db, "France", "FRA")
        repo = RatingRepository(db)
        repo.upsert_elo("FRA", 2070.0, "2026-01-01")
        db.commit()
        rating = repo.get_latest("FRA", "elo")
        assert rating is not None
        assert abs(rating["value"] - 2070.0) < 0.01

    def test_upsert_fifa_and_get(self, db):
        repo = RatingRepository(db)
        repo.upsert_fifa("FRA", 1850.0, rank=2, effective_date="2026-01-01")
        db.commit()
        rating = repo.get_latest("FRA", "fifa")
        assert rating is not None
        assert rating["rank"] == 2

    def test_list_latest_all(self, db):
        repo = RatingRepository(db)
        all_elo = repo.list_latest_all("elo")
        assert any(r["team_id"] == "FRA" for r in all_elo)


class TestStrengthRepository:
    def test_upsert_and_get(self, db):
        _seed_team(db, "Germany", "GER")
        repo = StrengthRepository(db)
        repo.upsert({
            "team_id": "GER",
            "attack_strength": 1.45,
            "defense_vulnerability": 0.80,
            "matches_used": 30,
            "cutoff_date": "2026-01-01",
            "decay_factor": 0.001,
        })
        db.commit()
        s = repo.get_by_team("GER")
        assert s is not None
        assert abs(s["attack_strength"] - 1.45) < 0.001

    def test_get_all(self, db):
        repo = StrengthRepository(db)
        all_s = repo.get_all()
        assert any(s["team_id"] == "GER" for s in all_s)


class TestAvailabilityRepository:
    def test_insert_and_get_active(self, db):
        _seed_team(db, "Brazil", "BRA")
        repo = AvailabilityRepository(db)
        repo.insert_claim({
            "team_id": "BRA",
            "player_name": "Vinicius Jr",
            "player_key": "vinicius_jr",
            "status": "injured",
            "observed_at": "2026-06-10T12:00:00Z",
            "confidence": 0.9,
        })
        db.commit()
        claims = repo.get_active_by_team("BRA", days_lookback=365)
        assert any(c["player_key"] == "vinicius_jr" for c in claims)

    def test_get_by_player(self, db):
        repo = AvailabilityRepository(db)
        claims = repo.get_by_player("vinicius_jr")
        assert len(claims) >= 1


class TestPredictionRepository:
    def test_create_run_and_insert_prediction(self, db):
        pred_repo = PredictionRepository(db)
        run_id = pred_repo.create_run({
            "model_set": "all",
            "data_version_hash": "abc123",
        })
        db.commit()

        pred_id = pred_repo.insert_prediction({
            "run_id": run_id,
            "fixture_id": "F001",
            "model_name": "poisson",
            "home_win": 0.55,
            "draw": 0.25,
            "away_win": 0.20,
        })
        db.commit()

        assert pred_id is not None
        preds = pred_repo.get_by_model("poisson", run_id=run_id)
        assert len(preds) == 1
        assert abs(preds[0]["home_win"] - 0.55) < 0.001

    def test_get_latest_run(self, db):
        repo = PredictionRepository(db)
        run = repo.get_latest_run()
        assert run is not None
        assert run["model_set"] == "all"


class TestSimulationRepository:
    def test_create_run_and_insert_result(self, db):
        sim_repo = SimulationRepository(db)
        run_id = sim_repo.create_run({
            "model_name": "poisson",
            "iterations": 30_000,
            "seed": 42,
        })
        db.commit()

        _seed_team(db, "Brazil", "BRA")
        res_id = sim_repo.insert_team_result({
            "simulation_run_id": run_id,
            "team_id": "BRA",
            "win_tournament": 0.18,
            "reach_final": 0.35,
            "qualify": 0.92,
        })
        db.commit()

        assert res_id is not None
        summary = sim_repo.get_run_summary(run_id)
        assert summary["run"]["id"] == run_id
        assert any(r["team_id"] == "BRA" for r in summary["team_results"])

    def test_get_latest_by_model_returns_none_when_pending(self, db):
        repo = SimulationRepository(db)
        result = repo.get_latest_by_model("poisson")
        # Status is 'pending' so no finished run yet
        assert result is None


class TestJobRepository:
    def test_create_and_update(self, db):
        repo = JobRepository(db)
        job_id = repo.create({"job_type": "simulation", "rq_job_id": "rq-abc"})
        db.commit()

        job = repo.get_by_id(job_id)
        assert job is not None
        assert job["status"] == "enqueued"

        repo.update_status(job_id, "started", started_at="2026-06-12T10:00:00Z")
        db.commit()
        job = repo.get_by_id(job_id)
        assert job["status"] == "started"

    def test_update_progress(self, db):
        repo = JobRepository(db)
        job_id = repo.create({"job_type": "ml_train"})
        db.commit()
        repo.update_progress(job_id, 0.5)
        db.commit()
        job = repo.get_by_id(job_id)
        assert abs(job["progress"] - 0.5) < 0.001

    def test_list_recent(self, db):
        repo = JobRepository(db)
        jobs = repo.list_recent(10)
        assert len(jobs) >= 1


class TestMLRepository:
    def test_create_training_run_and_save_model(self, db):
        repo = MLRepository(db)
        run_id = repo.create_training_run({
            "algorithm": "lightgbm",
            "train_start_year": 2010,
            "validation_split": 0.2,
        })
        db.commit()

        model_id = repo.save_model_path(
            run_id,
            "lightgbm",
            "data/processed/models/lgbm_v1.pkl",
            metrics={"brier_score": 0.19, "log_loss": 0.55, "accuracy": 0.65},
        )
        db.commit()

        assert model_id is not None
        # Activate and retrieve
        repo.set_active_model(model_id)
        db.commit()
        best = repo.get_best_model()
        assert best is not None
        assert best["id"] == model_id


class TestEvaluationRepository:
    def test_insert_and_get(self, db):
        repo = EvaluationRepository(db)
        for i in range(3):
            repo.insert_evaluation({
                "model_name": "elo",
                "eval_set": "wc_2022",
                "n_matches": 48,
                "brier_score": 0.22 + i * 0.01,
                "log_loss": 0.9 + i * 0.05,
                "rps": 0.15,
                "accuracy": 0.60,
            })
        db.commit()

        evals = repo.get_by_model("elo")
        assert len(evals) == 3

    def test_aggregate_metrics(self, db):
        repo = EvaluationRepository(db)
        agg = repo.compute_aggregate_metrics("elo")
        assert agg["n_evaluations"] == 3
        assert agg["avg_brier"] is not None


class TestNoSQLOutsideDB:
    """Verify SQL is only written inside app/db/."""

    def test_no_raw_sql_in_service_layer(self):
        root = Path(__file__).parent.parent / "app"
        patterns = ["CREATE TABLE", "INSERT INTO", "SELECT * FROM", "UPDATE ", "DELETE FROM"]

        violations: list[str] = []
        for py_file in root.rglob("*.py"):
            # Only check files outside app/db/
            rel = py_file.relative_to(root)
            if rel.parts[0] == "db":
                continue
            text = py_file.read_text(encoding="utf-8")
            if any(p in text for p in patterns):
                violations.append(str(rel))

        assert violations == [], (
            f"Raw SQL found outside app/db/ in: {violations}"
        )
