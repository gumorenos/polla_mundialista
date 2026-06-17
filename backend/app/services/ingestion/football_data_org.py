"""football-data.org client — backup data source when API-Football is unavailable.

Docs: https://www.football-data.org/documentation/quickstart
Auth: X-Auth-Token header (free tier: 10 req/min, WC competition available)

Used as an intermediate fallback between API-Football and CSV:
  API-Football → football-data.org → CSV historical
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

import httpx
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.fixtures import ResultRepository
from app.db.repositories.teams import TeamRepository
from app.services.normalization.team_names import normalize_team_id, normalize_team_name

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.football-data.org/v4"
_WC_CODE = "WC"
_WC_SEASON = 2026


def _headers() -> dict[str, str]:
    return {
        "X-Auth-Token": settings.FOOTBALL_DATA_API_KEY,
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.FOOTBALL_DATA_API_KEY:
        raise ValueError("FOOTBALL_DATA_API_KEY not configured")
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    with httpx.Client(timeout=20) as client:
        resp = client.get(url, headers=_headers(), params=params or {})
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Public fetch helpers
# ---------------------------------------------------------------------------

def fetch_teams_wc2026() -> list[dict[str, Any]]:
    """Fetch the 48 WC 2026 teams from football-data.org.

    Returns list of {team_id (tla), name, short_name, confederation}.
    Returns [] on any failure.
    """
    if not settings.FOOTBALL_DATA_API_KEY:
        logger.debug("FOOTBALL_DATA_API_KEY not set — skipping fetch_teams_wc2026")
        return []
    try:
        data = _get(f"competitions/{_WC_CODE}/teams", {"season": _WC_SEASON})
        teams = []
        for t in data.get("teams", []):
            name = t.get("name", "")
            team_id = (t.get("tla") or normalize_team_id(name) or "").upper()
            teams.append({
                "team_id": team_id,
                "name": normalize_team_name(name),
                "short_name": t.get("shortName", ""),
                "area": t.get("area", {}).get("name", ""),
            })
        logger.info("football-data.org: fetched %d WC2026 teams", len(teams))
        return teams
    except (RetryError, Exception) as exc:
        logger.warning("football-data.org teams fetch failed: %s", exc)
        return []


def fetch_matches_wc2026(known_team_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Fetch WC 2026 matches (finished only) from football-data.org.

    Args:
        known_team_ids: if provided, skip matches where either team TLA is not in this set.
                        Prevents friendlies or warm-up matches from leaking in.

    Returns list of {home_name, away_name, home_goals, away_goals, match_date, tournament, fixture_id}.
    Returns [] on any failure.
    """
    if not settings.FOOTBALL_DATA_API_KEY:
        logger.debug("FOOTBALL_DATA_API_KEY not set — skipping fetch_matches_wc2026")
        return []
    try:
        data = _get(f"competitions/{_WC_CODE}/matches", {"season": _WC_SEASON})
        matches = []
        skipped = 0
        for m in data.get("matches", []):
            if m.get("status") != "FINISHED":
                continue
            score = m.get("score", {}).get("fullTime", {})
            home_goals = score.get("home")
            away_goals = score.get("away")
            if home_goals is None or away_goals is None:
                continue
            home_raw = m.get("homeTeam", {}).get("name", "")
            away_raw = m.get("awayTeam", {}).get("name", "")
            home_tla = (m.get("homeTeam", {}).get("tla") or normalize_team_id(home_raw) or "").upper()
            away_tla = (m.get("awayTeam", {}).get("tla") or normalize_team_id(away_raw) or "").upper()
            if known_team_ids is not None:
                if home_tla not in known_team_ids or away_tla not in known_team_ids:
                    logger.debug(
                        "Skipping match with non-WC teams: %s (%s) vs %s (%s)",
                        m.get("homeTeam", {}).get("name"), home_tla,
                        m.get("awayTeam", {}).get("name"), away_tla,
                    )
                    skipped += 1
                    continue
            home_name = normalize_team_name(home_raw)
            away_name = normalize_team_name(away_raw)
            utc_date = m.get("utcDate", "")[:10]
            matches.append({
                "home_team_id": home_tla,
                "away_team_id": away_tla,
                "home_name": home_name,
                "away_name": away_name,
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
                "match_date": utc_date,
                "tournament": f"FIFA World Cup {_WC_SEASON}",
                "fixture_id": str(m.get("id", "")),
            })
        if skipped:
            logger.info("football-data.org: skipped %d matches with non-WC teams", skipped)
        logger.info("football-data.org: fetched %d finished WC2026 matches", len(matches))
        return matches
    except (RetryError, Exception) as exc:
        logger.warning("football-data.org matches fetch failed: %s", exc)
        return []


def fetch_standings_wc2026() -> list[dict[str, Any]]:
    """Fetch WC 2026 group standings from football-data.org.

    Returns list of {group, position, team_id, played, won, drawn, lost, points}.
    Returns [] on any failure.
    """
    if not settings.FOOTBALL_DATA_API_KEY:
        logger.debug("FOOTBALL_DATA_API_KEY not set — skipping fetch_standings_wc2026")
        return []
    try:
        data = _get(f"competitions/{_WC_CODE}/standings", {"season": _WC_SEASON})
        standings = []
        for stage in data.get("standings", []):
            group = stage.get("group", "")
            for row in stage.get("table", []):
                standings.append({
                    "group": group,
                    "position": row.get("position"),
                    "team_id": (
                        row.get("team", {}).get("tla")
                        or normalize_team_id(row.get("team", {}).get("name", ""))
                        or ""
                    ),
                    "team_name": normalize_team_name(row.get("team", {}).get("name", "")),
                    "played": row.get("playedGames", 0),
                    "won": row.get("won", 0),
                    "drawn": row.get("draw", 0),
                    "lost": row.get("lost", 0),
                    "points": row.get("points", 0),
                })
        logger.info("football-data.org: fetched standings for %d group rows", len(standings))
        return standings
    except (RetryError, Exception) as exc:
        logger.warning("football-data.org standings fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Ingest matches into DB
# ---------------------------------------------------------------------------

def ingest_football_data_fixtures(conn: sqlite3.Connection | None = None) -> int:
    """Fetch WC2026 matches from football-data.org and persist them.

    Only ingests matches where both teams are registered in the teams table.
    Returns number of newly inserted results. Returns 0 on failure.
    """
    t0 = time.perf_counter()

    def _get_known_ids(c: sqlite3.Connection) -> set[str]:
        return {row[0] for row in c.execute("SELECT id FROM teams").fetchall()}

    known_ids: set[str] = set()
    if conn is not None:
        known_ids = _get_known_ids(conn)
    else:
        with db_transaction() as c:
            known_ids = _get_known_ids(c)

    matches = fetch_matches_wc2026(known_team_ids=known_ids)
    if not matches:
        return 0

    def _persist(c: sqlite3.Connection) -> int:
        team_repo = TeamRepository(c)
        result_repo = ResultRepository(c)
        count = 0
        for m in matches:
            home_team = team_repo.get_by_id(m.get("home_team_id", "")) or team_repo.get_by_name(m["home_name"])
            away_team = team_repo.get_by_id(m.get("away_team_id", "")) or team_repo.get_by_name(m["away_name"])
            home_id = home_team["id"] if home_team else m["home_name"]
            away_id = away_team["id"] if away_team else m["away_name"]
            hg, ag = m["home_goals"], m["away_goals"]
            outcome = "W" if hg > ag else ("L" if hg < ag else "D")
            try:
                result_repo.insert({
                    "id": f"fd_{m['fixture_id']}",
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "home_goals": hg,
                    "away_goals": ag,
                    "outcome": outcome,
                    "match_date": m["match_date"],
                    "tournament": m["tournament"],
                    "source": "football_data_org",
                })
                count += 1
            except Exception as exc:
                logger.warning("DB error persisting fd fixture %s: %s", m, exc)
        return count

    if conn is not None:
        n = _persist(conn)
        conn.commit()
    else:
        with db_transaction() as c:
            n = _persist(c)

    logger.info(
        "football-data.org ingest: new_results=%d elapsed=%.2fs",
        n, time.perf_counter() - t0,
    )
    return n
