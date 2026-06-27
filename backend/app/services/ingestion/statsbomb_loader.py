"""StatsBomb Open Data ingestion.

Reads match, event, and lineup JSON files from the StatsBomb open-data
repository and populates the sb_matches, sb_match_stats, and
sb_player_stats tables.

Usage:
    from app.services.ingestion.statsbomb_loader import load_all_wc_matches
    count = load_all_wc_matches(conn, "/path/to/statsbomb-data/data")
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from app.services.normalization.team_names import normalize_team_id

logger = logging.getLogger(__name__)

_WC_COMPETITION_ID = 43  # FIFA World Cup in StatsBomb Open Data

# ---------------------------------------------------------------------------
# Team name mapping: StatsBomb English names → our 3-letter team codes
# ---------------------------------------------------------------------------

STATSBOMB_ALIASES: dict[str, str] = {
    # StatsBomb-specific variants that differ from the standard English form
    "Korea Republic": "KOR",
    "IR Iran": "IRN",
    "United States": "USA",

    # All teams that appeared in WC 2018 and/or WC 2022
    "Argentina": "ARG",
    "Australia": "AUS",
    "Belgium": "BEL",
    "Brazil": "BRA",
    "Cameroon": "CMR",
    "Canada": "CAN",
    "Colombia": "COL",
    "Costa Rica": "CRC",
    "Croatia": "CRO",
    "Denmark": "DEN",
    "Ecuador": "ECU",
    "Egypt": "EGY",
    "England": "ENG",
    "France": "FRA",
    "Germany": "GER",
    "Ghana": "GHA",
    "Iceland": "ISL",
    "Iran": "IRN",
    "Japan": "JPN",
    "Mexico": "MEX",
    "Morocco": "MAR",
    "Netherlands": "NED",
    "Nigeria": "NGA",
    "Panama": "PAN",
    "Peru": "PER",
    "Poland": "POL",
    "Portugal": "POR",
    "Qatar": "QAT",
    "Russia": "RUS",
    "Saudi Arabia": "KSA",
    "Senegal": "SEN",
    "Serbia": "SRB",
    "South Korea": "KOR",
    "Spain": "ESP",
    "Sweden": "SWE",
    "Switzerland": "SUI",
    "Tunisia": "TUN",
    "Uruguay": "URU",
    "Wales": "WAL",
}


def _normalize_sb_team(name: str) -> str:
    """Resolve a StatsBomb team name to our internal team_id.

    Priority: STATSBOMB_ALIASES → normalize_team_id() → truncated name.
    """
    if name in STATSBOMB_ALIASES:
        return STATSBOMB_ALIASES[name]
    team_id = normalize_team_id(name)
    if team_id:
        return team_id
    return name[:20]  # stub ID, consistent with csv_loader._resolve_team_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_statsbomb_competitions(data_path: str) -> list[dict]:
    """Return all FIFA World Cup entries from competitions.json.

    Filters by competition_id=43 (FIFA World Cup).
    Returns an empty list when the file is missing or unreadable.
    """
    path = Path(data_path) / "competitions.json"
    if not path.exists():
        logger.warning("[StatsBomb] competitions.json not found at %s", path)
        return []
    try:
        data: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("[StatsBomb] Cannot parse competitions.json: %s", exc)
        return []
    return [c for c in data if c.get("competition_id") == _WC_COMPETITION_ID]


def parse_match_events(events_data: list[dict]) -> dict[str, dict[str, Any]]:
    """Aggregate per-team stats from a list of StatsBomb match events.

    Processed event types: Shot, Pass, Pressure, Duel.
    Returns a dict keyed by StatsBomb team name.
    """
    teams: dict[str, dict[str, Any]] = {}
    total_events = len(events_data)

    for event in events_data:
        team_name: str = (event.get("team") or {}).get("name", "")
        if not team_name:
            continue

        if team_name not in teams:
            teams[team_name] = {
                "xg": 0.0,
                "shots": 0,
                "shots_on_target": 0,
                "passes_total": 0,
                "passes_completed": 0,
                "pressures": 0,
                "duels_won": 0,
                "duels_total": 0,
                "_event_count": 0,
            }

        t = teams[team_name]
        t["_event_count"] += 1
        event_type: str = (event.get("type") or {}).get("name", "")

        if event_type == "Shot":
            t["shots"] += 1
            shot: dict = event.get("shot") or {}
            t["xg"] += shot.get("statsbomb_xg") or 0.0
            outcome = (shot.get("outcome") or {}).get("name", "")
            if outcome in ("Saved", "Goal"):
                t["shots_on_target"] += 1

        elif event_type == "Pass":
            t["passes_total"] += 1
            pass_data: dict = event.get("pass") or {}
            # StatsBomb: pass.outcome is None/absent when the pass is successful
            if pass_data.get("outcome") is None:
                t["passes_completed"] += 1

        elif event_type == "Pressure":
            t["pressures"] += 1

        elif event_type == "Duel":
            t["duels_total"] += 1
            duel_outcome = ((event.get("duel") or {}).get("outcome") or {}).get("name", "")
            if "Win" in duel_outcome or "Success" in duel_outcome:
                t["duels_won"] += 1

    # Derive possession (% of events) and pass accuracy
    for stats in teams.values():
        event_count = stats.pop("_event_count", 0)
        stats["possession"] = round(100.0 * event_count / total_events, 1) if total_events else 0.0
        pt = stats["passes_total"]
        pc = stats["passes_completed"]
        stats["pass_accuracy"] = round(100.0 * pc / pt, 1) if pt else 0.0

    return teams


def load_all_wc_matches(conn: sqlite3.Connection, data_path: str) -> int:
    """Load WC 2018 and 2022 match data from StatsBomb Open Data.

    Reads matches/43/*.json for each World Cup season, then loads
    events/{match_id}.json to compute per-team and per-player stats.

    Returns the number of successfully processed matches.
    Commits the connection before returning.
    """
    base = Path(data_path)
    matches_dir = base / "matches" / str(_WC_COMPETITION_ID)

    if not matches_dir.exists():
        logger.warning("[StatsBomb] WC matches directory not found: %s", matches_dir)
        return 0

    total = 0
    for season_file in sorted(matches_dir.glob("*.json")):
        try:
            matches: list[dict] = json.loads(season_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[StatsBomb] Cannot read %s: %s", season_file, exc)
            continue

        for match in matches:
            try:
                _ingest_match(conn, match, base)
                total += 1
            except Exception as exc:
                logger.warning(
                    "[StatsBomb] Skipping match %s: %s",
                    match.get("match_id", "?"), exc,
                )

    conn.commit()
    logger.info("[StatsBomb] Ingested %d WC matches", total)
    return total


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ingest_match(conn: sqlite3.Connection, match: dict, base: Path) -> None:
    match_id: int = match["match_id"]
    competition_id: int = match["competition"]["competition_id"]
    season_id: int = match["season"]["season_id"]
    competition_name: str = match["competition"]["competition_name"]
    season_name: str = match["season"]["season_name"]
    match_date: str = match.get("match_date", "")
    home_team_sb: str = match["home_team"]["home_team_name"]
    away_team_sb: str = match["away_team"]["away_team_name"]
    home_score = match.get("home_score")
    away_score = match.get("away_score")

    home_team_id = _normalize_sb_team(home_team_sb)
    away_team_id = _normalize_sb_team(away_team_sb)

    conn.execute(
        """
        INSERT OR REPLACE INTO sb_matches
            (match_id, competition_id, season_id, competition_name, season_name,
             match_date, home_team_id, away_team_id,
             home_score, away_score, home_team_sb, away_team_sb)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (match_id, competition_id, season_id, competition_name, season_name,
         match_date, home_team_id, away_team_id,
         home_score, away_score, home_team_sb, away_team_sb),
    )

    events_file = base / "events" / f"{match_id}.json"
    if not events_file.exists():
        return  # match metadata loaded; events not available yet

    events_data: list[dict] = json.loads(events_file.read_text(encoding="utf-8"))
    team_stats = parse_match_events(events_data)

    team_names = list(team_stats.keys())
    for i, team_sb in enumerate(team_names):
        opp_sb = team_names[1 - i] if len(team_names) == 2 else None
        stats = team_stats[team_sb]
        opp_stats = team_stats.get(opp_sb, {}) if opp_sb else {}
        team_id = _normalize_sb_team(team_sb)
        is_home = 1 if team_sb == home_team_sb else 0
        goals = (home_score if is_home else away_score) or 0

        conn.execute(
            """
            INSERT OR REPLACE INTO sb_match_stats
                (id, match_id, team_id, is_home, goals,
                 xg, shots, shots_on_target,
                 xg_conceded, shots_conceded,
                 possession, passes_completed, passes_total, pass_accuracy,
                 pressures, duels_won, duels_total)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"{match_id}_{team_id}",
                match_id, team_id, is_home, goals,
                round(stats.get("xg", 0.0), 4),
                stats.get("shots", 0),
                stats.get("shots_on_target", 0),
                round(opp_stats.get("xg", 0.0), 4),
                opp_stats.get("shots", 0),
                stats.get("possession", 0.0),
                stats.get("passes_completed", 0),
                stats.get("passes_total", 0),
                stats.get("pass_accuracy", 0.0),
                stats.get("pressures", 0),
                stats.get("duels_won", 0),
                stats.get("duels_total", 0),
            ),
        )

    _ingest_player_stats(conn, match_id, events_data)


def _ingest_player_stats(
    conn: sqlite3.Connection,
    match_id: int,
    events_data: list[dict],
) -> None:
    players: dict[tuple[str, str], dict[str, Any]] = {}
    # Substitution events: player going OFF → minute they left
    sub_off_minute: dict[tuple[str, str], int] = {}

    for event in events_data:
        player_info = event.get("player")
        if not player_info:
            continue
        player_name: str = player_info.get("name", "")
        if not player_name:
            continue
        team_name: str = (event.get("team") or {}).get("name", "")
        event_type: str = (event.get("type") or {}).get("name", "")
        minute: int = event.get("minute") or 0

        key = (player_name, team_name)
        if key not in players:
            position = (event.get("position") or {}).get("name", "")
            players[key] = {
                "team_id": _normalize_sb_team(team_name),
                "position": position,
                "goals": 0,
                "xg": 0.0,
                "shots": 0,
                "key_passes": 0,
                "minutes_played": 90,  # default; overridden by substitution event
            }

        p = players[key]

        if event_type == "Shot":
            p["shots"] += 1
            shot: dict = event.get("shot") or {}
            p["xg"] += shot.get("statsbomb_xg") or 0.0
            if (shot.get("outcome") or {}).get("name") == "Goal":
                p["goals"] += 1
        elif event_type == "Pass":
            pass_data: dict = event.get("pass") or {}
            if pass_data.get("shot_assist") or pass_data.get("goal_assist"):
                p["key_passes"] += 1
        elif event_type == "Substitution":
            # The player field is the one going OFF at this minute
            sub_off_minute[key] = minute

    # Apply substitution minutes to players who came off
    for key, off_min in sub_off_minute.items():
        if key in players:
            players[key]["minutes_played"] = off_min

    for (player_name, team_name), p in players.items():
        pid = hashlib.md5(
            f"{match_id}|{team_name}|{player_name}".encode()
        ).hexdigest()[:16]
        conn.execute(
            """
            INSERT OR REPLACE INTO sb_player_stats
                (id, match_id, team_id, player_name, position,
                 minutes_played, goals, xg, shots, key_passes)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pid, match_id, p["team_id"], player_name, p["position"],
                p["minutes_played"],
                p["goals"], round(p["xg"], 4), p["shots"], p["key_passes"],
            ),
        )
