"""Tests for the ELO-as-prior blend in PoissonModel._get_strength.

Diagnosed root cause (post-deploy, 2026-07-01): a team with elite ELO but a
small/noisy historical sample (e.g. Argentina, elo=2074 but attack_strength
computed at ~1.006 from 38 matches including implausible historical losses)
could end up valued near the population average in Poisson. This blend
anchors low-data teams toward their ELO tier without ever fully overriding
an empirically well-supported strength.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.prediction.poisson_model import (
    PoissonModel,
    _elo_attack_defense_prior,
    _elo_prior_weight,
)


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    return conn


def _seed_team(conn, team_id, attack=1.0, defense=1.0, matches_used=30, elo=None):
    conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (team_id, team_id))
    conn.execute(
        "INSERT INTO team_strengths (id, team_id, attack_strength, defense_vulnerability, matches_used) "
        "VALUES (?, ?, ?, ?, ?)",
        (f"ts_{team_id}", team_id, attack, defense, matches_used),
    )
    if elo is not None:
        conn.execute(
            "INSERT INTO ratings (id, team_id, rating_type, value, effective_date) VALUES (?, ?, 'elo', ?, '2026-06-01')",
            (f"elo_{team_id}", team_id, elo),
        )
    conn.commit()


class TestEloPriorWeight:
    def test_weight_is_base_when_matches_used_meets_minimum(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_WEIGHT", 0.25)
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_MIN_MATCHES", 10)
        assert _elo_prior_weight(10) == pytest.approx(0.25)
        assert _elo_prior_weight(50) == pytest.approx(0.25)

    def test_weight_grows_toward_max_weight_as_matches_used_drops(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_WEIGHT", 0.25)
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_MIN_MATCHES", 10)
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_MAX_WEIGHT", 1.0)
        assert _elo_prior_weight(0) == pytest.approx(1.0)
        w5 = _elo_prior_weight(5)
        assert 0.25 < w5 < 1.0

    def test_weight_clamped_by_max_weight(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_WEIGHT", 0.25)
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_MIN_MATCHES", 10)
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_MAX_WEIGHT", 0.5)
        # Without the cap, matches_used=0 would give w=1.0 — the cap must hold it at 0.5.
        assert _elo_prior_weight(0) == pytest.approx(0.5)
        assert _elo_prior_weight(50) == pytest.approx(0.25)

    def test_disabled_returns_zero_weight_regardless_of_matches_used(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_ENABLED", False)
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_WEIGHT", 0.25)
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_MIN_MATCHES", 10)
        assert _elo_prior_weight(0) == 0.0
        assert _elo_prior_weight(100) == 0.0


class TestEloAttackDefensePrior:
    def test_elite_elo_yields_above_average_attack_and_below_average_defense_vuln(self):
        attack, defense = _elo_attack_defense_prior(2074)
        assert attack > 1.0
        assert defense < 1.0

    def test_neutral_elo_yields_neutral_priors(self):
        attack, defense = _elo_attack_defense_prior(1500)
        assert attack == pytest.approx(1.0)
        assert defense == pytest.approx(1.0)

    def test_bounded(self):
        attack, defense = _elo_attack_defense_prior(4000)
        assert attack <= 2.0
        attack2, defense2 = _elo_attack_defense_prior(-1000)
        assert defense2 <= 2.0
        assert attack2 >= 0.4


class TestPoissonModelBlend:
    def test_high_elo_low_matches_team_not_stuck_near_average(self):
        """A team with elite ELO but very few matches must not be valued at
        the population-average strength — the ELO prior should pull it up."""
        conn = _make_db()
        # 3 matches only — well below default min (10) — near-average empirical strength.
        _seed_team(conn, "ARG", attack=1.006, defense=1.005, matches_used=3, elo=2074)
        model = PoissonModel(conn)

        attack, defense, found = model._get_strength("ARG")
        assert found is True
        assert attack > 1.1  # pulled meaningfully above the near-1.0 empirical value
        conn.close()

    def test_high_matches_used_keeps_empirical_strength_dominant(self):
        """A team with a solid historical sample keeps its empirical strength
        — ELO only nudges it slightly (small base weight)."""
        conn = _make_db()
        _seed_team(conn, "POL", attack=1.22, defense=1.0, matches_used=500, elo=1700)
        model = PoissonModel(conn)

        attack, defense, found = model._get_strength("POL")
        assert found is True
        # Base weight is small (0.25 default) — result stays close to empirical.
        assert abs(attack - 1.22) < 0.15
        conn.close()

    def test_no_elo_data_falls_back_to_pure_empirical(self):
        conn = _make_db()
        _seed_team(conn, "XXX", attack=1.3, defense=0.9, matches_used=5, elo=None)
        model = PoissonModel(conn)

        attack, defense, found = model._get_strength("XXX")
        assert found is True
        assert attack == pytest.approx(1.3)
        assert defense == pytest.approx(0.9)
        conn.close()

    def test_no_strength_data_but_elo_known_uses_pure_prior(self):
        conn = _make_db()
        conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES ('NEW', 'NEW')")
        conn.execute(
            "INSERT INTO ratings (id, team_id, rating_type, value, effective_date) "
            "VALUES ('elo_new', 'NEW', 'elo', 1900, '2026-06-01')"
        )
        conn.commit()
        model = PoissonModel(conn)

        attack, defense, found = model._get_strength("NEW")
        assert found is True
        assert attack > 1.0

    def test_lambdas_stay_within_sane_bounds(self):
        """End-to-end: predict_match must not explode even for an extreme
        ELO team with almost no historical data."""
        conn = _make_db()
        _seed_team(conn, "ARG", attack=1.0, defense=1.0, matches_used=1, elo=2400)
        _seed_team(conn, "OPP", attack=1.0, defense=1.0, matches_used=1, elo=1200)
        model = PoissonModel(conn)

        result = model.predict_match("ARG", "OPP", context={"is_neutral": True})
        assert 0.1 <= result["expected_home_goals"] <= 8.0
        assert 0.1 <= result["expected_away_goals"] <= 8.0
        assert result["home_win"] > result["away_win"]
        conn.close()

    def test_disabled_ignores_elo_and_keeps_pure_empirical(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_ENABLED", False)
        conn = _make_db()
        _seed_team(conn, "ARG", attack=1.006, defense=1.005, matches_used=3, elo=2074)
        model = PoissonModel(conn)

        attack, defense, found = model._get_strength("ARG")
        assert found is True
        assert attack == pytest.approx(1.006)
        assert defense == pytest.approx(1.005)
        conn.close()

    def test_disabled_with_no_strength_entry_falls_back_to_defaults(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.POISSON_ELO_PRIOR_ENABLED", False)
        conn = _make_db()
        conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES ('NEW', 'NEW')")
        conn.execute(
            "INSERT INTO ratings (id, team_id, rating_type, value, effective_date) "
            "VALUES ('elo_new', 'NEW', 'elo', 1900, '2026-06-01')"
        )
        conn.commit()
        model = PoissonModel(conn)

        attack, defense, found = model._get_strength("NEW")
        assert found is False
        assert attack == 1.0 and defense == 1.0
        conn.close()

    def test_no_data_at_all_keeps_defaults(self):
        conn = _make_db()
        conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES ('ZZZ', 'ZZZ')")
        conn.commit()
        model = PoissonModel(conn)

        attack, defense, found = model._get_strength("ZZZ")
        assert found is False
        assert attack == 1.0 and defense == 1.0
        conn.close()


class TestPoissonContextXgBlend:
    """PoissonContextModel's xG override must not bypass the ELO prior for
    teams whose xG sample (StatsBomb WC matches) is itself small."""

    def _seed_xg(self, conn, team_id, xg, xgc, n, elo=None):
        conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (team_id, team_id))
        for i in range(n):
            conn.execute(
                "INSERT INTO sb_match_stats (id, team_id, match_id, is_home, xg, xg_conceded) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (f"sb_{team_id}_{i}", team_id, hash(f"{team_id}_{i}") % 1_000_000, xg, xgc),
            )
        if elo is not None:
            conn.execute(
                "INSERT INTO ratings (id, team_id, rating_type, value, effective_date) VALUES (?, ?, 'elo', ?, '2026-06-01')",
                (f"elo_{team_id}", team_id, elo),
            )
        conn.commit()

    def test_small_xg_sample_blends_with_elo_prior(self, monkeypatch):
        from app.services.prediction.poisson_context import PoissonContextModel

        conn = _make_db()
        # Exactly at the _load_xg_map threshold (>=3) but still a tiny, noisy sample.
        self._seed_xg(conn, "ARG", xg=0.5, xgc=0.5, n=3, elo=2074)
        self._seed_xg(conn, "OPP", xg=1.0, xgc=1.0, n=3, elo=1500)
        model = PoissonContextModel(conn)

        attack, defense, found = model._get_strength("ARG")
        assert found is True
        # Raw xG ratio alone would be ~0.5 (well below average) — the ELO
        # prior blend must pull it up toward ARG's elite tier.
        assert attack > 0.6
        conn.close()

    def test_large_xg_sample_stays_close_to_raw_xg(self, monkeypatch):
        from app.services.prediction.poisson_context import PoissonContextModel

        conn = _make_db()
        self._seed_xg(conn, "TEAM", xg=1.3, xgc=0.8, n=50, elo=1400)
        model = PoissonContextModel(conn)

        attack, defense, found = model._get_strength("TEAM")
        assert found is True
        # matches_used=50 is well above the min threshold — only the small
        # base weight (0.25) applies, so the result stays close to the raw
        # xG-derived attack (here 1.0, since TEAM is also the sole sample
        # behind the global average).
        assert abs(attack - 1.0) < 0.1
        conn.close()
