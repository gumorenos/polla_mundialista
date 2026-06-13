"""News scraper — Google News RSS + BeautifulSoup article extraction.

In-memory cache avoids repeated HTTP requests within one execution context.
All failures are logged at WARNING and return empty values (no crash).
"""

from __future__ import annotations

import logging
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10  # seconds
_AGENT = "Mozilla/5.0 (compatible; OraculoMundial/1.0)"
_TIER_HIGH = frozenset({"theathletic.com", "bbc.com", "bbc.co.uk"})

# In-memory cache: cache_key → list[article_dict]
_CACHE: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_player_news(country: str, player: str, days_back: int) -> list[dict]:
    """Search Google News RSS for player injury news.

    Returns list of dicts: {url, title, source_domain, published_at, snippet}.
    """
    cache_key = f"{country}|{player}|{days_back}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    try:
        results = _fetch_google_news_rss(player, country, days_back)
        _CACHE[cache_key] = results
        return results
    except Exception as exc:
        logger.warning("search_player_news failed for %s/%s: %s", country, player, exc)
        return []


def extract_article_text(url: str) -> str:
    """Extract main article text using BeautifulSoup paragraph heuristic.

    Falls back to empty string on any error.
    """
    try:
        resp = _fetch_url(url)
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(strip=True) for p in paragraphs[:30])
        return text.strip()
    except Exception as exc:
        logger.warning("extract_article_text failed for %s: %s", url, exc)
        return ""


def source_credibility(domain: str) -> float:
    """Return credibility score 0-1 based on source domain.

    Tier high (theathletic, bbc): 1.0
    Listed in FUENTES_CONFIABLES:   0.8
    Unknown:                        0.3
    """
    domain = domain.lower().strip().removeprefix("www.")
    if domain in _TIER_HIGH:
        return 1.0
    trusted = {d.lower().removeprefix("www.") for d in settings.FUENTES_CONFIABLES}
    if domain in trusted:
        return 0.8
    return 0.3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _fetch_url(url: str) -> httpx.Response:
    """HTTP GET with exponential retry on timeout/connection errors."""
    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": _AGENT})
        resp.raise_for_status()
        return resp


def _fetch_google_news_rss(
    player: str, country: str, days_back: int
) -> list[dict]:
    query = urllib.parse.quote(f"{player} {country} injury lesion")
    url = (
        f"https://news.google.com/rss/search"
        f"?q={query}&hl=en&gl=US&ceid=US:en"
    )

    try:
        resp = _fetch_url(url)
    except Exception as exc:
        logger.warning("_fetch_google_news_rss: all retries failed for %s: %s", url, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    root   = ET.fromstring(resp.text)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[dict] = []
    for item in channel.findall("item"):
        link    = (item.findtext("link")  or "").strip()
        title   = (item.findtext("title") or "").strip()
        snippet = (item.findtext("description") or "").strip()
        pub_str = (item.findtext("pubDate") or "").strip()

        try:
            pub_dt = datetime.strptime(pub_str, "%a, %d %b %Y %H:%M:%S %z")
        except ValueError:
            pub_dt = datetime.now(timezone.utc)

        if pub_dt < cutoff:
            continue

        items.append({
            "url":           link,
            "title":         title,
            "source_domain": _domain(link),
            "published_at":  pub_dt.isoformat(),
            "snippet":       snippet[:500],
        })

    return items


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return ""
