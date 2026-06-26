"""Tests for StatsBomb Open Data ingestion.

All tests use synthetic in-memory data — no actual StatsBomb files required.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.db.migrations import run_migrations
from app.services.ingestion.statsbomb_loader import (
    STATSBOMB_ALIASES,
    _normalize_sb_team,
    load_all_wc_matches,
    load_statsbomb_competitions,
    parse_match_events,
)


@pytest.fixture
def mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# parse_match_events
# ---------------------------------------------------------------------------

def test_parse_match_events_calcula_xg():
    """xG is summed correctly; shots_on_target counts only Saved and Goal."""
    events = [
        {
            "type": {"name": "Shot"},
            "team": {"name": "France"},
            "shot": {"statsbomb_xg": 0.15, "outcome": {"name": "Saved"}},
        },
        {
            "type": {"name": "Shot"},
            "team": {"name": "France"},
            "shot": {"statsbomb_xg": 0.45, "outcome": {"name": "Goal"}},
        },
        {
            "type": {"name": "Shot"},
            "team": {"name": "Croatia"},
            "shot": {"statsbomb_xg": 0.08, "outcome": {"name": "Off T"}},
        },
        {
            "type": {"name": "Pass"},
            "team": {"name": "France"},
            "pass": {"outcome": None},  # successful pass
        },
    ]
    stats = parse_match_events(events)

    assert "France" in stats
    assert abs(stats["France"]["xg"] - 0.60) < 0.01
    assert stats["France"]["shots"] == 2
    assert stats["France"]["shots_on_target"] == 2  # Saved + Goal
    assert stats["France"]["passes_completed"] == 1
    assert stats["France"]["passes_total"] == 1

    assert "Croatia" in stats
    assert abs(stats["Croatia"]["xg"] - 0.08) < 0.01
    assert stats["Croatia"]["shots_on_target"] == 0  # Off T is not on target


def test_parse_match_events_possession():
    """Possession equals share of total events per team."""
    events = [
        {"type": {"name": "Pass"}, "team": {"name": "Spain"}, "pass": {"outcome": None}},
        {"type": {"name": "Pass"}, "team": {"name": "Spain"}, "pass": {"outcome": None}},
        {"type": {"name": "Pass"}, "team": {"name": "Morocco"}, "pass": {"outcome": None}},
    ]
    stats = parse_match_events(events)
    assert abs(stats["Spain"]["possession"] - 66.7) < 1.0
    assert abs(stats["Morocco"]["possession"] - 33.3) < 1.0


def test_parse_match_events_pass_accuracy():
    """Pass accuracy is completed/total × 100."""
    events = [
        {"type": {"name": "Pass"}, "team": {"name": "Brazil"}, "pass": {"outcome": None}},
        {"type": {"name": "Pass"}, "team": {"name": "Brazil"}, "pass": {"outcome": None}},
        {"type": {"name": "Pass"}, "team": {"name": "Brazil"}, "pass": {"outcome": {"name": "Incomplete"}}},
    ]
    stats = parse_match_events(events)
    assert abs(stats["Brazil"]["pass_accuracy"] - 66.7) < 1.0


def test_parse_match_events_empty():
    """Empty event list returns empty dict without error."""
    assert parse_match_events([]) == {}


def test_parse_match_events_events_without_team_ignored():
    """Events with no team field do not cause errors."""
    events = [
        {"type": {"name": "Half Start"}},  # no team
        {"type": {"name": "Period End"}},   # no team
    ]
    assert parse_match_events(events) == {}


# ---------------------------------------------------------------------------
# load_statsbomb_competitions
# ---------------------------------------------------------------------------

def test_load_statsbomb_competitions_filtra_relevantes(tmp_path: Path):
    """Returns only competition_id=43 entries."""
    comps = [
        {"competition_id": 43, "season_id": 3, "competition_name": "FIFA World Cup", "season_name": "2018"},
        {"competition_id": 43, "season_id": 106, "competition_name": "FIFA World Cup", "season_name": "2022"},
        {"competition_id": 72, "season_id": 30, "competition_name": "Women's World Cup", "season_name": "2019"},
        {"competition_id": 11, "season_id": 1, "competition_name": "La Liga", "season_name": "2015/16"},
    ]
    (tmp_path / "competitions.json").write_text(json.dumps(comps))
    result = load_statsbomb_competitions(str(tmp_path))
    assert len(result) == 2
    assert all(c["competition_id"] == 43 for c in result)
    season_names = {c["season_name"] for c in result}
    assert season_names == {"2018", "2022"}


def test_load_statsbomb_competitions_archivo_no_existe(tmp_path: Path):
    """Returns empty list when competitions.json is absent."""
    result = load_statsbomb_competitions(str(tmp_path))
    assert result == []


def test_load_statsbomb_competitions_sin_wc(tmp_path: Path):
    """Returns empty list when no competition_id=43 exists."""
    (tmp_path / "competitions.json").write_text(json.dumps([
        {"competition_id": 1, "season_id": 1, "competition_name": "Serie A", "season_name": "2020/21"},
    ]))
    assert load_statsbomb_competitions(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# STATSBOMB_ALIASES coverage
# ---------------------------------------------------------------------------

def test_statsbomb_alias_cubre_equipos_wc_historicos():
    """STATSBOMB_ALIASES includes all team names from WC 2018 and WC 2022."""
    wc_teams = {
        # WC 2018
        "Russia", "Saudi Arabia", "Egypt", "Uruguay",
        "Portugal", "Spain", "Morocco", "Iran",
        "France", "Australia", "Peru", "Denmark",
        "Argentina", "Iceland", "Croatia", "Nigeria",
        "Brazil", "Switzerland", "Costa Rica", "Serbia",
        "Germany", "Mexico", "Sweden", "South Korea",
        "Belgium", "Panama", "Tunisia", "England",
        "Poland", "Senegal", "Colombia", "Japan",
        # WC 2022 additions
        "Qatar", "Ecuador", "Netherlands",
        "United States", "Wales", "Canada",
        "Cameroon", "Ghana",
    }
    missing = wc_teams - set(STATSBOMB_ALIASES.keys())
    assert not missing, f"Missing StatsBomb team names in STATSBOMB_ALIASES: {missing}"


# ---------------------------------------------------------------------------
# _normalize_sb_team
# ---------------------------------------------------------------------------

def test_normalize_team_name_statsbomb():
    """Known StatsBomb aliases map to the correct internal team codes."""
    assert _normalize_sb_team("France") == "FRA"
    assert _normalize_sb_team("Brazil") == "BRA"
    assert _normalize_sb_team("Korea Republic") == "KOR"
    assert _normalize_sb_team("IR Iran") == "IRN"
    assert _normalize_sb_team("United States") == "USA"
    assert _normalize_sb_team("Netherlands") == "NED"
    assert _normalize_sb_team("Saudi Arabia") == "KSA"


def test_normalize_team_name_unknown_devuelve_truncado():
    """Unknown names fall back to truncated string (max 20 chars)."""
    result = _normalize_sb_team("SomeUnknownNationThatIsVeryLong")
    assert len(result) <= 20


# ---------------------------------------------------------------------------
# load_all_wc_matches (integration with in-memory DB)
# ---------------------------------------------------------------------------

def _build_synthetic_data(tmp_path: Path) -> None:
    """Create minimal StatsBomb-format fixture files under tmp_path."""
    matches_dir = tmp_path / "matches" / "43"
    matches_dir.mkdir(parents=True)
    events_dir = tmp_path / "events"
    events_dir.mkdir()

    match = {
        "match_id": 9999,
        "match_date": "2022-12-18",
        "competition": {"competition_id": 43, "competition_name": "FIFA World Cup"},
        "season": {"season_id": 106, "season_name": "2022"},
        "home_team": {"home_team_name": "France"},
        "away_team": {"away_team_name": "Argentina"},
        "home_score": 3,
        "away_score": 3,
    }
    (matches_dir / "106.json").write_text(json.dumps([match]))

    events = [
        {
            "type": {"name": "Shot"},
            "team": {"name": "France"},
            "shot": {"statsbomb_xg": 0.7, "outcome": {"name": "Goal"}},
            "player": {"name": "Mbappé"},
            "position": {"name": "Left Wing"},
        },
        {
            "type": {"name": "Shot"},
            "team": {"name": "Argentina"},
            "shot": {"statsbomb_xg": 0.3, "outcome": {"name": "Saved"}},
            "player": {"name": "Messi"},
            "position": {"name": "Right Wing"},
        },
        {
            "type": {"name": "Pass"},
            "team": {"name": "France"},
            "pass": {"outcome": None},
            "player": {"name": "Griezmann"},
        },
        {
            "type": {"name": "Pass"},
            "team": {"name": "Argentina"},
            "pass": {"outcome": {"name": "Incomplete"}},
            "player": {"name": "Di María"},
        },
        {
            "type": {"name": "Pressure"},
            "team": {"name": "France"},
            "player": {"name": "Mbappé"},
        },
    ]
    (events_dir / "9999.json").write_text(json.dumps(events))


def test_load_all_wc_matches_inserta_partido(tmp_path: Path, mem_db: sqlite3.Connection):
    """A synthetic WC match is correctly inserted into sb_matches."""
    _build_synthetic_data(tmp_path)
    count = load_all_wc_matches(mem_db, str(tmp_path))
    assert count == 1

    row = mem_db.execute("SELECT * FROM sb_matches WHERE match_id=9999").fetchone()
    assert row is not None
    assert row["home_team_id"] == "FRA"
    assert row["away_team_id"] == "ARG"
    assert row["home_score"] == 3
    assert row["match_date"] == "2022-12-18"


def test_load_all_wc_matches_inserta_stats(tmp_path: Path, mem_db: sqlite3.Connection):
    """Team stats including xG and xG conceded are stored correctly."""
    _build_synthetic_data(tmp_path)
    load_all_wc_matches(mem_db, str(tmp_path))

    fra = mem_db.execute(
        "SELECT * FROM sb_match_stats WHERE match_id=9999 AND team_id='FRA'"
    ).fetchone()
    assert fra is not None
    assert abs(fra["xg"] - 0.7) < 0.01
    assert fra["shots"] == 1
    assert fra["is_home"] == 1
    assert fra["pressures"] == 1
    # France's xG conceded = Argentina's xG
    assert abs(fra["xg_conceded"] - 0.3) < 0.01

    arg = mem_db.execute(
        "SELECT * FROM sb_match_stats WHERE match_id=9999 AND team_id='ARG'"
    ).fetchone()
    assert arg is not None
    assert arg["shots_on_target"] == 1  # Saved = on target


def test_load_all_wc_matches_inserta_jugadores(tmp_path: Path, mem_db: sqlite3.Connection):
    """Player stats are inserted for players with Shot events."""
    _build_synthetic_data(tmp_path)
    load_all_wc_matches(mem_db, str(tmp_path))

    mbappe = mem_db.execute(
        "SELECT * FROM sb_player_stats WHERE match_id=9999 AND player_name='Mbappé'"
    ).fetchone()
    assert mbappe is not None
    assert mbappe["goals"] == 1
    assert mbappe["shots"] == 1
    assert abs(mbappe["xg"] - 0.7) < 0.01


def test_load_all_wc_matches_sin_directorio(tmp_path: Path, mem_db: sqlite3.Connection):
    """Returns 0 when the WC matches directory does not exist."""
    count = load_all_wc_matches(mem_db, str(tmp_path))
    assert count == 0


def test_load_all_wc_matches_sin_events(tmp_path: Path, mem_db: sqlite3.Connection):
    """Match is still inserted even when the events file is absent."""
    matches_dir = tmp_path / "matches" / "43"
    matches_dir.mkdir(parents=True)
    match = {
        "match_id": 8888,
        "match_date": "2018-07-15",
        "competition": {"competition_id": 43, "competition_name": "FIFA World Cup"},
        "season": {"season_id": 3, "season_name": "2018"},
        "home_team": {"home_team_name": "France"},
        "away_team": {"away_team_name": "Croatia"},
        "home_score": 4,
        "away_score": 2,
    }
    (matches_dir / "3.json").write_text(json.dumps([match]))
    # No events/ directory

    count = load_all_wc_matches(mem_db, str(tmp_path))
    assert count == 1
    row = mem_db.execute("SELECT match_id FROM sb_matches WHERE match_id=8888").fetchone()
    assert row is not None
