"""The Odds API integration — tournament winner (outright) odds.

Plan gratuito: 500 requests/mes. Llamar cada 6h = ~120 req/mes.
Docs: https://the-odds-api.com/liveapi/guides/v4/
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# English → Spanish name overrides for teams stored with Spanish names in DB
_EN_TO_ES: dict[str, str] = {
    "brazil":                  "brasil",
    "spain":                   "españa",
    "france":                  "francia",
    "germany":                 "alemania",
    "england":                 "inglaterra",
    "united states":           "estados unidos",
    "usa":                     "estados unidos",
    "south korea":             "corea del sur",
    "north korea":             "corea del norte",
    "ivory coast":             "costa de marfil",
    "netherlands":             "países bajos",
    "holland":                 "países bajos",
    "morocco":                 "marruecos",
    "iran":                    "irán",
    "switzerland":             "suiza",
    "denmark":                 "dinamarca",
    "turkey":                  "turquía",
    "czechia":                 "república checa",
    "czech republic":          "república checa",
    "cameroon":                "camerún",
    "saudi arabia":            "arabia saudita",
    "japan":                   "japón",
    "mexico":                  "méxico",
    "peru":                    "perú",
    "canada":                  "canadá",
    "panama":                  "panamá",
    "croatia":                 "croacia",
    "poland":                  "polonia",
    "ukraine":                 "ucrania",
    "sweden":                  "suecia",
    "norway":                  "noruega",
    "greece":                  "grecia",
    "hungary":                 "hungría",
    "romania":                 "rumania",
    "united arab emirates":    "emiratos árabes unidos",
    "new zealand":             "nueva zelanda",
    "wales":                   "gales",
}


# ---------------------------------------------------------------------------
# Public entry point (no raw SQL — all DB access via OddsRepository)
# ---------------------------------------------------------------------------

def fetch_and_store_odds() -> dict[str, Any]:
    """Fetch tournament winner odds from The Odds API and persist to DB.

    Returns a summary dict. Never raises — logs errors instead.
    """
    if not settings.ODDS_API_KEY:
        logger.info("odds_api: ODDS_API_KEY not configured — skipping fetch")
        return {"fetched": 0, "skipped": True, "reason": "no_api_key"}

    try:
        raw_events = _fetch_outrights()
    except Exception as exc:
        logger.warning("odds_api: fetch failed: %s", exc)
        return {"fetched": 0, "skipped": False, "error": str(exc)}

    if not raw_events:
        logger.info("odds_api: no outright events returned by API")
        return {"fetched": 0, "skipped": False}

    from app.db.connection import db_transaction
    from app.db.repositories.odds import OddsRepository

    with db_transaction() as conn:
        repo = OddsRepository(conn)
        team_map = repo.get_team_name_map()
        entries = _parse_outrights(raw_events, team_map)
        if entries:
            repo.replace_all(entries)
            conn.commit()

    logger.info(
        "odds_api: stored %d odds entries from %d events",
        len(entries),
        len(raw_events),
    )
    return {"fetched": len(entries), "skipped": False}


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def _fetch_outrights() -> list[dict[str, Any]]:
    url = f"{settings.ODDS_API_BASE_URL}/sports/{settings.ODDS_API_SPORT}/odds/"
    params = {
        "apiKey":      settings.ODDS_API_KEY,
        "regions":     "eu",
        "markets":     "outrights",
        "oddsFormat":  "decimal",
    }
    with httpx.Client(timeout=20) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("odds_api: requests remaining this month: %s", remaining)
    return resp.json()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_outrights(
    events: list[dict[str, Any]],
    team_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Extract one entry per (team, bookmaker) with normalized implied probability."""
    entries: list[dict[str, Any]] = []

    for event in events:
        for bm in event.get("bookmakers", []):
            bookmaker = bm.get("title") or bm.get("key", "unknown")
            for market in bm.get("markets", []):
                if market.get("key") != "outrights":
                    continue
                outcomes = [
                    o for o in market.get("outcomes", [])
                    if isinstance(o.get("price"), (int, float)) and o["price"] > 1.0
                ]
                if not outcomes:
                    continue

                # Remove overround: normalise so probabilities sum to 1
                total_raw = sum(1.0 / o["price"] for o in outcomes)
                if total_raw <= 0:
                    continue

                for o in outcomes:
                    team_id = _resolve_team(o["name"], team_map)
                    if not team_id:
                        continue
                    implied_prob = (1.0 / o["price"]) / total_raw
                    entries.append({
                        "team_id":     team_id,
                        "bookmaker":   bookmaker,
                        "decimal_odd": round(float(o["price"]), 4),
                        "implied_prob": round(implied_prob, 6),
                    })

    return entries


def _resolve_team(name: str, team_map: dict[str, str]) -> str | None:
    """Try to map a team name from the API to an internal team_id."""
    lower = name.strip().lower()

    # 1. Direct lowercase match
    if lower in team_map:
        return team_map[lower]

    # 2. English → Spanish override
    translated = _EN_TO_ES.get(lower)
    if translated and translated in team_map:
        return team_map[translated]

    # 3. Prefix match (e.g. "Côte d'Ivoire" → "costa de marfil")
    for db_name, tid in team_map.items():
        if lower.startswith(db_name) or db_name.startswith(lower):
            return tid

    logger.debug("odds_api: unresolved team %r — skipping", name)
    return None


def decimal_to_probability(decimal_odd: float) -> float:
    """Raw (non-normalised) implied probability."""
    return 1.0 / decimal_odd


def calculate_value(oraculo_prob: float, market_prob: float) -> float:
    """Positive = Oráculo more optimistic than market."""
    return round(oraculo_prob - market_prob, 6)
