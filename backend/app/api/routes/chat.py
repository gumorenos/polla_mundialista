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

_MAX_TOKENS = 300
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
- Puedes hacer comparaciones y análisis cualitativos\
"""


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
    top5_ml  = _get_top5(conn, "ml_calibrated")
    top5_poi = _get_top5(conn, "poisson")
    injuries = _get_injuries(conn)
    date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    best_top5  = top5_ml or top5_poi
    best_label = "ML Calibrado" if top5_ml else "Poisson"

    parts: list[str] = [f"CONTEXTO DEL MUNDIAL 2026 — {date_str}"]

    if best_top5:
        parts.append(f"\nTOP 5 FAVORITOS AL CAMPEONATO ({best_label}):")
        for i, r in enumerate(best_top5, 1):
            parts.append(
                f"  {i}. {r['team_name']}: campeón {float(r['win_tournament']):.1%}, "
                f"final {float(r['reach_final']):.1%}, semis {float(r['reach_semi_final']):.1%}"
            )
    else:
        parts.append("\nSin datos de simulación disponibles.")

    if top5_poi and top5_ml:
        parts.append("\nCOMPARACIÓN — Top 3 modelo Poisson:")
        for r in top5_poi[:3]:
            parts.append(f"  {r['team_name']}: campeón {float(r['win_tournament']):.1%}")

    if injuries:
        parts.append("\nLESIONES ACTIVAS (afectan predicción):")
        for inj in injuries[:10]:
            parts.append(f"  - {inj['player_name']} ({inj['team_name']}): {inj['status']}")
    else:
        parts.append("\nLESIONES: No hay lesiones confirmadas actualmente.")

    return "\n".join(parts)


def _get_top5(conn: sqlite3.Connection, model_name: str) -> list[dict[str, Any]]:
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
        LIMIT 5
        """,
        (model_name, model_name),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_injuries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
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
