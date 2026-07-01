"""Audit all completed simulation_runs for probability-invariant violations.

Read-only — never modifies the database. See mark_invalid_simulation_runs.py
to actually flag corrupt runs.

Usage:
    python3 scripts/audit_simulation_runs.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.connection import db_transaction  # noqa: E402
from app.services.simulation.validation import validate_simulation_run  # noqa: E402


def main() -> None:
    with db_transaction() as conn:
        runs = conn.execute(
            """
            SELECT id, model_name, status, created_at
            FROM simulation_runs
            WHERE status = 'completed'
            ORDER BY datetime(created_at) DESC
            """
        ).fetchall()

        total = len(runs)
        invalid: list[dict] = []
        by_model: dict[str, dict[str, int]] = {}

        for run in runs:
            model = run["model_name"]
            by_model.setdefault(model, {"valid": 0, "invalid": 0})
            result = validate_simulation_run(conn, run["id"])
            if result["valid"]:
                by_model[model]["valid"] += 1
            else:
                by_model[model]["invalid"] += 1
                invalid.append({
                    "run_id": run["id"],
                    "model_name": model,
                    "created_at": run["created_at"],
                    "violations": len(result["violations"]),
                    "checked": result["checked"],
                    "sample": result["violations"][:3],
                })

    print(f"Total runs completed: {total}")
    print(f"Valid:   {total - len(invalid)}")
    print(f"Invalid: {len(invalid)}")
    print()
    print("Por modelo:")
    for model, counts in sorted(by_model.items()):
        print(f"  {model:16s} valid={counts['valid']:3d}  invalid={counts['invalid']:3d}")

    if invalid:
        print()
        print(f"Últimos {min(10, len(invalid))} runs inválidos:")
        for r in invalid[:10]:
            print(f"  run_id={r['run_id']}  model={r['model_name']}  created_at={r['created_at']}")
            print(f"    {r['violations']}/{r['checked']} equipos con violaciones")
            for v in r["sample"]:
                print(f"      - {v['team_name']} ({v['team_id']}): {v['errors'][0]}")

    if invalid:
        sys.exit(1)


if __name__ == "__main__":
    main()
