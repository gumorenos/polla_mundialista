"""Abstract prediction interface — all statistical models implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PredictionModel(ABC):
    name: str
    version: str

    @abstractmethod
    def predict_match(
        self,
        home_team_id: str,
        away_team_id: str,
        context: dict | None = None,
    ) -> dict:
        """Return outcome probabilities and goal estimates for one match.

        Keys in returned dict:
            home_win (float)          — probability 0-1
            draw (float)
            away_win (float)
            expected_home_goals (float)
            expected_away_goals (float)
            most_likely_score (str)   — e.g. "2-1"
            features_used (list[str])
            features_missing (list[str])
            explanation (str)
        """

    def predict_batch(
        self,
        fixtures: list[dict],
        context: dict | None = None,
    ) -> list[dict]:
        return [self.predict_match(f["home"], f["away"], context) for f in fixtures]
