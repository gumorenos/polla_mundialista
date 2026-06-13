"""Snapshots endpoints — list, create, and compare pipeline snapshots."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, status

from app.db.connection import db_transaction
from app.db.repositories.simulations import SimulationRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])

_PROB_FIELDS = [
    "win_tournament",
    "reach_final",
    "reach_semi_final",
    "reach_quarter_final",
    "reach_round_of_16",
    "qualify",
]


# ---------------------------------------------------------------------------
# GET /api/snapshots
# ---------------------------------------------------------------------------

@router.get("")
def list_snapshots(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    """Return the most recent snapshots."""
    with db_transaction() as conn:
        return SimulationRepository(conn).list_snapshots(limit)


# ---------------------------------------------------------------------------
# POST /api/snapshots/{run_id}
# ---------------------------------------------------------------------------

@router.post("/{run_id}", status_code=status.HTTP_201_CREATED)
def create_manual_snapshot(
    run_id: str,
    label: str = Body(..., embed=True),
    description: str | None = Body(default=None, embed=True),
) -> dict[str, Any]:
    """Create a manual snapshot linked to an existing simulation run."""
    with db_transaction() as conn:
        repo = SimulationRepository(conn)

        # Verify the run exists
        run = conn.execute(
            "SELECT id FROM simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simulation run '{run_id}' not found",
            )

        snap_id = repo.create_snapshot(
            {
                "id": str(uuid.uuid4()),
                "label": label,
                "description": description,
                "trigger": "manual",
                "simulation_run_id": run_id,
            }
        )
        conn.commit()

        snap = repo.get_snapshot_by_id(snap_id)

    return snap  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/snapshots/{id}/compare?other={id2}
# ---------------------------------------------------------------------------

@router.get("/{snapshot_id}/compare")
def compare_snapshots(
    snapshot_id: str,
    other: str = Query(..., description="ID of the second snapshot to compare against"),
) -> dict[str, Any]:
    """Return per-team probability deltas between two snapshots (other − base)."""
    with db_transaction() as conn:
        repo = SimulationRepository(conn)

        snap_a = repo.get_snapshot_by_id(snapshot_id)
        snap_b = repo.get_snapshot_by_id(other)

        if not snap_a:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Snapshot '{snapshot_id}' not found")
        if not snap_b:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Snapshot '{other}' not found")

        summary_a = repo.get_run_summary(snap_a["simulation_run_id"]) if snap_a.get("simulation_run_id") else {}
        summary_b = repo.get_run_summary(snap_b["simulation_run_id"]) if snap_b.get("simulation_run_id") else {}

    results_a: dict[Any, dict] = {r["team_id"]: r for r in summary_a.get("team_results", [])}
    results_b: dict[Any, dict] = {r["team_id"]: r for r in summary_b.get("team_results", [])}

    all_team_ids = set(results_a) | set(results_b)
    deltas = []
    for tid in all_team_ids:
        ra = results_a.get(tid, {})
        rb = results_b.get(tid, {})
        entry: dict[str, Any] = {
            "team_id": tid,
            "team_name": ra.get("team_name") or rb.get("team_name"),
        }
        for field in _PROB_FIELDS:
            va = float(ra.get(field) or 0)
            vb = float(rb.get(field) or 0)
            entry[f"{field}_delta"] = round(vb - va, 6)
        deltas.append(entry)

    deltas.sort(key=lambda d: abs(d.get("win_tournament_delta", 0)), reverse=True)

    return {"snapshot_a": snap_a, "snapshot_b": snap_b, "deltas": deltas}
