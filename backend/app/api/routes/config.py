"""Dynamic app configuration endpoint.

GET  /api/config          — list all config entries (public)
PUT  /api/config/{key}    — update one entry (admin)
POST /api/config/reset    — restore all defaults (admin)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import require_admin
from app.db.connection import db_transaction
from app.db.migrations import _DEFAULT_APP_CONFIG
from app.db.repositories.config import ConfigRepository

router = APIRouter(prefix="/api/config", tags=["config"])

# ---------------------------------------------------------------------------
# Validation rules per key: (type, min, max)
# ---------------------------------------------------------------------------

_VALIDATORS: dict[str, tuple[type, float, float]] = {
    "NEWS_CONFIDENCE_THRESHOLD": (float, 0.5, 1.0),
    "INJURY_ATTACK_PENALTY":     (float, 0.0, 0.5),
    "INJURY_DEFENSE_PENALTY":    (float, 0.0, 0.5),
    "NEWS_MIN_SOURCES":          (int,   1,   5),
    "NEWS_DAYS_LOOKBACK":        (int,   1,   30),
}


def _validate(key: str, raw: str) -> None:
    if key not in _VALIDATORS:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {key}")
    typ, lo, hi = _VALIDATORS[key]
    try:
        val = typ(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{key} must be a {typ.__name__}")
    if not (lo <= val <= hi):
        raise HTTPException(
            status_code=422,
            detail=f"{key} must be between {lo} and {hi}, got {val}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class UpdateBody(BaseModel):
    value: str


@router.get("")
def list_config() -> list[dict[str, Any]]:
    with db_transaction() as conn:
        return ConfigRepository(conn).list_all()


@router.put("/{key}", dependencies=[Depends(require_admin)])
def update_config(key: str, body: UpdateBody) -> dict[str, Any]:
    _validate(key, body.value)
    with db_transaction() as conn:
        repo = ConfigRepository(conn)
        row = repo.set_value(key, body.value)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Config key not found: {key}")
        return row


@router.post("/reset", dependencies=[Depends(require_admin)])
def reset_config() -> list[dict[str, Any]]:
    with db_transaction() as conn:
        return ConfigRepository(conn).reset_all(_DEFAULT_APP_CONFIG)
