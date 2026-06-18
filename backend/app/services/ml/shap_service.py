"""SHAP-based explainability helpers for the ML Calibrated model.

All functions are pure computation — no DB access.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Human-readable labels and descriptions for each feature
FEATURE_META: dict[str, dict[str, str]] = {
    "elo_home":    {"label": "ELO local",              "desc": "Rating ELO del equipo local"},
    "elo_away":    {"label": "ELO visitante",           "desc": "Rating ELO del equipo visitante"},
    "elo_diff":    {"label": "Diferencia ELO",          "desc": "ELO local minus ELO visitante"},
    "attack_home": {"label": "Ataque local",            "desc": "Fuerza ofensiva relativa del local"},
    "defense_home":{"label": "Defensa local",           "desc": "Solidez defensiva del local (mayor = más goles concedidos)"},
    "attack_away": {"label": "Ataque visitante",        "desc": "Fuerza ofensiva relativa del visitante"},
    "defense_away":{"label": "Defensa visitante",       "desc": "Solidez defensiva del visitante"},
    "is_neutral":  {"label": "Terreno neutral",         "desc": "1 si es campo neutro, 0 si hay local"},
    "lam_home":    {"label": "λ goles esperados (local)",   "desc": "Goles esperados del local según Poisson"},
    "lam_away":    {"label": "λ goles esperados (visit.)",  "desc": "Goles esperados del visitante según Poisson"},
    "elo_p_home":  {"label": "Prob. ELO (local gana)",  "desc": "Probabilidad de victoria local según ELO puro"},
}


def compute_global_shap(
    model: Any,
    X_sample: Any,
    feature_names: list[str],
) -> dict[str, float]:
    """Compute mean |SHAP| importance across a sample for the home-win class.

    Returns {feature_name: importance} sorted descending. Returns {} on error.
    """
    try:
        import shap
        import pandas as pd

        if not isinstance(X_sample, pd.DataFrame):
            X_sample = pd.DataFrame(X_sample, columns=feature_names)

        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X_sample)

        # Resolve class axis: sv is list[ndarray] (older shap) or 3-D ndarray (newer)
        if isinstance(sv, list):
            sv_home = np.array(sv[0])       # class 0 = home_win
        elif isinstance(sv, np.ndarray) and sv.ndim == 3:
            sv_home = sv[:, :, 0]           # shape (n, features, classes)
        else:
            sv_home = np.array(sv)

        importance = {
            feature_names[i]: float(np.abs(sv_home[:, i]).mean())
            for i in range(len(feature_names))
        }
        return dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

    except Exception as exc:
        logger.warning("compute_global_shap failed: %s", exc)
        return {}


def explain_match(
    model: Any,
    features: list[float],
    feature_names: list[str],
    home_team: str,
    away_team: str,
    prediction: dict[str, float],
) -> dict[str, Any]:
    """Compute per-match SHAP explanation for the home-win class.

    Returns the explanation dict with top_factors and summary.
    Returns a graceful error dict if shap is unavailable.
    """
    try:
        import shap
        import pandas as pd

        X = pd.DataFrame([features], columns=feature_names)
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X)

        if isinstance(sv, list):
            sv_home = np.array(sv[0])[0]    # shape (n_features,)
        elif isinstance(sv, np.ndarray) and sv.ndim == 3:
            sv_home = sv[0, :, 0]
        else:
            sv_home = np.array(sv)[0]

        factors = []
        for i, name in enumerate(feature_names):
            shap_val = float(sv_home[i])
            feat_val = float(features[i])
            meta = FEATURE_META.get(name, {"label": name, "desc": ""})
            direction = (
                "favors_home" if shap_val > 0.005
                else "favors_away" if shap_val < -0.005
                else "neutral"
            )
            factors.append({
                "feature":          name,
                "label":            meta["label"],
                "value":            round(feat_val, 4),
                "shap_contribution": round(shap_val, 4),
                "direction":        direction,
                "description":      meta["desc"],
            })

        factors.sort(key=lambda f: abs(f["shap_contribution"]), reverse=True)
        top10 = factors[:10]

        # Build natural language summary from top 3
        pos = [f for f in top10 if f["direction"] == "favors_home"][:2]
        neg = [f for f in top10 if f["direction"] == "favors_away"][:1]
        parts: list[str] = []
        for f in pos:
            parts.append(f"{f['label']} ({f['value']:.2f}, +{f['shap_contribution']:.3f})")
        for f in neg:
            parts.append(f"{f['label']} ({f['value']:.2f}, {f['shap_contribution']:.3f})")

        hw = prediction.get("home_win", 0)
        if hw > 0.5:
            leaning = f"El modelo favorece a {home_team}"
        elif hw < 0.35:
            leaning = f"El modelo favorece a {away_team}"
        else:
            leaning = "El modelo ve el partido equilibrado"

        summary = leaning
        if parts:
            summary += f" principalmente por: {', '.join(parts)}."

        return {
            "top_factors": top10,
            "summary": summary,
        }

    except Exception as exc:
        logger.warning("explain_match failed: %s", exc)
        return {
            "top_factors": [],
            "summary": f"Explicación no disponible: {exc}",
        }
