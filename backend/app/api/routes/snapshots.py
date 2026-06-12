"""Snapshots endpoints — list pipeline snapshots."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.db.connection import db_transaction
from app.db.repositories.simulations import SimulationRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


@router.get("")
def list_snapshots(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    """Return the most recent snapshots."""
    with db_transaction() as conn:
        return SimulationRepository(conn).list_snapshots(limit)
