"""Tests for xG-based strength calculation and StatsBomb ML features."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.features.strengths import calculate_xg_strengths
from app.services.ml.feature_builder import (
    FEATURE_NAMES,
    _SB_DEFAULTS,
    compute_features,
    get_statsbomb_features,
    load_statsbomb_map,
)


@pytest.fixture
def mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('FRA', 'Francia', '2026-01-01')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('ARG', 'Argentina', '2026-01-01')"
    )
    conn.commit()
    yield conn
    conn.close()


def _insert_sb_match(conn, match_id, home_id, away_id, date="2022-12-01"):
    conn.execute(
        """INSERT OR IGNORE INTO sb_matches
           (match_id, competition_id, season_id, competition_name, season_name,
            match_date, home_team_id, away_team_id, home_score, away_score,
            home_team_sb, away_team_sb)
           VALUES (?, 43, 106, 'FIFA World Cup', '2022', ?, ?, ?, 2, 1, ?, ?)""",
        (match_id, date, home_id, away_id, home_id, away_id),
    )


def _insert_sb_stats(conn, match_id, team_id, is_home,
                     xg=1.5, xgc=0.8, shots=12, sot=5, poss=55.0,
                     passes_c=300, passes_t=350, pressures=120, dw=40, dt=70):
    row_id = f"{match_id}_{team_id}"
    conn.execute(
        """INSERT OR IGNORE INTO sb_match_stats
           (id, match_id, team_id, is_home, goals,
            xg, shots, shots_on_target, xg_conceded, shots_conceded,
            possession, passes_completed, passes_total, pass_accuracy,
            pressures, duels_won, duels_total)
           VALUES (?,?,?,?,2,?,?,?,?,5,?,?,?,?,?,?,?)""",
        (row_id, match_id, team_id, is_home,
         xg, shots, sot, xgc,
         poss, passes_c, passes_t, round(100 * passes_c / passes_t, 1),
         pressures, dw, dt),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# calculate_xg_strengths
# ---------------------------------------------------------------------------

def test_xg_strengths_returns_none_when_no_data(mem_db):
    """No StatsBomb data → None (caller uses goal-based fallback)."""
    result = calculate_xg_strengths("FRA", mem_db)
    assert result is None


def test_xg_strengths_returns_none_when_fewer_than_3_matches(mem_db):
    """< 3 matches → None."""
    for i in range(2):
        _insert_sb_match(mem_db, 1000 + i, "FRA", "ARG", f"2022-12-0{i+1}")
        _insert_sb_stats(mem_db, 1000 + i, "FRA", is_home=1)
    result = calculate_xg_strengths("FRA", mem_db)
    assert result is None


def test_xg_strengths_returns_values_with_sufficient_data(mem_db):
    """≥ 3 matches → returns dict with attack_xg, defense_xg, sample_size."""
    for i in range(5):
        mid = 2000 + i
        _insert_sb_match(mem_db, mid, "FRA", "ARG", f"2022-12-{i+1:02d}")
        _insert_sb_stats(mem_db, mid, "FRA", is_home=1, xg=1.8, xgc=0.6)
        _insert_sb_stats(mem_db, mid, "ARG", is_home=0, xg=0.6, xgc=1.8)

    result = calculate_xg_strengths("FRA", mem_db)
    assert result is not None
    assert "attack_xg" in result
    assert "defense_xg" in result
    assert result["sample_size"] == 5
    # FRA has high xG → attack_xg > 1.0
    assert result["attack_xg"] > 1.0
    # FRA concedes little → defense_xg < 1.0
    assert result["defense_xg"] < 1.0


def test_xg_strengths_clamped_to_bounds(mem_db):
    """Extreme values are clamped to [0.30, 3.00]."""
    for i in range(4):
        mid = 3000 + i
        _insert_sb_match(mem_db, mid, "FRA", "ARG", f"2022-12-{i+1:02d}")
        # Extremely high xG
        _insert_sb_stats(mem_db, mid, "FRA", is_home=1, xg=10.0, xgc=0.0)
        _insert_sb_stats(mem_db, mid, "ARG", is_home=0, xg=0.0, xgc=10.0)

    result = calculate_xg_strengths("FRA", mem_db)
    assert result is not None
    assert result["attack_xg"]  <= 3.0
    assert result["defense_xg"] >= 0.3


# ---------------------------------------------------------------------------
# get_statsbomb_features
# ---------------------------------------------------------------------------

def test_get_statsbomb_features_no_data(mem_db):
    """No StatsBomb data → returns default values with has_sb_data=0."""
    feat = get_statsbomb_features("FRA", mem_db)
    assert feat["has_sb_data"] == 0.0
    assert feat["avg_xg"] == _SB_DEFAULTS["avg_xg"]


def test_get_statsbomb_features_with_data(mem_db):
    """With StatsBomb data → returns real aggregated values."""
    for i in range(3):
        mid = 4000 + i
        _insert_sb_match(mem_db, mid, "FRA", "ARG", f"2022-12-{i+1:02d}")
        _insert_sb_stats(mem_db, mid, "FRA", is_home=1, xg=2.0, poss=60.0, shots=15, sot=6)

    feat = get_statsbomb_features("FRA", mem_db)
    assert feat["has_sb_data"] == 1.0
    assert abs(feat["avg_xg"] - 2.0) < 0.01
    assert abs(feat["avg_possession"] - 60.0) < 0.5
    # shot_accuracy = 6/15 = 0.4
    assert abs(feat["shot_accuracy"] - 0.4) < 0.01


# ---------------------------------------------------------------------------
# load_statsbomb_map
# ---------------------------------------------------------------------------

def test_load_statsbomb_map_empty(mem_db):
    """No data → empty dict."""
    assert load_statsbomb_map(mem_db) == {}


def test_load_statsbomb_map_includes_all_teams(mem_db):
    """Returns one entry per team that has sb_match_stats rows."""
    for tid, opp in [("FRA", "ARG"), ("ARG", "FRA")]:
        _insert_sb_match(mem_db, 5000, "FRA", "ARG", "2022-12-18")
        _insert_sb_stats(mem_db, 5000, tid, is_home=(tid == "FRA"))

    sb_map = load_statsbomb_map(mem_db)
    assert "FRA" in sb_map
    assert "ARG" in sb_map
    assert sb_map["FRA"]["has_sb_data"] == 1.0


# ---------------------------------------------------------------------------
# compute_features with StatsBomb features
# ---------------------------------------------------------------------------

def test_compute_features_length_matches_feature_names():
    """Feature vector length must equal len(FEATURE_NAMES)."""
    features, _ = compute_features(
        "FRA", "ARG",
        is_neutral=True,
        elo_map={},
        strength_map={},
        sb_map=None,
    )
    assert len(features) == len(FEATURE_NAMES), (
        f"Expected {len(FEATURE_NAMES)} features, got {len(features)}"
    )


def test_compute_features_uses_sb_map():
    """xG features from sb_map appear correctly in the feature vector."""
    sb_map = {
        "FRA": {**_SB_DEFAULTS, "avg_xg": 2.0, "has_sb_data": 1.0},
        "ARG": {**_SB_DEFAULTS, "avg_xg": 1.0, "avg_xg_conceded": 1.5, "has_sb_data": 1.0},
    }
    features, _ = compute_features(
        "FRA", "ARG",
        is_neutral=True,
        elo_map={},
        strength_map={},
        sb_map=sb_map,
    )
    fmap = dict(zip(FEATURE_NAMES, features))

    assert fmap["home_avg_xg"] == 2.0
    assert fmap["away_avg_xg"] == 1.0
    assert fmap["home_has_sb_data"] == 1.0
    # xg_difference = home_xg - away_xg = 2.0 - 1.0 = 1.0
    assert abs(fmap["xg_difference"] - 1.0) < 0.01
    # xg_defense_ratio = home_xg / away_xgc = 2.0 / 1.5 ≈ 1.333
    assert abs(fmap["xg_defense_ratio"] - (2.0 / 1.5)) < 0.01


def test_compute_features_defaults_when_no_sb_map():
    """Without sb_map, StatsBomb features use default values."""
    features, _ = compute_features(
        "FRA", "ARG",
        is_neutral=True,
        elo_map={},
        strength_map={},
        sb_map=None,
    )
    fmap = dict(zip(FEATURE_NAMES, features))
    assert fmap["home_has_sb_data"] == 0.0
    assert fmap["away_has_sb_data"] == 0.0
    assert fmap["home_avg_xg"] == _SB_DEFAULTS["avg_xg"]


# ---------------------------------------------------------------------------
# FEATURE_NAMES consistency
# ---------------------------------------------------------------------------

def test_feature_names_count():
    """FEATURE_NAMES has exactly 27 entries (11 original + 14 StatsBomb + 2 derived)."""
    assert len(FEATURE_NAMES) == 27, f"Got {len(FEATURE_NAMES)}: {FEATURE_NAMES}"


def test_feature_names_contain_sb_features():
    """Key StatsBomb feature names are present in FEATURE_NAMES."""
    for fname in ("home_avg_xg", "away_avg_xg", "xg_difference", "xg_defense_ratio",
                  "home_has_sb_data", "away_has_sb_data"):
        assert fname in FEATURE_NAMES, f"Missing: {fname}"
