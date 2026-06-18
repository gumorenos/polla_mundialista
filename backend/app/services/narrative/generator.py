"""LLM narrative generator for team and tournament explanations.

Uses the same OpenRouter client as the injury classifier (synchronous httpx).
Never raises — returns None on any failure so the caller can omit the field.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_MAX_TOKENS_TEAM       = 220
_MAX_TOKENS_TOURNAMENT = 380


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_team_narrative(
    conn: sqlite3.Connection,
    run_id: str,
    team_id: str,
) -> str | None:
    """Return a 2-3 paragraph narrative for a team's WC2026 outlook.

    Loads all context from DB; returns None on LLM failure.
    """
    ctx = _load_team_context(conn, run_id, team_id)
    if not ctx:
        return None

    prompt = _team_prompt(ctx)
    return _call_llm(prompt, max_tokens=_MAX_TOKENS_TEAM)


def generate_tournament_narrative(
    conn: sqlite3.Connection,
    run_id: str,
) -> str | None:
    """Return a ~300-word overview of the tournament favourites.

    Aggregates top-10 teams across all completed models.
    """
    ctx = _load_tournament_context(conn, run_id)
    if not ctx:
        return None

    prompt = _tournament_prompt(ctx)
    return _call_llm(prompt, max_tokens=_MAX_TOKENS_TOURNAMENT)


# ---------------------------------------------------------------------------
# Context loaders (all DB access here — no raw SQL in routes)
# ---------------------------------------------------------------------------

def _load_team_context(conn: sqlite3.Connection, run_id: str, team_id: str) -> dict[str, Any] | None:
    from app.db.repositories.narrative import NarrativeRepository  # noqa: F401 (used by caller)

    # Simulation results for this team in this run
    sim_row = conn.execute(
        """
        SELECT str.win_tournament, str.reach_final, str.reach_semi_final,
               str.reach_quarter_final, str.qualify, str.reach_round_of_16,
               t.name AS team_name, sr.model_name
        FROM simulation_team_results str
        JOIN simulation_runs sr ON str.simulation_run_id = sr.id
        JOIN teams t ON str.team_id = t.id
        WHERE str.simulation_run_id = ? AND str.team_id = ?
        """,
        (run_id, team_id),
    ).fetchone()
    if not sim_row:
        return None

    # ELO rating
    elo_row = conn.execute(
        """
        SELECT r.value AS elo, (
            SELECT COUNT(*) FROM ratings r2
            WHERE r2.rating_type = 'elo'
              AND r2.value > r.value
              AND r2.effective_date = (
                  SELECT MAX(r3.effective_date) FROM ratings r3
                  WHERE r3.team_id = r2.team_id AND r3.rating_type = 'elo'
              )
        ) + 1 AS elo_rank
        FROM ratings r
        WHERE r.team_id = ? AND r.rating_type = 'elo'
        ORDER BY r.effective_date DESC
        LIMIT 1
        """,
        (team_id,),
    ).fetchone()

    # Team strengths
    str_row = conn.execute(
        """
        SELECT attack_strength, defense_vulnerability
        FROM team_strengths
        WHERE team_id = ?
        ORDER BY computed_at DESC
        LIMIT 1
        """,
        (team_id,),
    ).fetchone()

    # Group and rivals
    group_row = conn.execute(
        """
        SELECT g.id AS group_id
        FROM groups g
        JOIN group_teams gt ON g.id = gt.group_id
        WHERE gt.team_id = ?
        LIMIT 1
        """,
        (team_id,),
    ).fetchone()

    rivals: list[str] = []
    if group_row:
        rival_rows = conn.execute(
            """
            SELECT t.name FROM group_teams gt
            JOIN teams t ON gt.team_id = t.id
            WHERE gt.group_id = ? AND gt.team_id != ?
            """,
            (group_row["group_id"], team_id),
        ).fetchall()
        rivals = [r["name"] for r in rival_rows]

    # Active injuries
    injury_rows = conn.execute(
        """
        SELECT player_name FROM availability_claims
        WHERE team_id = ? AND status IN ('injured', 'doubtful')
          AND affects_prediction = 1
        ORDER BY observed_at DESC
        LIMIT 5
        """,
        (team_id,),
    ).fetchall()
    injuries = [r["player_name"] for r in injury_rows]

    return {
        "team_id":        team_id,
        "team_name":      sim_row["team_name"],
        "model_name":     sim_row["model_name"],
        "champion":       float(sim_row["win_tournament"]),
        "top4":           float(sim_row["reach_semi_final"]),
        "qualify":        float(sim_row["qualify"]),
        "reach_final":    float(sim_row["reach_final"]),
        "elo":            float(elo_row["elo"]) if elo_row else None,
        "elo_rank":       int(elo_row["elo_rank"]) if elo_row else None,
        "attack":         float(str_row["attack_strength"]) if str_row else None,
        "defense":        float(str_row["defense_vulnerability"]) if str_row else None,
        "group_id":       group_row["group_id"] if group_row else None,
        "rivals":         rivals,
        "injuries":       injuries,
    }


def _load_tournament_context(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    # Top 10 teams from the requested run
    rows = conn.execute(
        """
        SELECT str.team_id, t.name AS team_name,
               str.win_tournament, str.reach_final, str.reach_semi_final,
               sr.model_name
        FROM simulation_team_results str
        JOIN simulation_runs sr ON str.simulation_run_id = sr.id
        JOIN teams t ON str.team_id = t.id
        WHERE str.simulation_run_id = ?
        ORDER BY str.win_tournament DESC
        LIMIT 10
        """,
        (run_id,),
    ).fetchall()
    if not rows:
        return None

    run_row = conn.execute(
        "SELECT model_name, iterations FROM simulation_runs WHERE id = ?", (run_id,)
    ).fetchone()

    return {
        "run_id":     run_id,
        "model_name": run_row["model_name"] if run_row else "poisson",
        "iterations": int(run_row["iterations"]) if run_row else 30_000,
        "top_teams":  [dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _team_prompt(ctx: dict[str, Any]) -> str:
    elo_text = (
        f"{ctx['elo']:.0f} (puesto {ctx['elo_rank']}/48)"
        if ctx["elo"] else "no disponible"
    )
    atk_text = f"{ctx['attack']:.2f}" if ctx["attack"] else "no disponible"
    def_text = f"{ctx['defense']:.2f}" if ctx["defense"] else "no disponible"
    rivals_text = ", ".join(ctx["rivals"]) if ctx["rivals"] else "no disponible"
    injury_text = ", ".join(ctx["injuries"]) if ctx["injuries"] else "ninguna conocida"
    group_text  = ctx["group_id"] or "no asignado"

    return f"""\
Eres un analista experto de fútbol. Explica en 2-3 párrafos cortos \
(máximo 150 palabras en total) por qué {ctx['team_name']} tiene estas \
probabilidades en el Mundial 2026.

Modelo: {ctx['model_name']}
Probabilidades:
- Campeón: {ctx['champion']:.1%}
- Final: {ctx['reach_final']:.1%}
- Top 4 (semis): {ctx['top4']:.1%}
- Pasar grupos: {ctx['qualify']:.1%}

Datos:
- ELO: {elo_text}
- Fuerza de ataque (1.0 = media): {atk_text}
- Vulnerabilidad defensiva (1.0 = media): {def_text}
- Grupo: {group_text} | Rivales: {rivals_text}
- Lesiones activas: {injury_text}

Sé conciso y directo. No repitas los números exactos ya mostrados. \
Enfócate en los factores cualitativos clave. Responde en español."""


def _tournament_prompt(ctx: dict[str, Any]) -> str:
    lines = []
    for i, t in enumerate(ctx["top_teams"], 1):
        lines.append(
            f"{i}. {t['team_name']}: campeón {float(t['win_tournament']):.1%}, "
            f"final {float(t['reach_final']):.1%}, semis {float(t['reach_semi_final']):.1%}"
        )
    teams_block = "\n".join(lines)

    return f"""\
Eres un analista experto de fútbol para el Mundial FIFA 2026. \
Basándote en los siguientes pronósticos estadísticos del modelo {ctx['model_name']} \
({ctx['iterations']:,} iteraciones Monte Carlo), escribe un análisis narrativo \
de 3-4 párrafos (máximo 300 palabras) sobre los favoritos al título y la \
dinámica del torneo. Identifica a los 5 principales candidatos y explica \
sus fortalezas y debilidades relativas.

Top 10 equipos por probabilidad de campeonato:
{teams_block}

Sé concreto, accesible y evita repetir números ya listados. \
Responde en español."""


# ---------------------------------------------------------------------------
# LLM caller (sync, mirrors llm_classifier pattern)
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, max_tokens: int) -> str | None:
    if not settings.OPENROUTER_API_KEY:
        logger.warning("narrative: OPENROUTER_API_KEY not set — skipping")
        return None

    models = [settings.OPENROUTER_MODEL] + list(settings.OPENROUTER_FALLBACK_MODELS)

    for model in models:
        try:
            headers = {
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  settings.OPENROUTER_SITE_URL or "http://localhost",
                "X-Title":       settings.OPENROUTER_APP_NAME,
            }
            payload = {
                "model":    model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens":  max_tokens,
            }
            with httpx.Client(timeout=45) as client:
                resp = client.post(
                    settings.OPENROUTER_BASE_URL, headers=headers, json=payload
                )
                resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            if text and text.strip():
                return text.strip()
        except Exception as exc:
            logger.warning("narrative: LLM call failed model=%s: %s", model, exc)

    return None
