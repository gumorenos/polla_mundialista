"""Tests for the news/injury detection module."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from app.db.migrations import run_migrations


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db(team_id: str = "FRA", team_name: str = "Francia") -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (team_id, team_name)
    )
    conn.commit()
    return conn


def _article(url: str, domain: str = "espn.com") -> dict:
    return {
        "url":           url,
        "title":         "Player injury report",
        "source_domain": domain,
        "published_at":  "2026-06-10T12:00:00+00:00",
        "snippet":       "Player is confirmed injured and will miss the tournament.",
    }


_CONFIRMED = {
    "status":          "CONFIRMED",
    "confidence":      0.95,
    "reasoning":       "Article clearly states player injured",
    "miss_tournament": True,
}

_UNRELATED = {
    "status":          "UNRELATED",
    "confidence":      0.0,
    "reasoning":       "Classification unavailable",
    "miss_tournament": False,
}


# ---------------------------------------------------------------------------
# 1. Two sources → penalty applied
# ---------------------------------------------------------------------------

class TestTwoSourcesApplyPenalty:
    def test_penalty_persisted_in_context_adjustments(self):
        from app.services.news.availability import run_news_analysis

        conn = _make_db()
        two_articles = [
            _article("https://espn.com/mbappe-1", "espn.com"),
            _article("https://bbc.com/mbappe-2",  "bbc.com"),
        ]

        with (
            patch(
                "app.services.news.availability._load_star_players",
                return_value={"Francia": ["Kylian Mbappé"]},
            ),
            patch(
                "app.services.news.availability.search_player_news",
                return_value=two_articles,
            ),
            patch(
                "app.services.news.availability.extract_article_text",
                return_value="Mbappé is confirmed injured and will miss WC2026.",
            ),
            patch(
                "app.services.news.availability.classify_injury",
                return_value=_CONFIRMED,
            ),
        ):
            result = run_news_analysis(conn)

        assert "FRA" in result["affected_teams"]
        assert any(p["player"] == "Kylian Mbappé" for p in result["injured_players"])

        row = conn.execute(
            "SELECT attack_factor FROM team_context_adjustments WHERE team_id = 'FRA'"
        ).fetchone()
        assert row is not None, "Expected a context_adjustment row for FRA"
        assert row["attack_factor"] < 1.0, (
            f"Expected attack_factor < 1.0 (penalty applied), got {row['attack_factor']}"
        )
        conn.close()

    def test_availability_claims_inserted(self):
        from app.services.news.availability import run_news_analysis

        conn = _make_db()
        two_articles = [
            _article("https://espn.com/a", "espn.com"),
            _article("https://bbc.com/b",  "bbc.com"),
        ]

        with (
            patch("app.services.news.availability._load_star_players",
                  return_value={"Francia": ["Kylian Mbappé"]}),
            patch("app.services.news.availability.search_player_news",
                  return_value=two_articles),
            patch("app.services.news.availability.extract_article_text",
                  return_value="Confirmed injury"),
            patch("app.services.news.availability.classify_injury",
                  return_value=_CONFIRMED),
        ):
            run_news_analysis(conn)

        claims = conn.execute(
            "SELECT * FROM availability_claims WHERE team_id = 'FRA'"
        ).fetchall()
        assert len(claims) == 2, f"Expected 2 availability claims, got {len(claims)}"
        conn.close()


# ---------------------------------------------------------------------------
# 2. Single source → NO penalty (below NEWS_MIN_SOURCES = 2)
# ---------------------------------------------------------------------------

class TestSingleSourceNoPenalty:
    def test_one_source_below_threshold_no_adjustment(self):
        from app.services.news.availability import run_news_analysis

        conn = _make_db()
        one_article = [_article("https://espn.com/mbappe-1", "espn.com")]

        with (
            patch("app.services.news.availability._load_star_players",
                  return_value={"Francia": ["Kylian Mbappé"]}),
            patch("app.services.news.availability.search_player_news",
                  return_value=one_article),
            patch("app.services.news.availability.extract_article_text",
                  return_value="Mbappé injured."),
            patch("app.services.news.availability.classify_injury",
                  return_value=_CONFIRMED),
        ):
            result = run_news_analysis(conn)

        # One confirmed source < NEWS_MIN_SOURCES (2) → no penalty
        assert "FRA" not in result["affected_teams"]

        row = conn.execute(
            "SELECT * FROM team_context_adjustments WHERE team_id = 'FRA'"
        ).fetchone()
        assert row is None, "Expected no context_adjustment for single-source injury"
        conn.close()


# ---------------------------------------------------------------------------
# 3. Invalid JSON from LLM → no crash, returns UNRELATED
# ---------------------------------------------------------------------------

class TestInvalidJsonReturnsUnrelated:
    def test_invalid_json_string(self):
        from app.services.news.llm_classifier import classify_injury

        with patch(
            "app.services.news.llm_classifier._call_openrouter",
            return_value="this is not json at all !!!",
        ):
            result = classify_injury("Mbappé", "Francia", "Some article text here.")

        assert result["status"] == "UNRELATED", (
            f"Expected UNRELATED on invalid JSON, got {result['status']}"
        )
        assert result["miss_tournament"] is False

    def test_partial_json_returns_unrelated(self):
        from app.services.news.llm_classifier import classify_injury

        with patch(
            "app.services.news.llm_classifier._call_openrouter",
            return_value='{"status": "CONFIRMED"',   # truncated, not valid JSON
        ):
            result = classify_injury("Kane", "Inglaterra", "Harry Kane is injured")

        assert result["status"] == "UNRELATED"

    def test_wrong_field_types_return_unrelated(self):
        from app.services.news.llm_classifier import classify_injury

        with patch(
            "app.services.news.llm_classifier._call_openrouter",
            return_value='{"status": "CONFIRMED", "confidence": "high", '
                         '"reasoning": "ok", "miss_tournament": "yes"}',
        ):
            result = classify_injury("Kane", "Inglaterra", "text")

        # confidence="high" fails Pydantic validation → UNRELATED
        assert result["status"] == "UNRELATED"


# ---------------------------------------------------------------------------
# 4. source_credibility ordering
# ---------------------------------------------------------------------------

class TestSourceCredibility:
    def test_theathletic_is_tier_high(self):
        from app.services.news.scraper import source_credibility
        assert source_credibility("theathletic.com") == 1.0

    def test_bbc_is_tier_high(self):
        from app.services.news.scraper import source_credibility
        assert source_credibility("bbc.com") == 1.0

    def test_unknown_blog_is_low(self):
        from app.services.news.scraper import source_credibility
        assert source_credibility("unknown-blog.com") == pytest.approx(0.3)

    def test_known_source_above_unknown(self):
        from app.services.news.scraper import source_credibility
        assert source_credibility("theathletic.com") > source_credibility("unknown-blog.com")

    def test_espn_is_trusted(self):
        from app.services.news.scraper import source_credibility
        assert source_credibility("espn.com") == pytest.approx(0.8)

    def test_www_prefix_stripped(self):
        from app.services.news.scraper import source_credibility
        assert source_credibility("www.theathletic.com") == 1.0


# ---------------------------------------------------------------------------
# 5. Complete LLM failure → no crash, no context adjustment
# ---------------------------------------------------------------------------

class TestLlmCompleteFailure:
    def test_llm_exception_no_crash(self):
        from app.services.news.availability import run_news_analysis

        conn = _make_db()
        one_article = [_article("https://espn.com/x", "espn.com")]

        with (
            patch("app.services.news.availability._load_star_players",
                  return_value={"Francia": ["Kylian Mbappé"]}),
            patch("app.services.news.availability.search_player_news",
                  return_value=one_article),
            patch("app.services.news.availability.extract_article_text",
                  return_value="Player injured text."),
            patch("app.services.news.availability.classify_injury",
                  side_effect=Exception("LLM service unreachable")),
        ):
            # Must not raise
            result = run_news_analysis(conn)

        assert isinstance(result, dict)  # returned normally

    def test_no_context_adjustment_when_llm_fails(self):
        from app.services.news.availability import run_news_analysis

        conn = _make_db()
        two_articles = [
            _article("https://espn.com/a", "espn.com"),
            _article("https://bbc.com/b",  "bbc.com"),
        ]

        with (
            patch("app.services.news.availability._load_star_players",
                  return_value={"Francia": ["Kylian Mbappé"]}),
            patch("app.services.news.availability.search_player_news",
                  return_value=two_articles),
            patch("app.services.news.availability.extract_article_text",
                  return_value="text"),
            patch("app.services.news.availability.classify_injury",
                  side_effect=Exception("LLM down")),
        ):
            run_news_analysis(conn)

        row = conn.execute(
            "SELECT * FROM team_context_adjustments WHERE team_id = 'FRA'"
        ).fetchone()
        assert row is None, (
            "Expected no context_adjustment when LLM fails for all articles"
        )
        conn.close()

    def test_unknown_team_skipped_gracefully(self):
        from app.services.news.availability import run_news_analysis

        conn = _make_db()

        with (
            patch("app.services.news.availability._load_star_players",
                  return_value={"Neverland FC": ["Ghost Player"]}),
        ):
            result = run_news_analysis(conn)

        assert result["affected_teams"] == []
        conn.close()
