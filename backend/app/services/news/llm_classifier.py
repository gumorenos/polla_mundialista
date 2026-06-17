"""LLM injury classifier via OpenRouter.

Calls the configured model; if it fails, tries fallback models in order.
JSON is validated with Pydantic. Returns UNRELATED on any unrecoverable failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_SYSTEM_PROMPT = (
    "You are an injury analyst for a football prediction system. "
    "Read the article and assess the named player's injury status. "
    "Return ONLY valid compact JSON — no markdown, no backticks."
)

_UNRELATED: dict[str, Any] = {
    "status":         "UNRELATED",
    "confidence":     0.0,
    "reasoning":      "Classification unavailable",
    "miss_tournament": False,
}


class InjuryClassification(BaseModel):
    status:          Literal["CONFIRMED", "SPECULATION", "DENIED", "UNRELATED"]
    confidence:      float = Field(ge=0.0, le=1.0)
    reasoning:       str
    miss_tournament: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_injury(
    player: str,
    country: str,
    article_text: str,
) -> dict[str, Any]:
    """Classify player injury status from article text using LLM.

    Returns a dict matching InjuryClassification fields.
    Never raises — returns UNRELATED on all failures.
    """
    prompt = _build_prompt(player, country, article_text)
    models = [settings.OPENROUTER_MODEL] + list(settings.OPENROUTER_FALLBACK_MODELS)

    for model in models:
        for attempt in range(_MAX_RETRIES):
            try:
                raw  = _call_openrouter(model, prompt)
                data = _parse_response(raw)
                if data is not None:
                    return data
                logger.debug(
                    "LLM parse failed on attempt %d/%d model=%s",
                    attempt + 1, _MAX_RETRIES, model,
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "OpenRouter HTTP error model=%s status=%d — trying next model",
                    model, exc.response.status_code,
                )
                break  # HTTP error from this model — skip to fallback
            except httpx.RequestError as exc:
                logger.warning(
                    "OpenRouter request error model=%s attempt=%d: %s",
                    model, attempt + 1, exc,
                )
            except Exception as exc:
                logger.warning(
                    "LLM classify error model=%s attempt=%d: %s",
                    model, attempt + 1, exc,
                )

    logger.warning("classify_injury: all models/retries exhausted for %s — UNRELATED", player)
    return dict(_UNRELATED)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_prompt(player: str, country: str, article_text: str) -> str:
    return f"""\
Analyze this article about {player} ({country} national team).
Determine their injury/availability status for the upcoming World Cup.

Return ONLY this JSON (no other text):
{{
  "status": "CONFIRMED" | "SPECULATION" | "DENIED" | "UNRELATED",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation (max 100 chars)",
  "miss_tournament": true|false
}}

Article:
{article_text[:2000]}
"""


def _call_openrouter(model: str, prompt: str) -> str:
    if not settings.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not configured")

    headers = {
        "Authorization":  f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type":   "application/json",
        "HTTP-Referer":   settings.OPENROUTER_SITE_URL or "http://localhost",
        "X-Title":        settings.OPENROUTER_APP_NAME,
    }
    payload = {
        "model":    model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens":  200,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(settings.OPENROUTER_BASE_URL, headers=headers, json=payload)
        resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    return content or ""


def _parse_response(raw: str | None) -> dict[str, Any] | None:
    """Parse and validate LLM output. Returns None on any parsing failure."""
    text = (raw or "").strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        data      = json.loads(text)
        validated = InjuryClassification(**data)
        return validated.model_dump()
    except (json.JSONDecodeError, ValidationError, TypeError, KeyError) as exc:
        logger.debug("_parse_response failed: %s — raw=%r", exc, (raw or "")[:200])
        return None
