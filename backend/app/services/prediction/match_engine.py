"""Low-level match sampling utilities used by Monte Carlo simulations."""

from __future__ import annotations

import numpy as np


def simulate_match(
    home_goals_lambda: float,
    away_goals_lambda: float,
    rng: np.random.Generator,
) -> tuple[int, int]:
    """Sample a scoreline from independent Poisson distributions."""
    home = int(rng.poisson(home_goals_lambda))
    away = int(rng.poisson(away_goals_lambda))
    return home, away


def get_result(home_goals: int, away_goals: int) -> str:
    """Return 'home' | 'draw' | 'away'."""
    if home_goals > away_goals:
        return "home"
    if home_goals == away_goals:
        return "draw"
    return "away"
