"""Read-only audit: find `results` rows mistagged as is_wc=1.

Root cause (fixed in app.services.ingestion.csv_loader): is_wc was set via a
naive `"WC20" in tournament` substring check, which also matches qualifying
campaigns like "AFC Qualifiers WC2026" or "CONMEBOL Qualifiers WC2026" — not
World Cup finals matches. `is_wc=1` legitimately covers *any* past World Cup
edition used as historical data (WC2018, WC2022, ...), not just WC2026, so
this audit only flags qualifier-labeled rows, not a date cutoff.

Those mistagged rows can poison the live WC2026 bracket simulator
(app.services.simulation.bracket_simulator.load_knockout_winners), which
treats any is_wc=1 result between two real WC2026 finalists as a decided
knockout match — that function now also requires match_date to be on/after
the WC2026 finals start as a second line of defense, but the tagging itself
should still be correct at the source.

This script only SELECTs — it does not modify the database. Use
fix_wc_result_tagging.py --dry-run / --apply to correct what this finds.
"""

from __future__ import annotations

import argparse
import re
import sys

sys.path.insert(0, ".")

from app.db.connection import db_transaction  # noqa: E402

_QUALIF_RE = re.compile(r"qualif|clasificat", re.IGNORECASE)


def find_mistagged(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, home_team_id, away_team_id, home_goals, away_goals, "
        "match_date, tournament, stage, source "
        "FROM results WHERE is_wc = 1 ORDER BY match_date"
    ).fetchall()

    mistagged = []
    for r in rows:
        tourn = r["tournament"] or ""
        if _QUALIF_RE.search(tourn):
            mistagged.append({**dict(r), "reasons": ["tournament name is a qualifying campaign"]})
    return mistagged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    with db_transaction() as conn:
        total_wc = conn.execute("SELECT COUNT(*) c FROM results WHERE is_wc = 1").fetchone()["c"]
        mistagged = find_mistagged(conn)

    print(f"Total results.is_wc=1 rows: {total_wc}")
    print(f"Mistagged (should be is_wc=0): {len(mistagged)}")
    for row in mistagged:
        print(
            f"  id={row['id']} {row['home_team_id']} {row['home_goals']}-{row['away_goals']} "
            f"{row['away_team_id']} date={row['match_date']} tournament={row['tournament']!r} "
            f"source={row['source']} -- {'; '.join(row['reasons'])}"
        )


if __name__ == "__main__":
    main()
