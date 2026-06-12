# Oráculo Mundial 2026 — Contexto del Proyecto

## Objetivo

Web app que predice resultados del Mundial 2026 usando múltiples modelos estadísticos,
simula el torneo completo con Monte Carlo y expone los resultados en un dashboard interactivo.

## Flujo de datos

```
CSVs / APIs externas
       ↓
Ingesta + Normalización (team_names.py)
       ↓
Features: fuerza ofensiva/defensiva con decaimiento temporal
       ↓
5 modelos de predicción paralelos
       ↓
Monte Carlo (30 000 iter) → probabilidades de avance
       ↓
Ajuste por lesiones (LLM extrae datos, no decide)
       ↓
Dashboard React/Vite
```

## Modelos de predicción

| ID | Nombre | Descripción |
|----|--------|-------------|
| `baseline` | Baseline | Probabilidades uniformes / frecuencia histórica global |
| `elo` | ELO | Diferencia ELO → probabilidad victoria/empate/derrota |
| `poisson` | Poisson + Dixon-Coles | Fuerza ofensiva/defensiva → matriz Poisson con corrección DC |
| `poisson_context` | Poisson Contextual | Poisson + ajustes por lesiones, localía, importancia |
| `ml_calibrated` | ML Calibrado | Ensamblador LightGBM/XGBoost entrenado con features históricas |

## Stack

### Backend
- Python 3.11+, FastAPI, Pydantic Settings
- SQLite WAL (diseñado para migrar a PostgreSQL)
- Redis + RQ (background jobs)
- SQLAlchemy Core (sin ORM completo)
- pandas, numpy, scipy, scikit-learn, xgboost, lightgbm
- requests, httpx, BeautifulSoup4, lxml
- APScheduler, tenacity, python-dotenv, pytest

### Frontend
- React + Vite + TypeScript
- Tailwind CSS, Recharts, TanStack Query v5, TanStack Table v8

### Infraestructura
- Docker Compose (api, frontend, redis, worker, scheduler)
- Cloudflare Tunnel (Oracle Cloud Free ARM)

## Reglas de diseño críticas

1. **Modularidad**: un archivo = una responsabilidad.
2. **Determinismo**: matemáticas/regex nunca delegadas al LLM.
3. **Cero credenciales en código**: solo `python-dotenv` + `.env`.
4. **Configuración central**: `backend/app/core/config.py` (Pydantic Settings).
5. **Validación**: todo input externo pasa por Pydantic antes de persistir.
6. **Logging estructurado**: `timestamp | nivel | módulo | mensaje`, persistido en archivo.
7. **Tests mínimos**: al menos un test de cordura por módulo crítico.
8. **Tolerancia a fallos**: red/API/LLM usan `tenacity`; fallos → WARNING + continuar.
9. **SQLite WAL**: `PRAGMA journal_mode=WAL` + `busy_timeout`.
10. **Jobs en background**: simulaciones, scraping, noticias, ML → RQ workers. API nunca bloquea.
11. **Trazabilidad**: cada predicción/simulación guarda `run_id`, `model_name`, `model_version`, `data_version_hash`, `config_snapshot`, `created_at`.
12. **No sobrescribir histórico**: solo INSERT en tablas de predicciones/simulaciones.
13. **IA limitada**: LLM solo extrae datos estructurados de noticias. No decide ganadores.
14. **Shell**: bash en scripts/Dockerfiles; fish permitido en desarrollo local.

## Base de datos — tablas principales

```
teams, groups, group_teams, fixtures, results,
ratings, team_strengths,
availability_claims, team_context_adjustments,
prediction_runs, match_predictions,
simulation_runs, simulation_team_results,
jobs, job_logs,
ml_training_runs, ml_models, ml_feature_snapshots,
model_evaluations,
data_sources, snapshots
```

## Parámetros clave (defaults)

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `TIME_DECAY_FACTOR` | 0.001 | `exp(-factor * días)` |
| `DIXON_COLES_RHO` | 0.15 | Corrección dependencia goles bajos |
| `LOCAL_ADVANTAGE_HOME` | 1.1 | Multiplicador localía |
| `INJURY_ATTACK_PENALTY` | 0.15 | Reducción ataque por lesión estrella |
| `NEWS_CONFIDENCE_THRESHOLD` | 0.7 | Score mínimo LLM para confirmar lesión |
| `MONTECARLO_ITERATIONS` | 30 000 | Iteraciones simulación |
| `MONTECARLO_SEED` | 42 | Reproducibilidad |
| `ML_TRAIN_START_YEAR` | 2010 | Inicio ventana entrenamiento |

## Orden de implementación

1. **Prompt 1** — Infraestructura base: config, logging, DB, migraciones, health check
2. **Prompt 2** — Ingesta de datos: CSVs, ELO scraper, FIFA rankings, API-Football
3. **Prompt 3** — Features: strengths con decaimiento temporal
4. **Prompt 4** — Modelos: baseline, ELO, Poisson+DC, Poisson contextual
5. **Prompt 5** — Monte Carlo + bracket WC2026
6. **Prompt 6** — Noticias + LLM classifier (lesiones)
7. **Prompt 7** — ML calibrador (LightGBM/XGBoost)
8. **Prompt 8** — Evaluación: Brier, LogLoss, RPS, backtesting, calibración
9. **Prompt 9** — API REST completa + background jobs (RQ)
10. **Prompt 10** — Scheduler (APScheduler)
11. **Prompt 11** — Frontend React/Vite
12. **Prompt 12** — Docker Compose + deploy Oracle Cloud
