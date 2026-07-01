"""Determine which WC2026 teams are still alive in the tournament.

Used to filter noticias/key-players panels so eliminated teams don't keep
showing up once the tournament has moved past the group stage.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

_ALIVE_STATUSES = ("active", "qualified", "alive")


def get_alive_team_ids(conn: sqlite3.Connection) -> tuple[set[str], str | None]:
    """Return (alive_team_ids, warning).

    Priority order:
      1. Live bracket state (load_r32_qualifiers) — if R32 is resolved, the
         32 qualifiers are alive minus any already eliminated in a real
         knockout result (load_knockout_winners). More precise than
         wc2026_standings once the tournament reaches R32: standings only
         tracks group-stage status and never advances past 'active'/
         'eliminated' for teams that already exited in the knockout stage.
      2. wc2026_standings.status — alive if status in ('active','qualified',
         'alive'), i.e. anything except 'eliminated'. Used pre-R32.
      3. Fallback: teams.is_wc2026 = 1 (all 48 qualifiers), with a warning
         since this doesn't exclude eliminated teams — only used when no
         tournament-state data exists at all (e.g. pre-tournament).
    """
    try:
        from app.services.simulation.bracket_simulator import (
            load_knockout_winners,
            load_r32_qualifiers,
        )

        r32 = load_r32_qualifiers(conn)
        if r32:
            qualifiers = set(r32.values())
            winners_by_pair = load_knockout_winners(conn, qualifiers)
            eliminated: set[str] = set()
            for pair, winner in winners_by_pair.items():
                h, a = tuple(pair)
                eliminated.add(a if winner == h else h)
            return qualifiers - eliminated, None
    except Exception as exc:
        logger.debug("get_alive_team_ids: bracket-based lookup failed: %s", exc)

    rows = conn.execute("SELECT team_id, status FROM wc2026_standings").fetchall()
    if rows:
        alive = {r["team_id"] for r in rows if r["status"] in _ALIVE_STATUSES}
        return alive, None

    rows = conn.execute("SELECT id FROM teams WHERE is_wc2026 = 1").fetchall()
    warning = (
        "No hay datos de wc2026_standings ni bracket en vivo — no se puede "
        "distinguir equipos eliminados; se muestran los 48 clasificados originales."
    )
    logger.warning("get_alive_team_ids: %s", warning)
    return {r["id"] for r in rows}, warning
