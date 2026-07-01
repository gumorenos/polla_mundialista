"""Validate simulation_team_results against the invariant chain.

0 <= win_tournament <= reach_final <= reach_semi_final <= reach_quarter_final
    <= reach_round_of_16 <= reach_round_of_32 <= 1
reach_round_of_32 == qualify (within tolerance)
0 <= win_group <= 1
0 <= qualify <= 1

Used to keep publicly-served simulation data honest — a run produced by a
buggy Monte Carlo build (e.g. the reach_round_of_32 double-count bug fixed
in commit f697bde) must never be silently served as "latest" again, even
though the *code* has been fixed — the stale *data* survives in the DB
until it's re-simulated or explicitly marked invalid.
"""

from __future__ import annotations

import sqlite3
from typing import Any

_TOLERANCE = 1e-4

_CHAIN = [
    "win_tournament", "reach_final", "reach_semi_final",
    "reach_quarter_final", "reach_round_of_16", "reach_round_of_32",
]


def validate_team_result(row: dict[str, Any]) -> list[str]:
    """Return a list of human-readable violation messages (empty = valid)."""
    errors: list[str] = []

    for col in (*_CHAIN, "win_group", "qualify"):
        v = row.get(col)
        if v is None:
            continue
        if v < -_TOLERANCE or v > 1 + _TOLERANCE:
            errors.append(f"{col}={v:.4f} fuera de rango [0,1]")

    for tighter, looser in zip(_CHAIN, _CHAIN[1:]):
        tv, lv = row.get(tighter), row.get(looser)
        if tv is None or lv is None:
            continue
        if tv > lv + _TOLERANCE:
            errors.append(f"{tighter}={tv:.4f} > {looser}={lv:.4f} (rompe monotonicidad)")

    r32, qualify = row.get("reach_round_of_32"), row.get("qualify")
    if r32 is not None and qualify is not None and abs(r32 - qualify) > _TOLERANCE:
        errors.append(f"reach_round_of_32={r32:.4f} != qualify={qualify:.4f}")

    return errors


def validate_simulation_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """Validate every team_result row for *run_id*.

    Returns:
        {
          "run_id": run_id,
          "valid": bool,
          "checked": int,
          "violations": [{"team_id", "team_name", "errors": [...]}],
        }
    """
    rows = conn.execute(
        """
        SELECT str.team_id, t.name AS team_name, str.win_group, str.qualify,
               str.reach_round_of_32, str.reach_round_of_16, str.reach_quarter_final,
               str.reach_semi_final, str.reach_final, str.win_tournament
        FROM simulation_team_results str
        JOIN teams t ON t.id = str.team_id
        WHERE str.simulation_run_id = ?
        """,
        (run_id,),
    ).fetchall()

    violations: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        errors = validate_team_result(row)
        if errors:
            violations.append({
                "team_id": row["team_id"],
                "team_name": row["team_name"],
                "errors": errors,
            })

    return {
        "run_id": run_id,
        "valid": len(violations) == 0 and len(rows) > 0,
        "checked": len(rows),
        "violations": violations,
    }


def get_latest_valid_run(
    conn: sqlite3.Connection, model_name: str, scan_limit: int = 20
) -> dict[str, Any] | None:
    """Scan the most recent completed runs for *model_name* and return the
    newest one that passes validation, or None if none of the last
    *scan_limit* runs are valid (all invalid, or no runs at all)."""
    from app.db.repositories.simulations import SimulationRepository

    for run in SimulationRepository(conn).get_recent_completed(model_name, limit=scan_limit):
        if is_run_valid(conn, run["id"]):
            return run
    return None


def is_run_valid(conn: sqlite3.Connection, run_id: str) -> bool:
    """Cheap boolean check — stops at the first violation found."""
    row = conn.execute(
        """
        SELECT str.win_group, str.qualify, str.reach_round_of_32, str.reach_round_of_16,
               str.reach_quarter_final, str.reach_semi_final, str.reach_final, str.win_tournament
        FROM simulation_team_results str
        WHERE str.simulation_run_id = ?
        """,
        (run_id,),
    ).fetchall()
    if not row:
        return False
    return all(not validate_team_result(dict(r)) for r in row)
