"""Correct `results.is_wc` for rows mistagged by the substring-matching bug
in the CSV ingestion loader (see audit_wc_result_tagging.py for the full
explanation).

Only ever UPDATEs `is_wc` to 0 on the affected rows — never deletes rows,
never touches fixtures/simulation_runs/bracket_runs/bracket_simulation_results.

Usage:
    python3 backend/scripts/fix_wc_result_tagging.py --dry-run
    python3 backend/scripts/fix_wc_result_tagging.py --apply
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.db.connection import db_transaction  # noqa: E402
from scripts.audit_wc_result_tagging import find_mistagged  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Report what would change, no writes.")
    group.add_argument("--apply", action="store_true", help="Actually UPDATE is_wc=0 for mistagged rows.")
    args = parser.parse_args()

    with db_transaction() as conn:
        mistagged = find_mistagged(conn)
        print(f"Rows to correct (is_wc 1 -> 0): {len(mistagged)}")
        for row in mistagged:
            print(f"  id={row['id']} {row['home_team_id']} vs {row['away_team_id']} "
                  f"date={row['match_date']} tournament={row['tournament']!r}")

        if args.apply and mistagged:
            ids = [row["id"] for row in mistagged]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"UPDATE results SET is_wc = 0 WHERE id IN ({placeholders})", ids)
            conn.commit()
            print(f"Applied: {len(ids)} rows updated.")
        elif args.dry_run:
            print("Dry run — no changes made. Re-run with --apply to fix.")


if __name__ == "__main__":
    main()
