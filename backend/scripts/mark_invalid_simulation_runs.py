"""Mark simulation_runs that violate the probability invariants as 'invalid'.

Never deletes anything — only changes status ('completed' -> 'invalid') and
sets error_message, so the run stays in the DB for audit but is excluded
from every "latest completed" query (get_latest_by_model, get_latest_valid_run,
consensus aggregation, etc. all filter on status = 'completed').

Usage:
    python3 scripts/mark_invalid_simulation_runs.py --dry-run
    python3 scripts/mark_invalid_simulation_runs.py --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

sys.path.insert(0, ".")

from app.services.simulation.validation import validate_simulation_run  # noqa: E402

ERROR_MESSAGE = "Invalid simulation probabilities detected after validation audit"


def find_invalid_runs(conn: sqlite3.Connection) -> list[dict]:
    """Return [{run_id, model_name, created_at, violations}] for every
    completed run that fails validate_simulation_run. Read-only."""
    runs = conn.execute(
        "SELECT id, model_name, created_at FROM simulation_runs WHERE status = 'completed'"
    ).fetchall()

    invalid: list[dict] = []
    for run in runs:
        result = validate_simulation_run(conn, run["id"])
        if not result["valid"]:
            invalid.append({
                "run_id": run["id"],
                "model_name": run["model_name"],
                "created_at": run["created_at"],
                "violations": len(result["violations"]),
            })
    return invalid


def mark_invalid(conn: sqlite3.Connection, run_ids: list[str]) -> int:
    """Set status='invalid' + error_message for the given run ids. Returns count."""
    for run_id in run_ids:
        conn.execute(
            "UPDATE simulation_runs SET status = 'invalid', error_message = ? WHERE id = ?",
            (ERROR_MESSAGE, run_id),
        )
    conn.commit()
    return len(run_ids)


def main() -> None:
    from app.db.connection import db_transaction

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Report only, no changes")
    group.add_argument("--apply", action="store_true", help="Mark invalid runs as status='invalid'")
    args = parser.parse_args()

    with db_transaction() as conn:
        to_mark = find_invalid_runs(conn)

        if not to_mark:
            print("No se encontraron runs inválidos — nada que hacer.")
            return

        print(f"Runs inválidos encontrados: {len(to_mark)}")
        for r in to_mark:
            print(f"  run_id={r['run_id']}  model={r['model_name']}  created_at={r['created_at']}  "
                  f"({r['violations']} equipos con violaciones)")

        if args.dry_run:
            print()
            print("--dry-run: no se modificó nada. Ejecuta con --apply para marcar como 'invalid'.")
            return

        n = mark_invalid(conn, [r["run_id"] for r in to_mark])
        print()
        print(f"--apply: {n} run(s) marcados como status='invalid'.")


if __name__ == "__main__":
    main()
