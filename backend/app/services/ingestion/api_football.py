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
from app.services.normalization.team_names import normalize_team_id, normalize_team_name

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
            "home_team_id": normalize_team_id(home_name),
            "away_team_id": normalize_team_id(away_name),
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
            home_team = team_repo.get_by_id(f.get("home_team_id") or "") or team_repo.get_by_name(f["home_name"])
            away_team = team_repo.get_by_id(f.get("away_team_id") or "") or team_repo.get_by_name(f["away_name"])
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
                    # ingest_api_fixtures always fetches league=_LEAGUE_WC2026 —
                    # every result persisted here IS a WC2026 match. Previously
                    # left unset (defaulted to False), which made bracket
                    # knockout-result detection (filters on is_wc=1) blind to
                    # every real R32+ result ingested from this source.
                    "is_wc":        True,
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


def fetch_wc2026_standings(conn: sqlite3.Connection) -> int:
    """Fetch WC2026 group standings and persist to wc2026_standings table.

    Returns number of team records upserted. Returns 0 if API unavailable.
    """
    if not settings.API_FOOTBALL_KEY:
        logger.warning("fetch_wc2026_standings: API_FOOTBALL_KEY not set — skipping")
        return 0

    try:
        data = _get("standings", {
            "league": _LEAGUE_WC2026,
            "season": _SEASON_WC2026,
        })
    except Exception as exc:
        logger.warning("fetch_wc2026_standings: API call failed: %s", exc)
        return 0

    try:
        standings_groups = data["response"][0]["league"]["standings"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("fetch_wc2026_standings: unexpected response structure: %s", exc)
        return 0

    upserted = 0
    for group in standings_groups:
        group_name = group[0].get("group", "") if group else ""
        group_id = group_name.replace("Group ", "").strip() or "?"

        for entry in group:
            api_team_id = str(entry["team"]["id"])
            team_name   = entry["team"]["name"]

            internal_id = normalize_team_id(api_team_id, team_name, conn)
            if not internal_id:
                logger.debug("fetch_wc2026_standings: no match for %s", team_name)
                continue

            description = (entry.get("description") or "").lower()
            if "eliminated" in description or "relegated" in description:
                status = "eliminated"
            elif "qualified" in description or "next stage" in description:
                status = "qualified"
            else:
                status = "active"

            stats = entry.get("all", {})
            goals = stats.get("goals", {})

            conn.execute(
                """
                INSERT OR REPLACE INTO wc2026_standings
                    (team_id, group_id, position, played, won, drawn, lost,
                     goals_for, goals_against, points, status, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    internal_id,
                    group_id,
                    int(entry.get("rank", 0)),
                    int(stats.get("played", 0)),
                    int(stats.get("win",   0)),
                    int(stats.get("draw",  0)),
                    int(stats.get("lose",  0)),
                    int(goals.get("for",     0)),
                    int(goals.get("against", 0)),
                    int(entry.get("points",  0)),
                    status,
                ),
            )
            upserted += 1

    conn.commit()
    logger.info("fetch_wc2026_standings: upserted %d team standings", upserted)
    return upserted


def fetch_wc2026_squads(conn: sqlite3.Connection) -> int:
    """Fetch WC2026 squad lists from API-Football and persist to wc2026_squads.

    Calls /players/squads for each WC2026 team (league=1, season=2026).
    Uses INSERT OR IGNORE so repeated runs are safe.
    Returns 0 and logs WARNING if API key is missing or the call fails.
    """
    if not settings.API_FOOTBALL_KEY:
        logger.warning("fetch_wc2026_squads: API_FOOTBALL_KEY not configured — skipping")
        return 0

    from app.db.repositories.teams import TeamRepository
    team_repo = TeamRepository(conn)
    teams = conn.execute("SELECT id FROM teams").fetchall()
    if not teams:
        logger.warning("fetch_wc2026_squads: no teams in DB — skipping")
        return 0

    total = 0
    for team_row in teams:
        team_id = team_row["id"]
        try:
            data = _get("players/squads", {"team": team_id})
            response = data.get("response", [])
            for squad_block in response:
                for player in squad_block.get("players", []):
                    name = (player.get("name") or "").strip()
                    position = (player.get("position") or "").strip() or None
                    number = player.get("number")
                    if not name:
                        continue
                    try:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO wc2026_squads
                                (team_id, player_name, position, jersey_number, source)
                            VALUES (?, ?, ?, ?, 'api_football')
                            """,
                            (team_id, name, position, number),
                        )
                        total += 1
                    except Exception as exc:
                        logger.debug("fetch_wc2026_squads: insert failed for %s/%s: %s", team_id, name, exc)
        except Exception as exc:
            logger.warning("fetch_wc2026_squads: failed for team %s: %s", team_id, exc)

    if total > 0:
        conn.commit()
    logger.info("fetch_wc2026_squads: %d players inserted", total)
    return total
