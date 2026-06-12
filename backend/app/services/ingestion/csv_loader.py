"""CSV ingestion — primary data source for all entities.

All loaders:
- Accept an optional sqlite3.Connection for testing (in-memory DB).
- Return the count of successfully persisted records.
- Log loaded/skipped counts at INFO level.
- Validate before persisting (no negative goals, no future dates, etc.).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.fixtures import FixtureRepository, ResultRepository
from app.db.repositories.ratings import RatingRepository
from app.db.repositories.strengths import StrengthRepository
from app.db.repositories.teams import TeamRepository
from app.services.normalization.team_names import normalize_team_name

logger = logging.getLogger(__name__)

_TODAY = date.today().isoformat()


def _raw_path() -> Path:
    configured = Path(settings.DATA_RAW_PATH)
    if configured.is_absolute():
        return configured
    # Resolve relative to project root (4 levels up from this file)
    project_root = Path(__file__).parent.parent.parent.parent.parent
    return (project_root / configured).resolve()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_team_id(
    conn: sqlite3.Connection,
    repo: TeamRepository,
    canonical_name: str,
) -> str:
    """Return team.id for *canonical_name*, creating a stub row if needed."""
    team = repo.get_by_name(canonical_name)
    if team:
        return team["id"]
    # Stub: historical team not in the WC2026 48-team list
    stub_id = canonical_name[:20]  # keep IDs compact
    repo.upsert({"id": stub_id, "name": canonical_name})
    return stub_id


def _read_csv(path: Path, loader_name: str) -> pd.DataFrame | None:
    if not path.exists():
        logger.warning("[%s] CSV not found: %s", loader_name, path)
        return None
    try:
        return pd.read_csv(path, dtype=str)
    except Exception as exc:
        logger.error("[%s] Failed to read %s: %s", loader_name, path, exc)
        return None


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_teams_from_csv(
    csv_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    path = csv_path or (_raw_path() / "teams.csv")
    df = _read_csv(path, "load_teams")
    if df is None:
        return 0

    def _load(c: sqlite3.Connection) -> int:
        repo = TeamRepository(c)
        count = 0
        for _, row in df.iterrows():
            try:
                repo.upsert({
                    "id":            str(row["id"]).strip(),
                    "name":          str(row["name"]).strip(),
                    "code":          str(row.get("country_code", "")).strip() or None,
                    "confederation": str(row.get("confederation", "")).strip() or None,
                })
                count += 1
            except Exception as exc:
                logger.warning("Skipping team row %s: %s", row.to_dict(), exc)
        return count

    if conn is not None:
        n = _load(conn)
        conn.commit()
        logger.info("load_teams: %d teams loaded from %s", n, path)
        return n
    with db_transaction() as c:
        n = _load(c)
    logger.info("load_teams: %d teams loaded from %s", n, path)
    return n


def load_groups_from_csv(
    csv_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    path = csv_path or (_raw_path() / "groups_2026.csv")
    df = _read_csv(path, "load_groups")
    if df is None:
        return 0

    def _load(c: sqlite3.Connection) -> int:
        count = 0
        seen_groups: set[str] = set()
        for _, row in df.iterrows():
            gid = str(row["group_id"]).strip()
            gname = str(row.get("group_name", gid)).strip()
            tid = str(row["team_id"]).strip()
            try:
                if gid not in seen_groups:
                    c.execute(
                        "INSERT OR IGNORE INTO groups (id, tournament) VALUES (?,?)",
                        (gid, "WC2026"),
                    )
                    seen_groups.add(gid)
                c.execute(
                    "INSERT OR IGNORE INTO group_teams (group_id, team_id) VALUES (?,?)",
                    (gid, tid),
                )
                count += 1
            except Exception as exc:
                logger.warning("Skipping group row %s: %s", row.to_dict(), exc)
        return count

    if conn is not None:
        n = _load(conn)
        conn.commit()
        logger.info("load_groups: %d group-team rows loaded", n)
        return n
    with db_transaction() as c:
        n = _load(c)
    logger.info("load_groups: %d group-team rows loaded", n)
    return n


def load_fixtures_from_csv(
    csv_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    path = csv_path or (_raw_path() / "fixtures_2026.csv")
    df = _read_csv(path, "load_fixtures")
    if df is None:
        return 0

    def _load(c: sqlite3.Connection) -> int:
        repo = FixtureRepository(c)
        count = 0
        for _, row in df.iterrows():
            try:
                home = str(row.get("home_team_id", "")).strip()
                away = str(row.get("away_team_id", "")).strip()
                repo.upsert({
                    "id":           str(row["fixture_id"]).strip(),
                    "stage":        str(row["stage"]).strip(),
                    "group_id":     str(row.get("group_id", "")).strip() or None,
                    "home_team_id": home if home not in ("TBD", "") else None,
                    "away_team_id": away if away not in ("TBD", "") else None,
                    "match_date":   str(row.get("scheduled_at", "")).strip()[:10] or None,
                    "venue":        str(row.get("venue", "")).strip() or None,
                    "is_neutral":   True,
                    "tournament":   "WC2026",
                })
                count += 1
            except Exception as exc:
                logger.warning("Skipping fixture row %s: %s", row.to_dict(), exc)
        return count

    if conn is not None:
        n = _load(conn)
        conn.commit()
        logger.info("load_fixtures: %d fixtures loaded", n)
        return n
    with db_transaction() as c:
        n = _load(c)
    logger.info("load_fixtures: %d fixtures loaded", n)
    return n


def load_historical_results_from_csv(
    csv_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    path = csv_path or (_raw_path() / "historical_results.csv")
    df = _read_csv(path, "load_historical")
    if df is None:
        return 0

    def _load(c: sqlite3.Connection) -> int:
        team_repo = TeamRepository(c)
        result_repo = ResultRepository(c)
        loaded = skipped = 0

        for _, row in df.iterrows():
            # ── Validate ────────────────────────────────────────────────
            try:
                home_goals = int(row["home_goals"])
                away_goals = int(row["away_goals"])
                match_date = str(row["date"]).strip()
                # Basic date format check
                datetime.strptime(match_date, "%Y-%m-%d")
            except (ValueError, KeyError) as exc:
                logger.debug("Skipping invalid row (parse error): %s", exc)
                skipped += 1
                continue

            if home_goals < 0 or away_goals < 0:
                logger.warning("Negative goals — skipping: %s", row.to_dict())
                skipped += 1
                continue

            if match_date > _TODAY:
                logger.debug("Future date %s — skipping", match_date)
                skipped += 1
                continue

            # ── Normalize team names ─────────────────────────────────
            home_name = normalize_team_name(str(row["home_team"]).strip())
            away_name = normalize_team_name(str(row["away_team"]).strip())

            # ── Resolve / create team stubs ──────────────────────────
            home_id = _resolve_team_id(c, team_repo, home_name)
            away_id = _resolve_team_id(c, team_repo, away_name)

            # ── Outcome ──────────────────────────────────────────────
            if home_goals > away_goals:
                outcome = "W"
            elif home_goals < away_goals:
                outcome = "L"
            else:
                outcome = "D"

            tourn = str(row.get("tournament", "")).strip()
            is_wc = int("WC20" in tourn)

            try:
                result_repo.insert({
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "home_goals":   home_goals,
                    "away_goals":   away_goals,
                    "outcome":      outcome,
                    "match_date":   match_date,
                    "tournament":   tourn,
                    "stage":        str(row.get("stage", "")).strip() or None,
                    "is_wc":        is_wc,
                    "source":       "csv",
                })
                loaded += 1
            except Exception as exc:
                logger.warning("DB insert failed for row %s: %s", row.to_dict(), exc)
                skipped += 1

        logger.info(
            "load_historical: loaded=%d skipped=%d from %s", loaded, skipped, path
        )
        return loaded

    if conn is not None:
        n = _load(conn)
        conn.commit()
        return n
    with db_transaction() as c:
        return _load(c)


def load_ratings_from_csv(
    elo_path: Path | None = None,
    fifa_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    elo_p = elo_path or (_raw_path() / "elo_ratings.csv")
    fifa_p = fifa_path or (_raw_path() / "fifa_rankings.csv")

    def _load(c: sqlite3.Connection) -> int:
        team_repo = TeamRepository(c)
        rating_repo = RatingRepository(c)
        count = 0

        # ELO
        df_elo = _read_csv(elo_p, "load_ratings_elo")
        if df_elo is not None:
            for _, row in df_elo.iterrows():
                try:
                    canonical = normalize_team_name(str(row["team"]).strip())
                    tid = _resolve_team_id(c, team_repo, canonical)
                    rating_repo.upsert_elo(
                        team_id=tid,
                        value=float(row["elo_rating"]),
                        effective_date=str(row["as_of"]).strip(),
                    )
                    count += 1
                except Exception as exc:
                    logger.warning("ELO row error %s: %s", row.to_dict(), exc)

        # FIFA
        df_fifa = _read_csv(fifa_p, "load_ratings_fifa")
        if df_fifa is not None:
            for _, row in df_fifa.iterrows():
                try:
                    canonical = normalize_team_name(str(row["team"]).strip())
                    tid = _resolve_team_id(c, team_repo, canonical)
                    rating_repo.upsert_fifa(
                        team_id=tid,
                        value=float(row["fifa_points"]),
                        rank=int(row["rank"]),
                        effective_date=str(row["as_of"]).strip(),
                    )
                    count += 1
                except Exception as exc:
                    logger.warning("FIFA row error %s: %s", row.to_dict(), exc)

        logger.info("load_ratings: %d rating rows loaded", count)
        return count

    if conn is not None:
        n = _load(conn)
        conn.commit()
        return n
    with db_transaction() as c:
        return _load(c)
