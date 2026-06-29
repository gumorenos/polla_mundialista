"""Calculate WC2026 group standings from actual match results in the DB.

Used when the external standings API is unavailable or returns no data.
Populates wc2026_standings with current group table state and marks teams
as 'eliminated' once their group stage is fully played.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Each group has 4 teams × 3 fixtures each = 6 total fixtures.
_FIXTURES_PER_GROUP = 6


@dataclass
class _TeamStats:
    team_id: str
    group_id: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def points(self) -> int:
        return self.won * 3 + self.drawn

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against


def calculate_standings_from_results(conn: sqlite3.Connection) -> int:
    """Calculate group standings from actual WC2026 match results.

    Reads played fixtures, computes group tables, then upserts into
    wc2026_standings.  Groups where all 6 fixtures are played get
    positions 3/4 marked as 'eliminated' and 1/2 as 'qualified'.
    Incomplete groups are marked 'active'.

    Returns number of team rows upserted.
    """
    # Load all teams per group
    group_teams: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT group_id, team_id FROM group_teams ORDER BY group_id, position"
    ).fetchall():
        group_teams.setdefault(row["group_id"], []).append(row["team_id"])

    if not group_teams:
        logger.warning("calculate_standings: group_teams table is empty — skipping")
        return 0

    # Initialise stats for every team
    stats: dict[str, _TeamStats] = {}
    for gid, tids in group_teams.items():
        for tid in tids:
            stats[tid] = _TeamStats(team_id=tid, group_id=gid)

    # Count played fixtures per group
    played_count: dict[str, int] = {gid: 0 for gid in group_teams}

    # Load played WC2026 group-stage fixtures
    rows = conn.execute(
        """
        SELECT f.group_id, f.home_team_id, f.away_team_id,
               r.home_goals, r.away_goals
        FROM fixtures f
        JOIN results r ON (
            r.home_team_id = f.home_team_id
            AND r.away_team_id = f.away_team_id
            AND r.match_date = f.match_date
        )
        WHERE f.group_id IS NOT NULL
          AND r.home_goals IS NOT NULL
          AND r.away_goals IS NOT NULL
        """
    ).fetchall()

    for row in rows:
        gid = row["group_id"]
        home, away = row["home_team_id"], row["away_team_id"]
        hg, ag = int(row["home_goals"]), int(row["away_goals"])

        if home not in stats or away not in stats:
            continue  # fixture involves a team not in group_teams — skip

        played_count[gid] = played_count.get(gid, 0) + 1

        for tid, gf, ga in [(home, hg, ag), (away, ag, hg)]:
            s = stats[tid]
            s.played += 1
            s.goals_for += gf
            s.goals_against += ga
            if gf > ga:
                s.won += 1
            elif gf == ga:
                s.drawn += 1
            else:
                s.lost += 1

    # Build sorted group tables and upsert standings
    upserted = 0
    for gid, tids in group_teams.items():
        group_complete = (played_count.get(gid, 0) >= _FIXTURES_PER_GROUP)

        # Sort by: points DESC, goal_diff DESC, goals_for DESC, team_id ASC (stable)
        ranked = sorted(
            [stats[tid] for tid in tids if tid in stats],
            key=lambda s: (-s.points, -s.goal_diff, -s.goals_for, s.team_id),
        )

        for pos, s in enumerate(ranked, start=1):
            if group_complete:
                status = "qualified" if pos <= 2 else "eliminated"
            else:
                status = "active"

            conn.execute(
                """
                INSERT OR REPLACE INTO wc2026_standings
                    (team_id, group_id, position, played, won, drawn, lost,
                     goals_for, goals_against, points, status, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    s.team_id, gid, pos, s.played, s.won, s.drawn, s.lost,
                    s.goals_for, s.goals_against, s.points, status,
                ),
            )
            upserted += 1

    conn.commit()

    eliminated = sum(
        1 for s in stats.values()
        if played_count.get(s.group_id, 0) >= _FIXTURES_PER_GROUP
        and sorted(
            [stats[t] for t in group_teams[s.group_id] if t in stats],
            key=lambda x: (-x.points, -x.goal_diff, -x.goals_for, x.team_id),
        ).index(s) >= 2
    )
    logger.info(
        "calculate_standings: upserted %d teams across %d groups, %d eliminated",
        upserted, len(group_teams), eliminated,
    )
    return upserted
