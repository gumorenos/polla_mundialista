from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class FixtureRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_by_id(self, fixture_id: str) -> dict[str, Any] | None:
        return _row(
            self._c.execute(
                "SELECT * FROM fixtures WHERE id = ?", (fixture_id,)
            ).fetchone()
        )

    def list_by_stage(self, stage: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._c.execute(
                "SELECT * FROM fixtures WHERE stage = ? ORDER BY match_date",
                (stage,),
            ).fetchall()
        ]

    def list_by_group(self, group_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._c.execute(
                "SELECT * FROM fixtures WHERE group_id = ? ORDER BY match_date",
                (group_id,),
            ).fetchall()
        ]

    def upsert(self, fixture: dict[str, Any]) -> None:
        fixture.setdefault("id", str(uuid.uuid4()))
        self._c.execute(
            """
            INSERT INTO fixtures
                (id, stage, group_id, home_team_id, away_team_id,
                 match_date, venue, is_neutral, tournament)
            VALUES
                (:id, :stage, :group_id, :home_team_id, :away_team_id,
                 :match_date, :venue, :is_neutral, :tournament)
            ON CONFLICT(id) DO UPDATE SET
                stage        = excluded.stage,
                group_id     = excluded.group_id,
                home_team_id = excluded.home_team_id,
                away_team_id = excluded.away_team_id,
                match_date   = excluded.match_date,
                venue        = excluded.venue,
                is_neutral   = excluded.is_neutral,
                tournament   = excluded.tournament
            """,
            {
                "id":           fixture["id"],
                "stage":        fixture["stage"],
                "group_id":     fixture.get("group_id"),
                "home_team_id": fixture.get("home_team_id"),
                "away_team_id": fixture.get("away_team_id"),
                "match_date":   fixture.get("match_date"),
                "venue":        fixture.get("venue"),
                "is_neutral":   int(fixture.get("is_neutral", True)),
                "tournament":   fixture.get("tournament", "WC2026"),
            },
        )


class ResultRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def insert(self, result: dict[str, Any]) -> None:
        result.setdefault("id", str(uuid.uuid4()))
        self._c.execute(
            """
            INSERT OR IGNORE INTO results
                (id, fixture_id, home_team_id, away_team_id,
                 home_goals, away_goals, outcome,
                 match_date, tournament, stage, is_wc, source)
            VALUES
                (:id, :fixture_id, :home_team_id, :away_team_id,
                 :home_goals, :away_goals, :outcome,
                 :match_date, :tournament, :stage, :is_wc, :source)
            """,
            {
                "id":           result["id"],
                "fixture_id":   result.get("fixture_id"),
                "home_team_id": result["home_team_id"],
                "away_team_id": result["away_team_id"],
                "home_goals":   result.get("home_goals"),
                "away_goals":   result.get("away_goals"),
                "outcome":      result.get("outcome"),
                "match_date":   result["match_date"],
                "tournament":   result.get("tournament"),
                "stage":        result.get("stage"),
                "is_wc":        int(result.get("is_wc", False)),
                "source":       result.get("source"),
            },
        )

    def list_by_team(self, team_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._c.execute(
                """
                SELECT * FROM results
                WHERE home_team_id = ? OR away_team_id = ?
                ORDER BY match_date DESC
                """,
                (team_id, team_id),
            ).fetchall()
        ]

    def list_since_date(self, since: str, team_id: str | None = None) -> list[dict[str, Any]]:
        if team_id:
            rows = self._c.execute(
                """
                SELECT * FROM results
                WHERE match_date >= ?
                  AND (home_team_id = ? OR away_team_id = ?)
                ORDER BY match_date
                """,
                (since, team_id, team_id),
            ).fetchall()
        else:
            rows = self._c.execute(
                "SELECT * FROM results WHERE match_date >= ? ORDER BY match_date",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]
