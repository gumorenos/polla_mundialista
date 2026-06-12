"""Canonical names and lookup tables used across the codebase.

Extended progressively as data is ingested — do not hardcode business
logic here; only stable reference data.
"""

CONFEDERATIONS = ["UEFA", "CONMEBOL", "CONCACAF", "CAF", "AFC", "OFC"]

# WC 2026 host countries (shared venue effect)
HOST_COUNTRIES = {"USA", "Canada", "Mexico"}

# Outcome labels used consistently across all models
OUTCOME_WIN = "W"
OUTCOME_DRAW = "D"
OUTCOME_LOSS = "L"

MODEL_IDS = [
    "baseline",
    "elo",
    "poisson",
    "poisson_context",
    "ml_calibrated",
]
