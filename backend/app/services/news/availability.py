"""News availability pipeline — injury detection and context adjustment persistence.

Pipeline phases (FIX 1: separated to avoid long write-transaction):
  1. Expire stale DB claims → short commit → lock released
  2. For each player: HTTP (RSS) + HTTP (article) + LLM — NO open write transaction
  3. After each player's network phase: persist collected claims → short commit
  4. After each team: if injured, persist context adjustment → short commit

FIX 5:
  - Articles classified as UNRELATED are NOT persisted.
  - Articles without published_at are NOT persisted.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.db.repositories.availability import AvailabilityRepository
from app.db.repositories.config import ConfigRepository
from app.services.news.llm_classifier import classify_injury
from app.services.news.scraper import extract_article_text, search_player_news, source_credibility

logger = logging.getLogger(__name__)

# LLM status → DB availability_claims.status
_STATUS_MAP = {
    "CONFIRMED":   "injured",
    "SPECULATION": "doubtful",
    "DENIED":      "available",
    "UNRELATED":   "unknown",
}

_MIN_CREDIBILITY = 0.3


def _get_config(conn: sqlite3.Connection, key: str) -> float:
    """Read a config value from app_config, falling back to settings."""
    try:
        raw = ConfigRepository(conn).get_value(key)
        if raw is not None:
            return float(raw)
    except Exception:
        pass
    return float(getattr(settings, key))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_suspension_analysis(db_conn: sqlite3.Connection) -> dict[str, Any]:
    """Detect suspended players and apply prediction penalties.

    Reads player_bookings for WC2026, identifies suspensions per FIFA rules,
    and inserts team_context_adjustments with adjustment_type='suspension'.

    Returns:
        {"affected_teams": list[str], "suspended_players": list[dict]}
    """
    from app.services.suspensions.detector import get_suspended_players

    try:
        teams = db_conn.execute("SELECT id FROM teams").fetchall()
    except Exception as exc:
        logger.warning("Suspension analysis: cannot read teams: %s", exc)
        return {"affected_teams": [], "suspended_players": []}

    affected_teams: list[str] = []
    all_suspended: list[dict] = []

    for row in teams:
        team_id = row["id"] if hasattr(row, "__getitem__") else row[0]
        suspended = get_suspended_players(team_id, db_conn)
        if not suspended:
            continue

        n = len(suspended)
        attack_factor = (1.0 - settings.SUSPENSION_ATTACK_PENALTY) ** n
        defense_factor = (1.0 + settings.SUSPENSION_DEFENSE_PENALTY) ** n
        player_names = [p["player_name"] for p in suspended]

        AvailabilityRepository(db_conn).insert_context_adjustment(
            team_id=team_id,
            attack_factor=attack_factor,
            defense_factor=defense_factor,
            notes=f"Suspended: {', '.join(player_names)}",
            adjustment_type="suspension",
        )
        db_conn.commit()
        affected_teams.append(team_id)
        all_suspended.extend(suspended)

        logger.info(
            "Suspension penalty applied: team=%s n=%d attack_factor=%.3f defense_factor=%.3f",
            team_id, n, attack_factor, defense_factor,
        )

    logger.info(
        "Suspension analysis complete: %d teams affected, %d suspended players",
        len(affected_teams), len(all_suspended),
    )
    return {"affected_teams": affected_teams, "suspended_players": all_suspended}


def run_form_analysis(db_conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute key-player form adjustments for all teams with StatsBomb data.

    Inserts team_context_adjustments with adjustment_type='player_form' for
    teams whose key striker is clearly in or out of form.

    Returns:
        {"boosted_teams": list[str], "penalised_teams": list[str],
         "form_data": list[dict]}
    """
    from app.services.features.player_form import (
        _IN_FORM_BONUS, _OUT_OF_FORM_PENALTY, get_player_form,
        get_team_form_adjustment,
    )

    try:
        teams = db_conn.execute("SELECT id FROM teams").fetchall()
    except Exception as exc:
        logger.warning("Form analysis: cannot read teams: %s", exc)
        return {"boosted_teams": [], "penalised_teams": [], "form_data": []}

    boosted: list[str] = []
    penalised: list[str] = []
    form_data: list[dict] = []

    for row in teams:
        team_id = row["id"] if hasattr(row, "__getitem__") else row[0]
        try:
            factor = get_team_form_adjustment(team_id, db_conn)
        except Exception as exc:
            logger.debug("Form analysis: failed for %s: %s", team_id, exc)
            continue

        if factor == 1.0:
            continue

        label = "in_form" if factor > 1.0 else "out_of_form"
        AvailabilityRepository(db_conn).insert_context_adjustment(
            team_id=team_id,
            attack_factor=factor,
            defense_factor=1.0,
            notes=f"Player form adjustment ({label}): attack factor {factor:.3f}",
            adjustment_type="player_form",
        )
        db_conn.commit()

        if factor > 1.0:
            boosted.append(team_id)
        else:
            penalised.append(team_id)

        form_data.append({"team_id": team_id, "factor": factor, "status": label})
        logger.info(
            "Form adjustment applied: team=%s factor=%.3f (%s)",
            team_id, factor, label,
        )

    logger.info(
        "Form analysis complete: %d boosted, %d penalised",
        len(boosted), len(penalised),
    )
    return {"boosted_teams": boosted, "penalised_teams": penalised, "form_data": form_data}


def run_news_analysis(db_conn: sqlite3.Connection) -> dict[str, Any]:
    """Run the full injury detection pipeline.

    The pipeline separates network I/O from DB writes to avoid holding
    a write-transaction open during HTTP/LLM calls (FIX 1).

    Returns:
        {"affected_teams": list[str], "injured_players": list[dict], "total_claims": int}
    """
    # Phase 1: expire stale claims → commit immediately to release write lock
    _expire_stale_claims(db_conn)
    db_conn.commit()

    star_players = _load_star_players()
    if not star_players:
        logger.warning("No star players data — skipping news analysis")
        return {"affected_teams": [], "injured_players": [], "total_claims": 0}

    avail_repo     = AvailabilityRepository(db_conn)
    affected_teams: list[str]   = []
    injured_players: list[dict] = []
    total_claims = 0

    for team_key, players in star_players.items():
        team_id = _resolve_team_id(db_conn, team_key)
        if team_id is None:
            logger.warning("Team '%s' not in DB — skipping", team_key)
            continue

        team_injuries: list[str] = []

        for player in players:
            try:
                # Phase 2: collect via HTTP/LLM — NO writes happen here
                claim_dicts, is_injured = _collect_player_claims(
                    player=player,
                    country=team_key,
                    team_id=team_id,
                    conn=db_conn,
                )

                # Phase 3: persist collected claims → short commit
                for claim in claim_dicts:
                    avail_repo.insert_claim(claim)
                if claim_dicts:
                    db_conn.commit()

                if is_injured:
                    team_injuries.append(player)
                    injured_players.append({"team": team_id, "player": player})
                    total_claims += 1
            except Exception as exc:
                logger.warning(
                    "News analysis failed for %s / %s: %s", team_key, player, exc
                )

        if team_injuries:
            # Phase 4: persist context adjustment → short commit
            _apply_penalties(db_conn, team_id, team_injuries)
            db_conn.commit()
            affected_teams.append(team_id)

    logger.info(
        "News analysis complete: %d teams affected, %d injured players confirmed",
        len(affected_teams), len(injured_players),
    )
    return {
        "affected_teams":  affected_teams,
        "injured_players": injured_players,
        "total_claims":    total_claims,
    }


# ---------------------------------------------------------------------------
# Internal pipeline
# ---------------------------------------------------------------------------

def _collect_player_claims(
    player: str,
    country: str,
    team_id: str,
    conn: sqlite3.Connection | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Collect and classify articles for one player — pure network phase, NO DB writes.

    Returns:
        (claim_dicts, is_injured)

    FIX 5 filters applied:
    - Skip articles without published_at (never substitute datetime.now()).
    - Skip UNRELATED classifications (not worth persisting).
    """
    days_lookback = int(_get_config(conn, "NEWS_DAYS_LOOKBACK")) if conn else settings.NEWS_DAYS_LOOKBACK
    confidence_threshold = _get_config(conn, "NEWS_CONFIDENCE_THRESHOLD") if conn else settings.NEWS_CONFIDENCE_THRESHOLD
    min_sources = int(_get_config(conn, "NEWS_MIN_SOURCES")) if conn else settings.NEWS_MIN_SOURCES

    articles = search_player_news(country, player, days_lookback)
    confirmed_count = 0
    claim_dicts: list[dict[str, Any]] = []

    for article in articles[: settings.NEWS_MAX_PER_PLAYER]:
        domain = article.get("source_domain") or _domain(article.get("url", ""))

        if source_credibility(domain) < _MIN_CREDIBILITY:
            continue

        # FIX 5: reject articles that have no real publication date
        if not article.get("published_at"):
            logger.warning(
                "Skipping claim for %s: article has no published_at (url=%s)",
                player, article.get("url", ""),
            )
            continue

        text = extract_article_text(article["url"])
        if not text:
            text = article.get("snippet", "")
        if not text:
            continue

        try:
            classification = classify_injury(player, country, text)
        except Exception as exc:
            logger.warning(
                "_collect_player_claims: classify_injury failed for %s / %s: %s",
                player, article.get("url", ""), exc,
            )
            continue

        # FIX 5: don't persist UNRELATED articles
        if classification["status"] == "UNRELATED":
            logger.debug(
                "Skipping UNRELATED claim for %s (url=%s)", player, article.get("url", "")
            )
            continue

        db_status = _STATUS_MAP.get(classification["status"], "unknown")
        affects   = (
            classification["status"]    == "CONFIRMED"
            and classification["confidence"] >= confidence_threshold
            and classification["miss_tournament"]
        )

        claim_dicts.append({
            "team_id":            team_id,
            "player_name":        player,
            "player_key":         f"{team_id}_{_slugify(player)}",
            "status":             db_status,
            "reason":             classification["reasoning"][:200],
            "source_url":         article["url"],
            "source_name":        domain,
            "confidence":         classification["confidence"],
            "evidence_level":     "confirmed" if affects else "speculation",
            "observed_at":        datetime.now(timezone.utc).isoformat(),
            "published_at":       article.get("published_at"),
            "affects_prediction": affects,
            "raw_json":           json.dumps(classification),
        })

        if affects:
            confirmed_count += 1

    is_injured = confirmed_count >= min_sources
    return claim_dicts, is_injured


def _expire_stale_claims(conn: sqlite3.Connection) -> None:
    """Mark availability claims older than NEWS_DAYS_LOOKBACK days as available."""
    days = int(_get_config(conn, "NEWS_DAYS_LOOKBACK"))
    AvailabilityRepository(conn).expire_stale_claims(days)
    logger.debug("Expired stale claims older than %d days", days)


def _apply_penalties(
    conn: sqlite3.Connection,
    team_id: str,
    injured_players: list[str],
) -> None:
    """Insert a team_context_adjustments row with injury-based penalty factors."""
    n              = len(injured_players)
    attack_factor  = (1.0 - _get_config(conn, "INJURY_ATTACK_PENALTY"))  ** n
    defense_factor = (1.0 + _get_config(conn, "INJURY_DEFENSE_PENALTY")) ** n

    AvailabilityRepository(conn).insert_context_adjustment(
        team_id=team_id,
        attack_factor=attack_factor,
        defense_factor=defense_factor,
        notes=f"Injured: {', '.join(injured_players)}",
    )
    logger.info(
        "Penalty applied: team=%s injured=%d attack_factor=%.3f defense_factor=%.3f",
        team_id, n, attack_factor, defense_factor,
    )


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_star_players() -> dict[str, list[str]]:
    path = _raw_path() / "star_players.json"
    if not path.exists():
        logger.warning("star_players.json not found at %s", path)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to load star_players.json: %s", exc)
        return {}


def _raw_path() -> Path:
    configured = Path(settings.DATA_RAW_PATH)
    if configured.is_absolute():
        return configured
    project_root = Path(__file__).parent.parent.parent.parent.parent
    return (project_root / configured).resolve()


def _resolve_team_id(conn: sqlite3.Connection, key: str) -> str | None:
    """Look up team by ID or canonical name."""
    row = conn.execute(
        "SELECT id FROM teams WHERE id = ? OR name = ? COLLATE NOCASE",
        (key, key),
    ).fetchone()
    return row["id"] if row else None


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return ""


def _slugify(text: str) -> str:
    replacements = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    return text.lower().translate(replacements).replace(" ", "_")
