"""Walk-forward temporal backtesting for all prediction models.

Strategy:
1. Load all historical results from start_year onward.
2. Group matches into `window_months`-month windows (sorted by date).
3. For each window: predict with every requested model; accumulate (pred, actual) pairs.
4. After all windows: compute aggregate metrics and calibration data per model.
5. Persist one model_evaluations row per model; export calibration JSON to disk.

Note: base models (ELO, Poisson, Baseline) are stateless — they use current
ELO / strength data as a proxy for each historical match.  ML calibrated uses
the currently-trained model (if any), or falls back to Poisson with a
"degraded" note.
"""

from __future__ import annotations

import calendar
import json
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.repositories.evaluations import EvaluationRepository
from app.services.evaluation.metrics import (
    accuracy,
    brier_score,
    calibration_data,
    log_loss,
    ranked_probability_score,
)

logger = logging.getLogger(__name__)

_ALL_MODELS = ["baseline", "elo", "poisson", "poisson_context", "ml_calibrated"]
_DEFAULT_START_YEAR = 2018


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_backtesting(
    db_conn: sqlite3.Connection,
    models: list[str] | None = None,
    window_months: int = 3,
    start_year: int | None = None,
    max_matches: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Evaluate all models on historical results and persist metrics.

    Returns {model_name: {brier_score, log_loss, rps, accuracy,
                          calibration_data, n_matches, eval_id}}.
    """
    model_names = models or _ALL_MODELS
    begin_year  = start_year or _DEFAULT_START_YEAR
    start_iso   = f"{begin_year}-01-01"

    limit_clause = f"LIMIT {max_matches}" if max_matches else ""
    rows = db_conn.execute(
        f"""
        SELECT home_team_id, away_team_id, home_goals, away_goals,
               match_date, outcome
        FROM results
        WHERE match_date >= ?
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
        ORDER BY match_date ASC
        {limit_clause}
        """,
        (start_iso,),
    ).fetchall()

    if not rows:
        logger.info("Backtesting: no historical results found from %s", start_iso)
        return {}

    logger.info(
        "Backtesting: %d matches from %s (max_matches=%s), models=%s",
        len(rows), start_iso, max_matches, model_names,
    )

    # Build windows list from earliest match date to latest
    first_date = date.fromisoformat(str(rows[0]["match_date"])[:10])
    last_date  = date.fromisoformat(str(rows[-1]["match_date"])[:10])
    windows    = _build_windows(first_date, last_date, window_months)

    # Instantiate one model object per name (loaded once, shared across windows)
    model_instances = _load_models(model_names, db_conn)

    # Per-model accumulators
    preds_acc:   dict[str, list[dict]] = {m: [] for m in model_names}
    actuals_acc: dict[str, list[str]]  = {m: [] for m in model_names}
    degraded:    dict[str, int]        = {m: 0  for m in model_names}

    # Assign each result row to its window and predict
    row_idx = 0
    n_rows  = len(rows)

    for w_start, w_end in windows:
        while row_idx < n_rows:
            row = rows[row_idx]
            match_date = str(row["match_date"])[:10]
            if match_date > w_end:
                break  # This row belongs to a future window

            home_id  = row["home_team_id"]
            away_id  = row["away_team_id"]
            hg, ag   = row["home_goals"], row["away_goals"]
            actual   = _outcome_label(hg, ag)

            ctx = {"is_neutral": True}  # approximation for historical matches

            for mname in model_names:
                model = model_instances.get(mname)
                if model is None:
                    continue
                try:
                    pred = model.predict_match(home_id, away_id, ctx)
                    if "[fallback" in pred.get("explanation", ""):
                        degraded[mname] += 1
                    preds_acc[mname].append(pred)
                    actuals_acc[mname].append(actual)
                except Exception as exc:
                    logger.debug(
                        "Backtesting: model %s failed on %s vs %s: %s",
                        mname, home_id, away_id, exc,
                    )

            row_idx += 1

    # Compute metrics and persist
    eval_repo  = EvaluationRepository(db_conn)
    results: dict[str, dict[str, Any]] = {}

    exports_dir = Path(settings.DATA_EXPORTS_PATH)
    exports_dir.mkdir(parents=True, exist_ok=True)

    for mname in model_names:
        preds   = preds_acc[mname]
        actuals = actuals_acc[mname]
        n = len(preds)

        if n == 0:
            logger.info("Backtesting: no predictions for model %s", mname)
            continue

        bs  = brier_score(preds, actuals)
        ll  = log_loss(preds, actuals)
        rps = ranked_probability_score(preds, actuals)
        acc = accuracy(preds, actuals)
        cal = calibration_data(preds, actuals, n_bins=10)

        eval_id = eval_repo.insert_evaluation({
            "model_name":  mname,
            "eval_set":    f"historical_{begin_year}_to_{last_date.year}",
            "n_matches":   n,
            "brier_score": bs,
            "log_loss":    ll,
            "rps":         rps,
            "accuracy":    acc,
        })
        db_conn.commit()

        # Export calibration JSON
        cal_path = exports_dir / f"calibration_{mname}.json"
        cal_path.write_text(
            json.dumps(cal, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        results[mname] = {
            "brier_score":      round(bs,  6),
            "log_loss":         round(ll,  6),
            "rps":              round(rps, 6),
            "accuracy":         round(acc, 6),
            "calibration_data": cal,
            "n_matches":        n,
            "eval_id":          eval_id,
            "degraded_windows": degraded[mname],
        }
        logger.info(
            "Backtesting %s: n=%d brier=%.4f logloss=%.4f rps=%.4f acc=%.1f%%",
            mname, n, bs, ll, rps, acc * 100,
        )

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _outcome_label(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home_win"
    if home_goals == away_goals:
        return "draw"
    return "away_win"


def _build_windows(
    first: date,
    last: date,
    window_months: int,
) -> list[tuple[str, str]]:
    """Return list of (start_iso, end_iso) window tuples covering [first, last]."""
    windows: list[tuple[str, str]] = []
    year, month = first.year, first.month
    end_year, end_month = last.year, last.month

    while (year, month) <= (end_year, end_month):
        w_start = f"{year}-{month:02d}-01"

        # Advance by window_months
        total = (year * 12 + month - 1) + window_months - 1
        e_year, e_month = total // 12, total % 12 + 1
        last_day = calendar.monthrange(e_year, e_month)[1]
        w_end = f"{e_year}-{e_month:02d}-{last_day:02d}"

        windows.append((w_start, w_end))

        # Advance to next window start
        total_next = year * 12 + month - 1 + window_months
        year, month = total_next // 12, total_next % 12 + 1

    return windows


def _load_models(
    model_names: list[str],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Instantiate one model object per name; skip on error."""
    from app.services.prediction.baseline import BaselineModel
    from app.services.prediction.elo_model import EloModel
    from app.services.prediction.ml_calibrated import MLCalibratedModel
    from app.services.prediction.poisson_context import PoissonContextModel
    from app.services.prediction.poisson_model import PoissonModel

    cls_map = {
        "baseline":       BaselineModel,
        "elo":            EloModel,
        "poisson":        PoissonModel,
        "poisson_context": PoissonContextModel,
        "ml_calibrated":  MLCalibratedModel,
    }

    instances: dict[str, Any] = {}
    for name in model_names:
        cls = cls_map.get(name)
        if cls is None:
            logger.warning("Backtesting: unknown model '%s' — skipping", name)
            continue
        try:
            instances[name] = cls(conn)
        except Exception as exc:
            logger.warning("Backtesting: could not load model %s: %s", name, exc)
    return instances
