"""Central helper for resolving a team's "key player pool" — the set of
player names that should be used for xG-based form adjustments.

Prefers the real WC2026 squad list (wc2026_squads) when available, so a
player who topped historical xG but didn't make the final squad is never
used. Falls back to the full StatsBomb player pool when no squad data
exists for the team yet (pre-squad-announcement), with an explicit warning
so callers/consumers know the result may include non-convocados.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from typing import TypedDict


class KeyPlayerPool(TypedDict):
    players: list[str]
    squad_status: str  # "confirmed" | "missing" | "partial"
    source: str
    warning: str | None


def _normalize_name(name: str) -> str:
    """lower + strip accents + trim + collapse internal whitespace."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(ascii_only.lower().split())


def get_key_player_pool(team_id: str, conn: sqlite3.Connection) -> KeyPlayerPool:
    """Return the player-name pool to use for *team_id*'s xG-based adjustments.

    squad_status:
      "confirmed" — wc2026_squads has data for this team; only those
                    players are used (StatsBomb names matched by normalized
                    name where an exact match isn't available).
      "missing"   — no wc2026_squads data for this team at all; falls back
                    to the full StatsBomb player pool (may include players
                    no longer in the squad).
      "partial"   — wc2026_squads has data, but none of the squad's player
                    names could be matched against StatsBomb records.
    """
    squad_rows = conn.execute(
        "SELECT player_name FROM wc2026_squads WHERE team_id = ?", (team_id,)
    ).fetchall()

    if not squad_rows:
        sb_rows = conn.execute(
            "SELECT DISTINCT player_name FROM sb_player_stats WHERE team_id = ?", (team_id,)
        ).fetchall()
        return {
            "players": [r["player_name"] for r in sb_rows],
            "squad_status": "missing",
            "source": "statsbomb_fallback",
            "warning": (
                f"No hay convocatoria WC2026 registrada para '{team_id}' — "
                "usando el pool completo de jugadores StatsBomb (puede incluir "
                "jugadores que ya no están en la convocatoria)."
            ),
        }

    squad_names = {r["player_name"] for r in squad_rows}
    squad_normalized = {_normalize_name(n): n for n in squad_names}

    sb_rows = conn.execute(
        "SELECT DISTINCT player_name FROM sb_player_stats WHERE team_id = ?", (team_id,)
    ).fetchall()
    sb_names = [r["player_name"] for r in sb_rows]

    matched: list[str] = []
    for sb_name in sb_names:
        if sb_name in squad_names:
            matched.append(sb_name)
        elif _normalize_name(sb_name) in squad_normalized:
            matched.append(sb_name)

    if not matched:
        return {
            "players": [],
            "squad_status": "partial",
            "source": "wc2026_squads",
            "warning": (
                f"'{team_id}' tiene convocatoria WC2026 registrada, pero ningún "
                "nombre coincide con los registros StatsBomb (ni tras normalizar "
                "tildes/mayúsculas/espacios) — no hay datos de forma disponibles."
            ),
        }

    return {
        "players": matched,
        "squad_status": "confirmed",
        "source": "wc2026_squads",
        "warning": None,
    }
