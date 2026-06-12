"""Ingestion layer tests — all run against an in-memory SQLite DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.db.migrations import run_migrations
from app.db.repositories.teams import TeamRepository
from app.services.normalization.team_names import normalize_team_name

DATA_RAW = Path(__file__).parent.parent.parent / "data" / "raw"


# ---------------------------------------------------------------------------
# Module-scoped DB with teams pre-loaded (historical results need team stubs)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_loaded() -> sqlite3.Connection:
    """In-memory DB with teams loaded — used for historical/ratings tests."""
    from app.services.ingestion.csv_loader import load_teams_from_csv

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    # Pre-load teams so historical FK references resolve without stubs issues
    load_teams_from_csv(conn=conn)
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# 1. load_teams_from_csv — ≥ 48 teams
# ---------------------------------------------------------------------------

class TestLoadTeams:
    def test_loads_at_least_48_teams(self, db):
        from app.services.ingestion.csv_loader import load_teams_from_csv

        count = load_teams_from_csv(conn=db)
        assert count >= 48, f"Expected ≥ 48 teams, got {count}"

    def test_teams_persisted_in_db(self, db):
        repo = TeamRepository(db)
        teams = repo.list_all()
        assert len(teams) >= 48

    def test_argentina_has_correct_confederation(self, db):
        repo = TeamRepository(db)
        arg = repo.get_by_name("Argentina")
        assert arg is not None
        assert arg["confederation"] == "CONMEBOL"

    def test_idempotent(self, db):
        """Calling loader twice must not raise or duplicate rows."""
        from app.services.ingestion.csv_loader import load_teams_from_csv

        before = len(TeamRepository(db).list_all())
        load_teams_from_csv(conn=db)
        after = len(TeamRepository(db).list_all())
        assert after == before  # ON CONFLICT DO UPDATE — no new rows


# ---------------------------------------------------------------------------
# 2. load_historical_results_from_csv — ≥ 500 matches, valid data
# ---------------------------------------------------------------------------

class TestLoadHistoricalResults:
    def test_loads_at_least_500_matches(self, db_loaded):
        from app.services.ingestion.csv_loader import load_historical_results_from_csv

        count = load_historical_results_from_csv(conn=db_loaded)
        assert count >= 500, f"Expected ≥ 500, got {count}"

    def test_no_negative_goals(self, db_loaded):
        rows = db_loaded.execute(
            "SELECT * FROM results WHERE home_goals < 0 OR away_goals < 0"
        ).fetchall()
        assert len(rows) == 0, "Found rows with negative goals"

    def test_no_future_dates(self, db_loaded):
        from datetime import date

        today = date.today().isoformat()
        rows = db_loaded.execute(
            "SELECT * FROM results WHERE match_date > ?", (today,)
        ).fetchall()
        assert len(rows) == 0, f"Found {len(rows)} future-dated results"

    def test_outcomes_are_valid(self, db_loaded):
        rows = db_loaded.execute(
            "SELECT * FROM results WHERE outcome NOT IN ('W','D','L')"
        ).fetchall()
        assert len(rows) == 0, "Invalid outcome values found"

    def test_wc_results_present(self, db_loaded):
        rows = db_loaded.execute(
            "SELECT COUNT(*) as n FROM results WHERE is_wc = 1"
        ).fetchone()
        assert rows["n"] >= 64, "Expected at least 64 WC matches"


# ---------------------------------------------------------------------------
# 3. normalize_team_name — ≥ 10 known mappings
# ---------------------------------------------------------------------------

class TestNormalizeTeamName:
    @pytest.mark.parametrize("raw,expected", [
        ("United States",       "Estados Unidos"),
        ("USA",                 "Estados Unidos"),
        ("USMNT",               "Estados Unidos"),
        ("Ivory Coast",         "Costa de Marfil"),
        ("Côte d'Ivoire",       "Costa de Marfil"),
        ("South Korea",         "Corea del Sur"),
        ("Korea Republic",      "Corea del Sur"),
        ("IR Iran",             "Irán"),
        ("Netherlands",         "Países Bajos"),
        ("Holland",             "Países Bajos"),
        ("Germany",             "Alemania"),
        ("England",             "Inglaterra"),
        ("Brazil",              "Brasil"),
        ("Mexico",              "México"),
        ("Türkiye",             "Turquía"),
        # Already canonical — identity
        ("Argentina",           "Argentina"),
        ("Brasil",              "Brasil"),
        ("España",              "España"),
    ])
    def test_mapping(self, raw, expected):
        assert normalize_team_name(raw) == expected

    def test_unknown_name_returns_as_is(self):
        result = normalize_team_name("Neverland FC")
        assert result == "Neverland FC"

    def test_strips_whitespace(self):
        assert normalize_team_name("  Germany  ") == "Alemania"

    def test_case_insensitive_lookup(self):
        # "germany" (lowercase) should still map
        assert normalize_team_name("germany") == "Alemania"


# ---------------------------------------------------------------------------
# 4. ELO scraper — mock HTTP returns correct structure
# ---------------------------------------------------------------------------

class TestEloScraper:
    _FAKE_HTML = """
    <html><body>
    <table>
      <tr><td>1</td><td>Argentina</td><td>2074</td></tr>
      <tr><td>2</td><td>France</td><td>2056</td></tr>
      <tr><td>3</td><td>England</td><td>2036</td></tr>
      <tr><td>bad</td><td>Header</td><td>Row</td></tr>
    </table>
    </body></html>
    """

    def test_parse_html_returns_entries(self):
        from app.services.ingestion.elo_scraper import _parse_elo_html

        entries = _parse_elo_html(self._FAKE_HTML)
        assert len(entries) == 3
        assert entries[0].team == "Argentina"
        assert entries[0].elo == 2074
        assert entries[0].rank == 1

    def test_parse_normalizes_names(self):
        from app.services.ingestion.elo_scraper import _parse_elo_html

        html = "<table><tr><td>1</td><td>Netherlands</td><td>1970</td></tr></table>"
        entries = _parse_elo_html(html)
        assert entries[0].team == "Países Bajos"

    def test_scrape_falls_back_on_http_error(self):
        """If HTTP fails, scrape_elo_ratings() returns [] without crashing."""
        from app.services.ingestion.elo_scraper import scrape_elo_ratings

        with patch("app.services.ingestion.elo_scraper._fetch_html") as mock_fetch:
            mock_fetch.side_effect = Exception("Connection refused")
            result = scrape_elo_ratings()

        assert result == []

    def test_ingest_uses_csv_fallback_when_scrape_fails(self, db_loaded):
        """ingest_elo_ratings() falls back to CSV and persists data."""
        from app.services.ingestion.elo_scraper import ingest_elo_ratings

        with patch("app.services.ingestion.elo_scraper.scrape_elo_ratings", return_value=[]):
            count = ingest_elo_ratings(conn=db_loaded)

        assert count >= 48, f"Expected ≥ 48 ELO ratings from CSV fallback, got {count}"


# ---------------------------------------------------------------------------
# 5. load_ratings_from_csv — ELO + FIFA
# ---------------------------------------------------------------------------

class TestLoadRatings:
    def test_loads_elo_and_fifa(self, db_loaded):
        from app.services.ingestion.csv_loader import load_ratings_from_csv
        from app.db.repositories.ratings import RatingRepository

        count = load_ratings_from_csv(conn=db_loaded)
        assert count >= 96  # ≥ 48 ELO + ≥ 48 FIFA

        repo = RatingRepository(db_loaded)
        arg_elo = repo.get_latest("ARG", "elo")
        assert arg_elo is not None
        assert arg_elo["value"] > 2000


# ---------------------------------------------------------------------------
# 6. Admin endpoint — POST /api/admin/ingest
# ---------------------------------------------------------------------------

class TestAdminEndpoint:
    def test_ingest_enqueues_job(self):
        from fastapi.testclient import TestClient
        from app.main import app

        mock_job = MagicMock()
        mock_job.id = "ingest-job-xyz"

        with (
            patch("app.api.routes.admin.Redis"),
            patch("app.api.routes.admin.Queue") as MockQ,
        ):
            mock_q = MagicMock()
            mock_q.enqueue.return_value = mock_job
            MockQ.return_value = mock_q

            client = TestClient(app)
            response = client.post(
                "/api/admin/ingest",
                headers={"X-Admin-Token": ""},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "ingest-job-xyz"
        assert data["status"] == "enqueued"

    def test_ingest_requires_token_when_set(self):
        from fastapi.testclient import TestClient
        from app.main import app
        import app.api.routes.admin as admin_mod

        original = admin_mod.settings.ADMIN_TOKEN
        try:
            admin_mod.settings.ADMIN_TOKEN = "secret123"
            client = TestClient(app)
            response = client.post(
                "/api/admin/ingest",
                headers={"X-Admin-Token": "wrong"},
            )
            assert response.status_code == 403
        finally:
            admin_mod.settings.ADMIN_TOKEN = original
