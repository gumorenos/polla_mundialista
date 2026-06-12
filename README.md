# Oráculo Mundial 2026

Predictor estadístico del Mundial FIFA 2026. Combina cinco modelos comparables,
simulación Monte Carlo (30 000 iteraciones) y análisis de noticias de lesiones con LLM
para generar probabilidades de avance por equipo.

## Stack

| Capa | Tecnologías |
|------|-------------|
| Backend | Python 3.11, FastAPI, SQLite WAL, Redis + RQ, APScheduler |
| Modelos | pandas, numpy, scipy, scikit-learn, xgboost, lightgbm |
| LLM | OpenRouter + DeepSeek V3 (solo extracción de datos de lesiones) |
| Frontend | React + Vite + TypeScript, Tailwind CSS, Recharts, TanStack Query v5 |
| Infra | Docker Compose, Cloudflare Tunnel, Oracle Cloud Free ARM |

## Inicio rápido (desarrollo)

```bash
# 1. Clonar y configurar entorno
cp .env.example .env
# Editar .env con tus API keys

# 2. Levantar servicios
docker compose up --build

# 3. Aplicar migraciones
docker compose exec api python -m app.db.migrations

# 4. Cargar datos semilla
docker compose exec api python -m app.services.ingestion.csv_loader

# 5. Correr primera simulación
docker compose exec api python -m app.workers.tasks run_full_pipeline
```

## Comandos útiles

```bash
# Tests
cd backend && pytest

# Ver logs del worker
docker compose logs -f worker

# Forzar refresco de datos
docker compose exec api python -c "from app.workers.tasks import run_full_pipeline; run_full_pipeline.delay()"

# Shell interactivo
docker compose exec api python
```

## Modelos de predicción

| Modelo | Descripción |
|--------|-------------|
| `baseline` | Control: probabilidades uniformes o frecuencia histórica |
| `elo` | Diferencia ELO → probabilidades via logística |
| `poisson` | Fuerza ofensiva/defensiva → Poisson + corrección Dixon-Coles |
| `poisson_context` | Poisson + lesiones confirmadas + ajuste de localía |
| `ml_calibrated` | Ensamblador LightGBM/XGBoost entrenado con features históricas |

## Estructura

```
backend/app/
  core/          config.py, logging.py, constants.py
  db/            conexión SQLite, migraciones, repositorios
  services/      ingesta, features, predicción, simulación, noticias, ML, evaluación
  api/routes/    endpoints REST
  workers/       RQ tasks
  scheduler/     APScheduler jobs

frontend/src/
  pages/         Dashboard, Teams, Models, Simulations, Snapshots, Calibration, Jobs
  components/    Layout, charts, tabla comparativa

data/
  raw/           CSVs semilla (teams, fixtures, results, ELO, FIFA rankings)
  processed/     modelos ML serializados
  sqlite/        oraculo.db (excluido de git)
```

## Seguridad

- Cero credenciales en código — todo desde `.env`
- Endpoint `/admin/*` protegido por token (`ADMIN_TOKEN`)
- SQLite WAL con `busy_timeout` para concurrencia segura

## Licencia

MIT
