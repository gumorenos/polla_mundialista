"""Diagnose why a team's prediction differs across models.

Usage:
    python3 scripts/diagnose_team_model.py ARG --models poisson,poisson_context,elo
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.db.connection import db_transaction  # noqa: E402
from app.services.simulation.constants import GROUPS_2026  # noqa: E402
from app.services.simulation.validation import is_run_valid  # noqa: E402


def _print_header(title: str) -> None:
    print()
    print(f"=== {title} ===")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("team_id")
    parser.add_argument("--models", default="poisson,poisson_context,elo,ml_calibrated,consensus")
    args = parser.parse_args()

    team_id = args.team_id.upper()
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    with db_transaction() as conn:
        team = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team:
            print(f"Team '{team_id}' not found in teams table.")
            sys.exit(1)
        print(f"Team: {dict(team)}")

        _print_header("ELO / ratings")
        for r in conn.execute(
            "SELECT rating_type, value, effective_date, source FROM ratings "
            "WHERE team_id = ? ORDER BY effective_date DESC LIMIT 5",
            (team_id,),
        ):
            print(dict(r))

        _print_header("team_strengths")
        for r in conn.execute(
            "SELECT * FROM team_strengths WHERE team_id = ? ORDER BY computed_at DESC LIMIT 3",
            (team_id,),
        ):
            print(dict(r))

        _print_header("Key player / form adjustment")
        try:
            from app.services.features.player_form import _top_xg_player, get_player_form
            from app.services.features.squad_pool import get_key_player_pool

            pool = get_key_player_pool(team_id, conn)
            print(f"squad_status={pool['squad_status']} source={pool['source']} warning={pool['warning']}")
            top_player = _top_xg_player(team_id, conn, pool["players"])
            if top_player:
                print(f"key_player={top_player}")
                print(get_player_form(top_player, team_id, conn))
            else:
                print("No key player found.")
        except Exception as exc:
            print(f"Error computing player form: {exc}")

        _print_header("Injuries / suspensions adjustments")
        for r in conn.execute(
            "SELECT adjustment_type, attack_factor, defense_factor, notes FROM team_context_adjustments "
            "WHERE team_id = ? ORDER BY created_at DESC LIMIT 10",
            (team_id,),
        ):
            print(dict(r))

        _print_header(f"Expected goals & match probabilities vs group rivals ({models})")
        group_letter = None
        for letter, members in GROUPS_2026.items():
            if team_id in members:
                group_letter = letter
                break
        rivals = [t for t in GROUPS_2026.get(group_letter, []) if t != team_id] if group_letter else []
        if not rivals:
            print(f"Team not found in any GROUPS_2026 entry (group_letter={group_letter})")

        from app.services.simulation.monte_carlo import _init_model
        for model_name in models:
            try:
                model = _init_model(model_name, conn)
            except Exception as exc:
                print(f"[{model_name}] failed to init: {exc}")
                continue
            for rival in rivals:
                try:
                    pred = model.predict_match(team_id, rival, {"is_neutral": True})
                    print(
                        f"[{model_name}] {team_id} vs {rival}: "
                        f"xG={pred['expected_home_goals']:.2f}-{pred['expected_away_goals']:.2f} "
                        f"P={pred['home_win']:.1%}/{pred['draw']:.1%}/{pred['away_win']:.1%}"
                    )
                except Exception as exc:
                    print(f"[{model_name}] {team_id} vs {rival}: ERROR {exc}")

        _print_header("Last simulations for this team, by model")
        for model_name in models:
            rows = conn.execute(
                """
                SELECT sr.id, sr.status, sr.created_at, str.win_tournament, str.reach_round_of_32
                FROM simulation_runs sr
                JOIN simulation_team_results str ON str.simulation_run_id = sr.id
                WHERE sr.model_name = ? AND str.team_id = ?
                ORDER BY sr.created_at DESC LIMIT 3
                """,
                (model_name, team_id),
            ).fetchall()
            for r in rows:
                row = dict(r)
                valid = is_run_valid(conn, row["id"]) if row["status"] == "completed" else None
                print(f"[{model_name}] run={row['id']} status={row['status']} "
                      f"created_at={row['created_at']} win_tournament={row['win_tournament']} "
                      f"reach_round_of_32={row['reach_round_of_32']} valid={valid}")


if __name__ == "__main__":
    main()
