"""API-Football (api-sports.io) client for fetching international fixtures.

Strategy:
1. Require API_FOOTBALL_KEY from settings — skip entirely if empty.
2. Request /fixtures for WC2026 league + recent fixtures.
3. Filter to senior national team matches (exclude U-20, U-23, Olympics).
4. Persist via ResultRepository.
5. Fallback to CSV historical if API call fails after retries.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date, timedelta
from typing import Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.fixtures import ResultRepository
from app.db.repositories.teams import TeamRepository
from app.services.normalization.team_names import normalize_team_name

logger = logging.getLogger(__name__)

_LEAGUE_WC2026 = 1       # FIFA World Cup league ID on api-sports.io
_SEASON_WC2026  = 2026

# Keywords that indicate non-senior matches — skip these
_EXCLUDE_KEYWORDS = {
    "U20", "U-20", "U21", "U-21", "U23", "U-23",
    "Under-20", "Under-23", "Olympic", "Olimpic",
    "Youth", "Friendly B",
}


def _is_senior(league_name: str) -> bool:
    return not any(kw.lower() in league_name.lower() for kw in _EXCLUDE_KEYWORDS)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _build_request_args(endpoint: str) -> tuple[str, dict[str, str]]:
    """Return (url, headers) for the configured API-Football variant."""
    if settings.API_FOOTBALL_RAPIDAPI:
        base = f"https://{settings.API_FOOTBALL_HOST}"
        headers = {
            "x-rapidapi-key":  settings.API_FOOTBALL_KEY,
            "x-rapidapi-host": settings.API_FOOTBALL_HOST,
            "Accept": "application/json",
        }
    else:
        base = settings.API_FOOTBALL_BASE_URL.rstrip("/")
        headers = {
            "x-apisports-key": settings.API_FOOTBALL_KEY,
            "Accept": "application/json",
        }
    return f"{base}/{endpoint.lstrip('/')}", headers


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)
def _get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    if not settings.API_FOOTBALL_KEY:
        raise ValueError("API_FOOTBALL_KEY not configured")
    url, headers = _build_request_args(endpoint)
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_fixture(item: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw API fixture dict to our internal format. Returns None to skip."""
    try:
        league = item.get("league", {})
        if not _is_senior(league.get("name", "")):
            return None

        fixture = item["fixture"]
        teams   = item["teams"]
        goals   = item["goals"]

        home_name = teams["home"]["name"]
        away_name = teams["away"]["name"]
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            return None  # match not finished

        match_date = fixture["date"][:10]  # ISO date

        return {
            "home_name":   normalize_team_name(home_name),
            "away_name":   normalize_team_name(away_name),
            "home_goals":  int(home_goals),
            "away_goals":  int(away_goals),
            "match_date":  match_date,
            "tournament":  league.get("name", "Unknown"),
            "fixture_id":  str(fixture["id"]),
        }
    except (KeyError, ValueError, TypeError) as exc:
        logger.debug("Skipping fixture item: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_fixtures(
    league: int = _LEAGUE_WC2026,
    season: int = _SEASON_WC2026,
    days_back: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch fixtures from API-Football. Returns [] on failure."""
    if not settings.API_FOOTBALL_KEY:
        logger.info("API_FOOTBALL_KEY not set — skipping API fetch")
        return []

    params: dict[str, Any] = {"league": league, "season": season}
    if days_back is not None:
        since = (date.today() - timedelta(days=days_back)).isoformat()
        params["from"] = since

    try:
        data = _get("fixtures", params)
        raw = data.get("response", [])
        parsed = [r for item in raw if (r := _parse_fixture(item)) is not None]
        logger.info("API-Football: fetched %d / %d fixtures (league=%d)", len(parsed), len(raw), league)
        return parsed
    except (RetryError, Exception) as exc:
        logger.warning("API-Football fetch failed (%s) — caller should use CSV fallback", exc)
        return []


def ingest_api_fixtures(
    days_back: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Fetch recent fixtures from API-Football and persist them.

    Falls back to csv_loader.load_historical_results_from_csv on failure.
    Returns the number of newly inserted results.
    """
    t0 = time.perf_counter()
    fixtures = fetch_fixtures(days_back=days_back)
    source = "api_football"

    if not fixtures:
        logger.warning("API-Football returned 0 results — trying football-data.org backup")
        try:
            from app.services.ingestion.football_data_org import ingest_football_data_fixtures
            n = ingest_football_data_fixtures(conn=conn)
            if n > 0:
                logger.info("football-data.org backup: loaded %d results (%.2fs)", n, time.perf_counter() - t0)
                return n
        except Exception as exc:
            logger.warning("football-data.org backup failed: %s", exc)

        logger.warning("All API sources failed — falling back to CSV historical data")
        from app.services.ingestion.csv_loader import load_historical_results_from_csv
        n = load_historical_results_from_csv(conn=conn)
        logger.info("CSV fallback: loaded %d results (%.2fs)", n, time.perf_counter() - t0)
        return n

    def _persist(c: sqlite3.Connection) -> int:
        team_repo = TeamRepository(c)
        result_repo = ResultRepository(c)
        count = 0
        for f in fixtures:
            home_team = team_repo.get_by_name(f["home_name"])
            away_team = team_repo.get_by_name(f["away_name"])
            home_id = home_team["id"] if home_team else f["home_name"]
            away_id = away_team["id"] if away_team else f["away_name"]

            hg, ag = f["home_goals"], f["away_goals"]
            outcome = "W" if hg > ag else ("L" if hg < ag else "D")

            try:
                result_repo.insert({
                    "id":           f"apif_{f['fixture_id']}",
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "home_goals":   hg,
                    "away_goals":   ag,
                    "outcome":      outcome,
                    "match_date":   f["match_date"],
                    "tournament":   f["tournament"],
                    "source":       "api_football",
                })
                count += 1
            except Exception as exc:
                logger.warning("DB error persisting fixture %s: %s", f, exc)
        return count

    if conn is not None:
        n = _persist(conn)
        conn.commit()
    else:
        with db_transaction() as c:
            n = _persist(c)

    logger.info(
        "API-Football ingest: source=%s new_results=%d elapsed=%.2fs",
        source, n, time.perf_counter() - t0,
    )
    return n
