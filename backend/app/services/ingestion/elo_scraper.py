"""ELO ratings scraper for eloratings.net.

Strategy:
1. Try scraping the live page.
2. On any failure (network, parse, rate-limit), fall back to elo_ratings.csv
   and log a WARNING so the operator knows fresh data wasn't fetched.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import NamedTuple

from bs4 import BeautifulSoup
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.ratings import RatingRepository
from app.db.repositories.teams import TeamRepository
from app.services.normalization.team_names import normalize_team_name

logger = logging.getLogger(__name__)

_ELO_URL = settings.ELO_URL.rstrip("/")


class EloEntry(NamedTuple):
    team: str        # canonical Spanish name
    elo: int
    rank: int


# ---------------------------------------------------------------------------
# Scraping (live)
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
def _fetch_html(url: str) -> str:
    import httpx
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        resp = client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; OraculoMundial/1.0)"},
        )
        resp.raise_for_status()
        return resp.text


def _parse_elo_html(html: str) -> list[EloEntry]:
    """Parse the eloratings.net HTML and return a list of EloEntry."""
    soup = BeautifulSoup(html, "lxml")
    entries: list[EloEntry] = []

    # eloratings.net structure: table rows with td[0]=rank, td[1]=flag+name, td[2]=elo
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            try:
                rank = int(tds[0].get_text(strip=True))
                name_raw = tds[1].get_text(strip=True)
                elo = int(tds[2].get_text(strip=True).replace(",", ""))
                canonical = normalize_team_name(name_raw)
                entries.append(EloEntry(team=canonical, elo=elo, rank=rank))
            except (ValueError, IndexError):
                continue

    return entries


def scrape_elo_ratings() -> list[EloEntry]:
    """Attempt to scrape live ELO ratings; returns empty list on failure."""
    url = f"{_ELO_URL}/en/club/national"
    try:
        html = _fetch_html(url)
        entries = _parse_elo_html(html)
        logger.info("ELO scraper: extracted %d entries from %s", len(entries), url)
        return entries
    except (RetryError, Exception) as exc:
        logger.warning("ELO scrape failed (%s) — caller should use CSV fallback", exc)
        return []


# ---------------------------------------------------------------------------
# Fallback: load from CSV
# ---------------------------------------------------------------------------

def _load_elo_from_csv() -> list[EloEntry]:
    from app.services.ingestion.csv_loader import _read_csv, _raw_path

    path = _raw_path() / "elo_ratings.csv"
    df = _read_csv(path, "elo_fallback")
    if df is None:
        return []

    entries: list[EloEntry] = []
    for _, row in df.iterrows():
        try:
            canonical = normalize_team_name(str(row["team"]).strip())
            entries.append(
                EloEntry(
                    team=canonical,
                    elo=int(float(row["elo_rating"])),
                    rank=int(row["rank"]),
                )
            )
        except (ValueError, KeyError):
            continue
    return entries


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest_elo_ratings(
    conn: sqlite3.Connection | None = None,
    effective_date: str | None = None,
) -> int:
    """Scrape ELO ratings (with CSV fallback) and persist via RatingRepository.

    Returns the number of ratings saved.
    """
    t0 = time.perf_counter()
    from datetime import date as _date

    eff_date = effective_date or _date.today().isoformat()

    entries = scrape_elo_ratings()
    source = "scrape"
    if not entries:
        logger.warning("ELO scraper returned 0 entries — falling back to CSV")
        entries = _load_elo_from_csv()
        source = "csv_fallback"

    if not entries:
        logger.error("ELO ingest: no data available from scraper or CSV")
        return 0

    def _persist(c: sqlite3.Connection) -> int:
        team_repo = TeamRepository(c)
        rating_repo = RatingRepository(c)
        count = 0
        for entry in entries:
            try:
                team = team_repo.get_by_name(entry.team)
                tid = team["id"] if team else entry.team
                if not team:
                    team_repo.upsert({"id": entry.team, "name": entry.team})
                rating_repo.upsert_elo(
                    team_id=tid,
                    value=float(entry.elo),
                    effective_date=eff_date,
                    source=source,
                )
                count += 1
            except Exception as exc:
                logger.warning("ELO persist error for %s: %s", entry.team, exc)
        return count

    elapsed = time.perf_counter() - t0

    if conn is not None:
        n = _persist(conn)
        conn.commit()
    else:
        with db_transaction() as c:
            n = _persist(c)

    logger.info(
        "ELO ingest complete: source=%s teams=%d elapsed=%.2fs",
        source, n, elapsed,
    )
    return n
