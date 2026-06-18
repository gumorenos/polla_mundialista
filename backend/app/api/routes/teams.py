from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import db_transaction
from app.db.repositories.elo_history import EloHistoryRepository

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("/{team_id}/elo-history")
def get_team_elo_history(team_id: str) -> list[dict]:
    with db_transaction() as conn:
        repo = EloHistoryRepository(conn)
        history = repo.get_team_history(team_id)
    if not history:
        raise HTTPException(status_code=404, detail="No ELO history found for this team")
    return history
