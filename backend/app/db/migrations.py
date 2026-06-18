"""Idempotent schema migrations — CREATE TABLE IF NOT EXISTS only, never DROP.

Rules:
- Only CREATE TABLE IF NOT EXISTS and ALTER TABLE ADD COLUMN (guarded).
- Never DROP or UPDATE existing column definitions.
- New migrations appended to _MIGRATIONS list.
- run_migrations() accepts an optional connection for in-memory testing.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _add_col(conn: sqlite3.Connection, table: str, col: str, definition: str) -> None:
    """Add a column if it does not already exist — safe to call repeatedly."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
    except sqlite3.OperationalError:
        pass  # Column already exists


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------

def _m001_create_all_tables(conn: sqlite3.Connection) -> None:
    """Create the full application schema (idempotent via IF NOT EXISTS)."""
    stmts = [
        # ---- Reference data ------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS teams (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL UNIQUE,
            code            TEXT,
            confederation   TEXT,
            is_host         INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            updated_at      TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS groups (
            id          TEXT PRIMARY KEY,
            tournament  TEXT NOT NULL DEFAULT 'WC2026',
            created_at  TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS group_teams (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    TEXT NOT NULL REFERENCES groups(id),
            team_id     TEXT NOT NULL REFERENCES teams(id),
            UNIQUE (group_id, team_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fixtures (
            id              TEXT PRIMARY KEY,
            stage           TEXT NOT NULL,
            group_id        TEXT REFERENCES groups(id),
            home_team_id    TEXT REFERENCES teams(id),
            away_team_id    TEXT REFERENCES teams(id),
            match_date      TEXT,
            venue           TEXT,
            is_neutral      INTEGER DEFAULT 1,
            tournament      TEXT DEFAULT 'WC2026',
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS results (
            id              TEXT PRIMARY KEY,
            fixture_id      TEXT REFERENCES fixtures(id),
            home_team_id    TEXT NOT NULL REFERENCES teams(id),
            away_team_id    TEXT NOT NULL REFERENCES teams(id),
            home_goals      INTEGER,
            away_goals      INTEGER,
            outcome         TEXT,
            match_date      TEXT NOT NULL,
            tournament      TEXT,
            stage           TEXT,
            is_wc           INTEGER DEFAULT 0,
            source          TEXT,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ratings (
            id              TEXT PRIMARY KEY,
            team_id         TEXT NOT NULL REFERENCES teams(id),
            rating_type     TEXT NOT NULL,
            value           REAL NOT NULL,
            rank            INTEGER,
            effective_date  TEXT NOT NULL,
            source          TEXT,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS team_strengths (
            id                      TEXT PRIMARY KEY,
            team_id                 TEXT NOT NULL REFERENCES teams(id),
            attack_strength         REAL NOT NULL,
            defense_vulnerability   REAL NOT NULL,
            matches_used            INTEGER,
            cutoff_date             TEXT,
            decay_factor            REAL,
            computed_at             TEXT NOT NULL
                                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        # ---- Availability & context ----------------------------------------
        """
        CREATE TABLE IF NOT EXISTS availability_claims (
            id              TEXT PRIMARY KEY,
            team_id         TEXT REFERENCES teams(id),
            player_name     TEXT NOT NULL,
            player_key      TEXT,
            status          TEXT NOT NULL,
            reason          TEXT,
            source_url      TEXT,
            source_name     TEXT,
            confidence      REAL,
            evidence_level  TEXT,
            observed_at     TEXT NOT NULL,
            affects_prediction INTEGER DEFAULT 0,
            raw_json        TEXT,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS team_context_adjustments (
            id              TEXT PRIMARY KEY,
            team_id         TEXT NOT NULL REFERENCES teams(id),
            fixture_id      TEXT REFERENCES fixtures(id),
            adjustment_type TEXT NOT NULL,
            attack_factor   REAL DEFAULT 1.0,
            defense_factor  REAL DEFAULT 1.0,
            notes           TEXT,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        # ---- Predictions ---------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS prediction_runs (
            id                  TEXT PRIMARY KEY,
            model_set           TEXT,
            status              TEXT DEFAULT 'pending',
            data_version_hash   TEXT,
            config_snapshot     TEXT,
            started_at          TEXT,
            finished_at         TEXT,
            error_message       TEXT,
            created_at          TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS match_predictions (
            id                  TEXT PRIMARY KEY,
            run_id              TEXT NOT NULL REFERENCES prediction_runs(id),
            fixture_id          TEXT REFERENCES fixtures(id),
            model_name          TEXT NOT NULL,
            model_version       TEXT,
            home_win            REAL,
            draw                REAL,
            away_win            REAL,
            expected_home_goals REAL,
            expected_away_goals REAL,
            most_likely_score   TEXT,
            features_used       TEXT,
            features_missing    TEXT,
            explanation         TEXT,
            created_at          TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        # ---- Simulations ---------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS simulation_runs (
            id                  TEXT PRIMARY KEY,
            prediction_run_id   TEXT REFERENCES prediction_runs(id),
            model_name          TEXT NOT NULL,
            status              TEXT DEFAULT 'pending',
            iterations          INTEGER DEFAULT 30000,
            seed                INTEGER DEFAULT 42,
            data_version_hash   TEXT,
            config_snapshot     TEXT,
            started_at          TEXT,
            finished_at         TEXT,
            error_message       TEXT,
            created_at          TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS simulation_team_results (
            id                      TEXT PRIMARY KEY,
            simulation_run_id       TEXT NOT NULL REFERENCES simulation_runs(id),
            team_id                 TEXT REFERENCES teams(id),
            win_group               REAL,
            qualify                 REAL,
            reach_round_of_32       REAL,
            reach_round_of_16       REAL,
            reach_quarter_final     REAL,
            reach_semi_final        REAL,
            reach_final             REAL,
            win_tournament          REAL,
            expected_group_points   REAL,
            created_at              TEXT NOT NULL
                                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        # ---- Jobs ----------------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            rq_job_id       TEXT,
            job_type        TEXT,
            status          TEXT DEFAULT 'enqueued',
            progress        REAL DEFAULT 0.0,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            started_at      TEXT,
            finished_at     TEXT,
            error_message   TEXT,
            result_ref      TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id      TEXT NOT NULL REFERENCES jobs(id),
            level       TEXT NOT NULL,
            message     TEXT NOT NULL,
            created_at  TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        # ---- Machine Learning ----------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS ml_training_runs (
            id                  TEXT PRIMARY KEY,
            algorithm           TEXT NOT NULL,
            train_start_year    INTEGER,
            train_end_date      TEXT,
            validation_split    REAL,
            feature_set         TEXT,
            hyperparams         TEXT,
            status              TEXT DEFAULT 'pending',
            started_at          TEXT,
            finished_at         TEXT,
            error_message       TEXT,
            created_at          TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ml_models (
            id              TEXT PRIMARY KEY,
            training_run_id TEXT REFERENCES ml_training_runs(id),
            algorithm       TEXT NOT NULL,
            model_path      TEXT,
            brier_score     REAL,
            log_loss        REAL,
            accuracy        REAL,
            is_active       INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ml_feature_snapshots (
            id                  TEXT PRIMARY KEY,
            training_run_id     TEXT REFERENCES ml_training_runs(id),
            feature_names       TEXT,
            feature_importances TEXT,
            created_at          TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        # ---- Evaluations ---------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS model_evaluations (
            id                  TEXT PRIMARY KEY,
            model_name          TEXT NOT NULL,
            model_version       TEXT,
            eval_set            TEXT,
            n_matches           INTEGER,
            brier_score         REAL,
            log_loss            REAL,
            rps                 REAL,
            accuracy            REAL,
            calibration_error   REAL,
            evaluated_at        TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        # ---- Data sources & snapshots ---------------------------------------
        """
        CREATE TABLE IF NOT EXISTS data_sources (
            id              TEXT PRIMARY KEY,
            source_type     TEXT NOT NULL,
            source_name     TEXT,
            url             TEXT,
            last_fetched_at TEXT,
            records_fetched INTEGER,
            status          TEXT,
            error_message   TEXT,
            created_at      TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id                  TEXT PRIMARY KEY,
            label               TEXT,
            description         TEXT,
            trigger             TEXT,
            simulation_run_id   TEXT REFERENCES simulation_runs(id),
            created_at          TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """,
    ]

    for stmt in stmts:
        conn.execute(stmt)

    # Indexes for common query patterns
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_results_home ON results(home_team_id)",
        "CREATE INDEX IF NOT EXISTS idx_results_away ON results(away_team_id)",
        "CREATE INDEX IF NOT EXISTS idx_results_date ON results(match_date)",
        "CREATE INDEX IF NOT EXISTS idx_ratings_team_type ON ratings(team_id, rating_type)",
        "CREATE INDEX IF NOT EXISTS idx_ratings_date ON ratings(effective_date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_strengths_team ON team_strengths(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_pred_run_model ON match_predictions(run_id, model_name)",
        "CREATE INDEX IF NOT EXISTS idx_sim_results_run ON simulation_team_results(simulation_run_id)",
        "CREATE INDEX IF NOT EXISTS idx_avail_team ON availability_claims(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_avail_player ON availability_claims(player_key)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
        "CREATE INDEX IF NOT EXISTS idx_evals_model ON model_evaluations(model_name)",
    ]
    for idx in indexes:
        conn.execute(idx)


def _m002_jobs_extend_schema(conn: sqlite3.Connection) -> None:
    """Extend jobs table with columns from P2 (no-op if already created by m001)."""
    for col, defn in [
        ("rq_job_id",     "TEXT"),
        ("job_type",      "TEXT"),
        ("progress",      "REAL DEFAULT 0.0"),
        ("finished_at",   "TEXT"),
        ("error_message", "TEXT"),
        ("result_ref",    "TEXT"),
    ]:
        _add_col(conn, "jobs", col, defn)


def _m003_group_teams_position(conn: sqlite3.Connection) -> None:
    """Add position column to group_teams so ORDER BY works correctly."""
    _add_col(conn, "group_teams", "position", "INTEGER DEFAULT 0")


def _m004_jobs_last_heartbeat(conn: sqlite3.Connection) -> None:
    """Add last_heartbeat column to jobs for worker liveness detection."""
    _add_col(conn, "jobs", "last_heartbeat", "TEXT")


def _m005_admin_password_history(conn: sqlite3.Connection) -> None:
    """Audit table for admin password changes."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_password_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            changed_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            changed_by   TEXT NOT NULL DEFAULT 'system',
            password_hash TEXT NOT NULL,
            note         TEXT
        )
        """
    )
    _add_col(conn, "admin_password_history", "note", "TEXT")


def _m006_admin_credentials(conn: sqlite3.Connection) -> None:
    """Durable admin credential store for the web login password."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_credentials (
            id            TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _m007_availability_published_at(conn: sqlite3.Connection) -> None:
    """Add published_at column to availability_claims for the RSS article date."""
    _add_col(conn, "availability_claims", "published_at", "TEXT")


_DEFAULT_APP_CONFIG: dict[str, tuple[str, str]] = {
    "NEWS_CONFIDENCE_THRESHOLD": ("0.7", "Confianza mínima del LLM para aplicar ajuste"),
    "INJURY_ATTACK_PENALTY":     ("0.15", "Penalización ataque por lesión (0.0 - 0.5)"),
    "INJURY_DEFENSE_PENALTY":    ("0.05", "Penalización defensa por lesión (0.0 - 0.5)"),
    "NEWS_MIN_SOURCES":          ("2", "Fuentes mínimas para confirmar lesión"),
    "NEWS_DAYS_LOOKBACK":        ("7", "Días de lookback para noticias"),
}


def _m009_ml_models_shap(conn: sqlite3.Connection) -> None:
    """Add shap_importance JSON column to ml_models."""
    _add_col(conn, "ml_models", "shap_importance", "TEXT")


def _m011_market_odds(conn: sqlite3.Connection) -> None:
    """Market odds from The Odds API — bookmaker tournament winner prices."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_odds (
            id           TEXT PRIMARY KEY,
            team_id      TEXT NOT NULL,
            bookmaker    TEXT NOT NULL,
            decimal_odd  REAL NOT NULL,
            implied_prob REAL NOT NULL,
            fetched_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_odds_team "
        "ON market_odds(team_id, bookmaker)"
    )


def _m010_narrative_cache(conn: sqlite3.Connection) -> None:
    """Cache table for LLM-generated team and tournament narratives."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS narrative_cache (
            id           TEXT PRIMARY KEY,
            run_id       TEXT NOT NULL,
            team_id      TEXT,
            model_name   TEXT NOT NULL,
            narrative    TEXT NOT NULL,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_narrative_run_team "
        "ON narrative_cache(run_id, team_id, model_name)"
    )


def _m008_app_config(conn: sqlite3.Connection) -> None:
    """Dynamic configuration table — overrides settings.py values at runtime."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_config (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            description TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for key, (value, description) in _DEFAULT_APP_CONFIG.items():
        conn.execute(
            "INSERT OR IGNORE INTO app_config (key, value, description) VALUES (?, ?, ?)",
            (key, value, description),
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_MIGRATIONS = [
    _m001_create_all_tables,
    _m002_jobs_extend_schema,
    _m003_group_teams_position,
    _m004_jobs_last_heartbeat,
    _m005_admin_password_history,
    _m006_admin_credentials,
    _m007_availability_published_at,
    _m008_app_config,
    _m009_ml_models_shap,
    _m010_narrative_cache,
    _m011_market_odds,
]


def fix_stuck_records(conn: sqlite3.Connection) -> tuple[int, int]:
    """Mark simulation_runs and jobs stuck in 'running' for >30 min as failed.

    Safe to call on every startup — idempotent (only matches running rows with
    no finished_at that are older than 30 minutes).

    Returns:
        (simulation_runs_fixed, jobs_fixed)
    """
    # FIX 3: wrap column values with datetime() to safely compare ISO strings
    # that may include timezone offsets (e.g. "2026-06-18T10:00:00+00:00").
    cur_sim = conn.execute(
        """
        UPDATE simulation_runs
        SET status        = 'failed',
            finished_at   = datetime('now'),
            error_message = 'Stuck in running state — fixed on startup'
        WHERE status = 'running'
          AND finished_at IS NULL
          AND datetime(started_at) < datetime('now', '-30 minutes')
        """
    )
    cur_job = conn.execute(
        """
        UPDATE jobs
        SET status        = 'failed',
            finished_at   = datetime('now'),
            error_message = 'Stuck in running state — fixed on startup'
        WHERE status IN ('running', 'started')
          AND finished_at IS NULL
          AND datetime(started_at) < datetime('now', '-30 minutes')
        """
    )
    conn.commit()
    return cur_sim.rowcount, cur_job.rowcount


def run_migrations(conn: sqlite3.Connection | None = None) -> None:
    """Apply all migrations in order.

    Pass *conn* to run against an in-memory connection (useful in tests).
    """
    if conn is not None:
        for fn in _MIGRATIONS:
            logger.debug("Applying %s", fn.__name__)
            fn(conn)
        conn.commit()
        return

    from app.db.connection import db_transaction

    logger.info("Running DB migrations…")
    with db_transaction() as txn:
        for fn in _MIGRATIONS:
            logger.debug("Applying %s", fn.__name__)
            fn(txn)
    logger.info("DB migrations complete (%d applied)", len(_MIGRATIONS))
