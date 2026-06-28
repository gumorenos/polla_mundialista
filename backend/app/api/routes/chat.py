"""Chat assistant — answers questions about the tournament using LLM + live context."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.limiter import limiter
from app.db.connection import db_transaction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

_MAX_TOKENS = 450
_FALLBACK_ANSWER = (
    "Lo siento, el servicio de análisis no está disponible en este momento. "
    "Puedes ver los datos directamente en las páginas de Simulaciones y Modelos."
)
_SYSTEM_PROMPT = """\
Eres el asistente del Oráculo Mundial 2026, una aplicación de predicción \
estadística del Mundial de Fútbol 2026. Respondes preguntas sobre el torneo \
basándote ÚNICAMENTE en los datos proporcionados.

Reglas:
- Responde en el mismo idioma que la pregunta (español o inglés)
- Sé conciso (máximo 150 palabras)
- Si no tienes datos para responder, dilo claramente
- No inventes datos ni probabilidades que no estén en el contexto
- Menciona el modelo cuando hables de probabilidades
- Puedes hacer comparaciones y análisis cualitativos
- Cuando el usuario pregunte por un equipo específico, menciona su ELO, \
strengths de ataque/defensa, grupo y probabilidades en cada modelo disponible.
- Cuando compares modelos, explica brevemente qué considera cada uno \
(ELO = ratings históricos; Poisson = fuerzas gol con decaimiento temporal; \
ML = LightGBM entrenado con 11 features; Poisson+ctx = Poisson ajustado \
por lesiones confirmadas).\
"""

_ALL_MODELS = ["ml_calibrated", "consensus", "poisson_context", "poisson", "elo", "baseline"]
_MODEL_LABELS: dict[str, str] = {
    "ml_calibrated":   "ML Calibrado",
    "consensus":       "Consenso",
    "poisson_context": "Poisson+Ctx",
    "poisson":         "Poisson",
    "elo":             "ELO",
    "baseline":        "Baseline",
}


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class ChatResponse(BaseModel):
    answer: str
    context_date: str | None = None
    model_used: str | None = None
    error: bool = False


@router.post("", response_model=ChatResponse)
@limiter.limit("10/minute")
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Answer a free-form question about the tournament using live simulation data."""
    with db_transaction() as conn:
        context = _build_context(conn)

    answer, model_used = _call_llm(context, body.question)

    if answer is None:
        return ChatResponse(answer=_FALLBACK_ANSWER, error=True)

    return ChatResponse(
        answer=answer,
        context_date=datetime.now(timezone.utc).isoformat(),
        model_used=model_used,
    )


# ---------------------------------------------------------------------------
# Context builder — all read-only queries, no SQL write patterns
# ---------------------------------------------------------------------------

def _build_context(conn: sqlite3.Connection) -> str:
    date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    parts: list[str] = [f"CONTEXTO DEL MUNDIAL 2026 — {date_str}"]

    # ------------------------------------------------------------------
    # Block 2 — Top 10 de todos los modelos disponibles
    # ------------------------------------------------------------------
    model_results: dict[str, list[dict[str, Any]]] = {}
    for model in _ALL_MODELS:
        rows = _get_top_n(conn, model, n=10)
        if rows:
            model_results[model] = rows

    if model_results:
        for model_name, rows in model_results.items():
            label = _MODEL_LABELS.get(model_name, model_name)
            parts.append(f"\nTOP 10 — {label}:")
            for i, r in enumerate(rows, 1):
                parts.append(
                    f"  {i}. {r['team_name']}: "
                    f"campeón {float(r['win_tournament']):.1%}, "
                    f"final {float(r['reach_final']):.1%}, "
                    f"semis {float(r['reach_semi_final']):.1%}"
                )
    else:
        parts.append("\nSin datos de simulación disponibles.")

    # ------------------------------------------------------------------
    # Block 3 — Comparativa entre modelos para top 5 del mejor modelo
    # ------------------------------------------------------------------
    best_model = next(iter(model_results), None)
    if best_model and len(model_results) > 1:
        top5 = model_results[best_model][:5]
        parts.append("\nCOMPARATIVA ENTRE MODELOS (top 5 equipos):")
        for team in top5:
            tid = team["team_id"]
            probs: list[str] = []
            for m, rows in model_results.items():
                match = next((r for r in rows if r["team_id"] == tid), None)
                if match:
                    probs.append(
                        f"{_MODEL_LABELS.get(m, m)}: {float(match['win_tournament']):.1%}"
                    )
            if probs:
                parts.append(f"  {team['team_name']}: {' | '.join(probs)}")

    # ------------------------------------------------------------------
    # Block 4 — ELO y strengths de todos los equipos WC2026
    # ------------------------------------------------------------------
    team_data = _get_all_team_data(conn)
    if team_data:
        parts.append("\nELO Y STRENGTHS POR EQUIPO (orden ELO desc):")
        for td in team_data:
            elo  = f"{float(td['elo']):.0f}" if td.get("elo") is not None else "—"
            atk  = f"{float(td['attack_strength']):.2f}" if td.get("attack_strength") is not None else "—"
            defv = f"{float(td['defense_vulnerability']):.2f}" if td.get("defense_vulnerability") is not None else "—"
            grp  = td.get("group_id") or "—"
            parts.append(
                f"  {td['name']}: ELO={elo}, atk={atk}, def={defv}, grupo={grp}"
            )

    # ------------------------------------------------------------------
    # Block 5 — Composición de grupos
    # ------------------------------------------------------------------
    groups = _get_groups(conn)
    if groups:
        parts.append("\nCOMPOSICIÓN DE GRUPOS:")
        for gid, team_names in sorted(groups.items()):
            parts.append(f"  Grupo {gid}: {', '.join(team_names)}")

    # ------------------------------------------------------------------
    # Block 6 — Lesiones activas (existing logic, kept as-is)
    # ------------------------------------------------------------------
    injuries = _get_injuries(conn)
    if injuries:
        parts.append("\nLESIONES ACTIVAS (afectan predicción):")
        for inj in injuries[:10]:
            parts.append(f"  - {inj['player_name']} ({inj['team_name']}): {inj['status']}")
    else:
        parts.append("\nLESIONES: No hay lesiones confirmadas actualmente.")

    # ------------------------------------------------------------------
    # Block 7 — Jugadores clave (top xG por equipo, filtrado por convocados)
    # ------------------------------------------------------------------
    key_players = _get_key_players(conn)
    if key_players:
        parts.append("\nJUGADORES CLAVE (mayor xG/partido, máx 20 equipos):")
        for kp in key_players:
            parts.append(
                f"  {kp['team_name']}: {kp['player_name']} "
                f"(xG/partido: {float(kp['avg_xg']):.2f})"
            )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Query helpers — all return [] or {} on any DB error (safe for empty DBs)
# ---------------------------------------------------------------------------

def _get_top_n(
    conn: sqlite3.Connection, model_name: str, n: int = 10
) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT str.team_id, t.name AS team_name,
                   str.win_tournament, str.reach_final, str.reach_semi_final
            FROM simulation_team_results str
            JOIN simulation_runs sr ON str.simulation_run_id = sr.id
            JOIN teams t ON str.team_id = t.id
            WHERE sr.model_name = ? AND sr.status = 'completed'
              AND sr.finished_at = (
                  SELECT MAX(sr2.finished_at) FROM simulation_runs sr2
                  WHERE sr2.model_name = ? AND sr2.status = 'completed'
              )
            ORDER BY str.win_tournament DESC
            LIMIT ?
            """,
            (model_name, model_name, n),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("_get_top_n(%s): %s", model_name, exc)
        return []


def _get_all_team_data(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return ELO, attack/defense strengths and group for every WC2026 team."""
    try:
        rows = conn.execute(
            """
            SELECT t.id, t.name,
                   r.value  AS elo,
                   ts.attack_strength,
                   ts.defense_vulnerability,
                   gt.group_id
            FROM teams t
            LEFT JOIN ratings r ON r.team_id = t.id
                AND r.rating_type = 'elo'
                AND r.source != 'own_elo'
                AND r.effective_date = (
                    SELECT MAX(r2.effective_date)
                    FROM ratings r2
                    WHERE r2.team_id = t.id
                      AND r2.rating_type = 'elo'
                      AND r2.source != 'own_elo'
                )
            LEFT JOIN team_strengths ts ON ts.team_id = t.id
            LEFT JOIN group_teams gt ON gt.team_id = t.id
            ORDER BY r.value DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("_get_all_team_data: %s", exc)
        return []


def _get_groups(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return {group_id: [team_name, ...]} for all groups."""
    try:
        rows = conn.execute(
            """
            SELECT gt.group_id, t.name AS team_name
            FROM group_teams gt
            JOIN teams t ON gt.team_id = t.id
            ORDER BY gt.group_id, gt.position
            """
        ).fetchall()
        groups: dict[str, list[str]] = {}
        for r in rows:
            gid = r["group_id"]
            if gid not in groups:
                groups[gid] = []
            groups[gid].append(r["team_name"])
        return groups
    except Exception as exc:
        logger.debug("_get_groups: %s", exc)
        return {}


def _get_key_players(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return top-xG player per team, filtered by wc2026_squads when available."""
    try:
        has_squads = bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wc2026_squads'"
            ).fetchone()
        )

        if has_squads:
            rows = conn.execute(
                """
                SELECT sps.team_id, t.name AS team_name,
                       sps.player_name, AVG(sps.xg) AS avg_xg
                FROM sb_player_stats sps
                JOIN teams t ON sps.team_id = t.id
                WHERE (
                    EXISTS (
                        SELECT 1 FROM wc2026_squads ws
                        WHERE ws.team_id = sps.team_id
                          AND ws.player_name = sps.player_name
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM wc2026_squads WHERE team_id = sps.team_id
                    )
                )
                GROUP BY sps.team_id, sps.player_name
                HAVING AVG(sps.xg) > 0
                ORDER BY sps.team_id, AVG(sps.xg) DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT sps.team_id, t.name AS team_name,
                       sps.player_name, AVG(sps.xg) AS avg_xg
                FROM sb_player_stats sps
                JOIN teams t ON sps.team_id = t.id
                GROUP BY sps.team_id, sps.player_name
                HAVING AVG(sps.xg) > 0
                ORDER BY sps.team_id, AVG(sps.xg) DESC
                """
            ).fetchall()

        # Keep only the highest-xG player per team
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for r in rows:
            tid = r["team_id"]
            if tid not in seen:
                seen.add(tid)
                result.append(dict(r))
            if len(result) >= 20:
                break
        return result
    except Exception as exc:
        logger.debug("_get_key_players: %s", exc)
        return []


def _get_injuries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT ac.player_name, t.name AS team_name, ac.status
            FROM availability_claims ac
            JOIN teams t ON ac.team_id = t.id
            WHERE ac.affects_prediction = 1
              AND ac.status IN ('injured', 'doubtful')
              AND ac.created_at >= datetime('now', '-7 days')
            ORDER BY t.name, ac.player_name
            LIMIT 20
            """,
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("_get_injuries: %s", exc)
        return []


# ---------------------------------------------------------------------------
# LLM caller — mirrors generator.py pattern, returns (text, model) or (None, None)
# ---------------------------------------------------------------------------

def _call_llm(context: str, question: str) -> tuple[str | None, str | None]:
    if not settings.OPENROUTER_API_KEY:
        logger.warning("chat: OPENROUTER_API_KEY not set — skipping")
        return None, None

    user_message = f"{context}\n\nPREGUNTA DEL USUARIO: {question}"
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
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                "temperature": 0.4,
                "max_tokens":  _MAX_TOKENS,
            }
            with httpx.Client(timeout=45) as client:
                resp = client.post(settings.OPENROUTER_BASE_URL, headers=headers, json=payload)
                resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            if text and text.strip():
                return text.strip(), model
        except Exception as exc:
            logger.warning("chat: LLM call failed model=%s: %s", model, exc)

    return None, None
