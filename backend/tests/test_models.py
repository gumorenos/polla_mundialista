"""Tests for all statistical prediction models."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from app.db.migrations import run_migrations


# ---------------------------------------------------------------------------
# Shared DB helpers
# ---------------------------------------------------------------------------

def _empty_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


def _insert_team(conn, tid: str, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (tid, name))


def _insert_strength(conn, team_id: str, attack: float, defense: float) -> None:
    conn.execute(
        """
        INSERT INTO team_strengths
            (id, team_id, attack_strength, defense_vulnerability, matches_used,
             cutoff_date, decay_factor)
        VALUES (?, ?, ?, ?, 10, '2025-01-01', 0.001)
        """,
        (str(uuid.uuid4()), team_id, attack, defense),
    )


def _insert_elo(conn, team_id: str, value: float) -> None:
    conn.execute(
        """
        INSERT INTO ratings
            (id, team_id, rating_type, value, effective_date, source)
        VALUES (?, ?, 'elo', ?, '2025-01-01', 'test')
        """,
        (str(uuid.uuid4()), team_id, value),
    )


def _insert_result(conn, home_id: str, away_id: str, hg: int, ag: int) -> None:
    outcome = "W" if hg > ag else ("D" if hg == ag else "L")
    conn.execute(
        """
        INSERT INTO results
            (id, home_team_id, away_team_id, home_goals, away_goals, match_date, outcome)
        VALUES (?, ?, ?, ?, ?, '2024-06-01', ?)
        """,
        (str(uuid.uuid4()), home_id, away_id, hg, ag, outcome),
    )


# ---------------------------------------------------------------------------
# Module-scoped fixture: realistic DB with contrasting teams + history
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_models() -> sqlite3.Connection:
    """Two teams: BRA (strong) and SMR (weak), with ELO + strengths + results."""
    conn = _empty_db()

    _insert_team(conn, "BRA", "Brasil")
    _insert_team(conn, "SMR", "San Marino")
    _insert_team(conn, "ARG", "Argentina")

    _insert_strength(conn, "BRA", attack=1.8, defense=0.6)
    _insert_strength(conn, "SMR", attack=0.3, defense=2.5)
    _insert_strength(conn, "ARG", attack=1.7, defense=0.7)

    _insert_elo(conn, "BRA", 2030.0)
    _insert_elo(conn, "SMR", 1200.0)
    _insert_elo(conn, "ARG", 2074.0)

    # Some historical results for baseline and draw-rate computation
    for hg, ag in [(2, 1), (1, 0), (3, 2), (1, 1), (0, 0), (2, 2), (0, 1), (1, 2)]:
        _insert_result(conn, "BRA", "ARG", hg, ag)

    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helper: assert probabilities sum to 1
# ---------------------------------------------------------------------------

def _assert_probs_sum_to_one(pred: dict, tol: float = 1e-6) -> None:
    total = pred["home_win"] + pred["draw"] + pred["away_win"]
    assert abs(total - 1.0) <= tol, f"Probabilities sum to {total}, expected 1.0"


# ---------------------------------------------------------------------------
# 1. All models return probabilities that sum to 1.0 ± 1e-6
# ---------------------------------------------------------------------------

class TestProbabilitiesSumToOne:
    def test_baseline_sums_to_one(self, db_models):
        from app.services.prediction.baseline import BaselineModel
        pred = BaselineModel(db_models).predict_match("BRA", "SMR")
        _assert_probs_sum_to_one(pred)

    def test_elo_sums_to_one(self, db_models):
        from app.services.prediction.elo_model import EloModel
        pred = EloModel(db_models).predict_match("BRA", "SMR")
        _assert_probs_sum_to_one(pred)

    def test_poisson_sums_to_one(self, db_models):
        from app.services.prediction.poisson_model import PoissonModel
        pred = PoissonModel(db_models).predict_match("BRA", "SMR")
        _assert_probs_sum_to_one(pred)

    def test_poisson_context_sums_to_one(self, db_models):
        from app.services.prediction.poisson_context import PoissonContextModel
        pred = PoissonContextModel(db_models).predict_match("BRA", "SMR")
        _assert_probs_sum_to_one(pred)


# ---------------------------------------------------------------------------
# 2. poisson_model: strong team vs weak team → P_win_strong > 0.90
# ---------------------------------------------------------------------------

class TestPoissonDominance:
    def test_brasil_vs_san_marino_home_win_over_90_pct(self, db_models):
        from app.services.prediction.poisson_model import PoissonModel
        pred = PoissonModel(db_models).predict_match("BRA", "SMR")
        assert pred["home_win"] > 0.90, (
            f"Expected P(BRA wins) > 0.90, got {pred['home_win']:.3f}"
        )


# ---------------------------------------------------------------------------
# 3. poisson_model: rho=0 → Dixon-Coles does not change the matrix
# ---------------------------------------------------------------------------

class TestDixonColesRhoZero:
    def test_rho_zero_leaves_matrix_unchanged(self):
        from app.services.prediction.poisson_model import _compute_probability_matrix
        import math

        lam_h, lam_a, max_goals = 1.5, 1.2, 8

        # Matrix with rho=0 (DC correction multipliers are all 1.0)
        matrix_dc0 = _compute_probability_matrix(lam_h, lam_a, 0.0, max_goals)

        # Manually compute raw Poisson matrix
        def pois(k, lam):
            return math.exp(-lam) * (lam ** k) / math.factorial(k)

        for i, row in enumerate(matrix_dc0):
            for j, p in enumerate(row):
                expected = pois(i, lam_h) * pois(j, lam_a)
                # normalisation from truncation at max_goals causes tiny deviation
                assert abs(p - expected) < 1e-4, (
                    f"Cell ({i},{j}): expected {expected:.6f}, got {p:.6f}"
                )


# ---------------------------------------------------------------------------
# 4. elo_model: +300 ELO → P_win > 0.65
# ---------------------------------------------------------------------------

class TestEloAdvantage:
    def test_300_elo_advantage_gives_over_65_pct_win(self, db_models):
        from app.services.prediction.elo_model import EloModel
        # BRA (2030) vs SMR (1200) — delta = 830 ELO → well over threshold
        pred = EloModel(db_models).predict_match("BRA", "SMR")
        assert pred["home_win"] > 0.65, (
            f"Expected P_win > 0.65 for +830 ELO, got {pred['home_win']:.3f}"
        )

    def test_exactly_300_elo_advantage(self):
        """Isolated test using teams with exactly ΔElo = +300."""
        conn = _empty_db()
        _insert_team(conn, "STRONG", "Strong FC")
        _insert_team(conn, "WEAK",   "Weak FC")
        _insert_elo(conn, "STRONG", 1800.0)
        _insert_elo(conn, "WEAK",   1500.0)
        conn.commit()

        from app.services.prediction.elo_model import EloModel
        pred = EloModel(conn, draw_rate=0.25).predict_match("STRONG", "WEAK")
        assert pred["home_win"] > 0.65, (
            f"Expected P_win > 0.65 for +300 ELO, got {pred['home_win']:.3f}"
        )
        _assert_probs_sum_to_one(pred)
        conn.close()


# ---------------------------------------------------------------------------
# 5. baseline: with history, does not return exactly 1/3
# ---------------------------------------------------------------------------

class TestBaseline:
    def test_not_uniform_when_history_exists(self, db_models):
        from app.services.prediction.baseline import BaselineModel
        pred = BaselineModel(db_models).predict_match("BRA", "SMR")
        # Historical data has unequal W/D/L counts → not all exactly 1/3
        assert pred["home_win"] != pytest.approx(1 / 3)

    def test_uniform_when_no_history(self):
        conn = _empty_db()
        conn.commit()
        from app.services.prediction.baseline import BaselineModel
        pred = BaselineModel(conn).predict_match("BRA", "SMR")
        assert pred["home_win"] == pytest.approx(1 / 3)
        assert pred["draw"]     == pytest.approx(1 / 3)
        assert pred["away_win"] == pytest.approx(1 / 3)
        conn.close()


# ---------------------------------------------------------------------------
# 6. poisson_context: confirmed injury reduces lam_home
# ---------------------------------------------------------------------------

class TestPoissonContextInjury:
    def test_injury_reduces_expected_home_goals(self):
        conn = _empty_db()
        _insert_team(conn, "HOME", "Home Team")
        _insert_team(conn, "AWAY", "Away Team")
        _insert_strength(conn, "HOME", attack=1.5, defense=0.8)
        _insert_strength(conn, "AWAY", attack=1.0, defense=1.0)
        conn.commit()

        from app.services.prediction.poisson_context import PoissonContextModel
        model = PoissonContextModel(conn)

        # Prediction without any injuries
        pred_before = model.predict_match("HOME", "AWAY")

        # Insert an injury claim for the home team (affects_prediction=1)
        conn.execute(
            """
            INSERT INTO availability_claims
                (id, team_id, player_name, status, observed_at, affects_prediction)
            VALUES (?, 'HOME', 'Star Striker', 'injured', ?, 1)
            """,
            (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        # Prediction with injury in place
        pred_after = model.predict_match("HOME", "AWAY")

        assert pred_after["expected_home_goals"] < pred_before["expected_home_goals"], (
            f"Injury should reduce lam_home: "
            f"before={pred_before['expected_home_goals']:.3f} "
            f"after={pred_after['expected_home_goals']:.3f}"
        )
        conn.close()


# ---------------------------------------------------------------------------
# 7. All models handle missing team_strengths gracefully (no crash)
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def _make_db_no_strengths(self) -> sqlite3.Connection:
        conn = _empty_db()
        _insert_team(conn, "X", "Team X")
        _insert_team(conn, "Y", "Team Y")
        conn.commit()
        return conn

    def test_baseline_no_crash(self):
        conn = self._make_db_no_strengths()
        from app.services.prediction.baseline import BaselineModel
        pred = BaselineModel(conn).predict_match("X", "Y")
        _assert_probs_sum_to_one(pred)
        conn.close()

    def test_elo_no_crash(self):
        conn = self._make_db_no_strengths()
        from app.services.prediction.elo_model import EloModel
        pred = EloModel(conn).predict_match("X", "Y")
        _assert_probs_sum_to_one(pred)
        assert "elo_home" in pred["features_missing"]
        conn.close()

    def test_poisson_no_crash(self):
        conn = self._make_db_no_strengths()
        from app.services.prediction.poisson_model import PoissonModel
        pred = PoissonModel(conn).predict_match("X", "Y")
        _assert_probs_sum_to_one(pred)
        assert "team_strengths_home" in pred["features_missing"]
        assert "team_strengths_away" in pred["features_missing"]
        conn.close()

    def test_poisson_context_no_crash(self):
        conn = self._make_db_no_strengths()
        from app.services.prediction.poisson_context import PoissonContextModel
        pred = PoissonContextModel(conn).predict_match("X", "Y")
        _assert_probs_sum_to_one(pred)
        conn.close()
