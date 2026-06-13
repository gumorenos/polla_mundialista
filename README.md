# Oráculo Mundial 2026

Predictor estadístico del Mundial FIFA 2026. Combina **5 modelos** comparables, simulación Monte Carlo (30 000 iteraciones) y análisis LLM de lesiones para generar probabilidades de avance por selección.

## Stack

| Capa | Tecnologías |
|---|---|
| Backend | Python 3.11, FastAPI, SQLite WAL, Redis + RQ, APScheduler |
| Modelos | pandas, numpy, scipy, scikit-learn, XGBoost, LightGBM |
| LLM | OpenRouter + DeepSeek V3 (solo extracción de datos de lesiones) |
| Frontend | React 18 + Vite + TypeScript, Tailwind CSS, Recharts, TanStack Query v5 |
| Infra | Docker Compose, Nginx, Oracle Cloud Free ARM |

---

## Setup local (sin Docker)

```bash
# 1. Clonar
git clone https://github.com/gumorenos/polla_mundialista.git
cd polla_mundialista

# 2. Variables de entorno
cp .env.example .env
# Editar .env: ADMIN_TOKEN, API_FOOTBALL_KEY, OPENROUTER_API_KEY

# 3. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Levantar Redis (requiere Docker o Redis local)
docker run -d -p 6379:6379 redis:7-alpine

# API
uvicorn app.main:app --reload

# Worker RQ (otra terminal)
rq worker --url redis://localhost:6379 default long ml news

# 4. Frontend (otra terminal)
cd ../frontend
npm install
npm run dev   # http://localhost:5173
```

---

## Setup con Docker (desarrollo)

```bash
docker compose up --build
# API: http://localhost:8000/api/docs
# Frontend: http://localhost:3000
```

---

## Setup producción (Oracle Cloud ARM)

Ver guía completa en [`docs/DEPLOY_ORACLE.md`](docs/DEPLOY_ORACLE.md).

```bash
cp .env.example .env && nano .env        # rellenar ADMIN_TOKEN, keys
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps   # todos deben ser healthy
```

---

## Operación

### Full refresh inicial (carga datos + modelos + simulaciones)

```bash
curl -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/pipelines/full-refresh
```

### Daily update incremental

```bash
curl -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/pipelines/daily-update
```

### Simular un modelo concreto

```bash
curl -X POST http://localhost:8000/api/simulations/run \
  -H "Content-Type: application/json" \
  -d '{"model_name": "poisson", "iterations": 30000}'
```

### Monitoreo del sistema

```bash
curl -s http://localhost:8000/api/metrics | python3 -m json.tool
```

### Backup de la base de datos

```bash
bash backend/scripts/backup_sqlite.sh
```

---

## Endpoints principales

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/metrics` | Estado del sistema (jobs, modelos, lesiones) |
| POST | `/api/pipelines/full-refresh` | Full refresh (auth requerida) |
| POST | `/api/pipelines/daily-update` | Update incremental (auth requerida) |
| POST | `/api/simulations/run` | Lanzar simulación Monte Carlo |
| GET | `/api/simulations/latest?model=poisson` | Últimos resultados |
| GET | `/api/evaluations/summary` | Métricas comparativas de todos los modelos |
| GET | `/api/evaluations/calibration?model=elo` | Datos de calibración para gráfico |
| GET | `/api/jobs` | Lista de jobs recientes |
| GET | `/api/snapshots` | Snapshots guardados |
| POST | `/api/ml/train` | Entrenar modelo ML calibrado (auth) |
| GET | `/api/docs` | Swagger UI |

---

## Modelos de predicción

| Modelo | Descripción |
|---|---|
| `baseline` | Probabilidades históricas o uniformes si no hay datos |
| `elo` | Diferencia ELO → logística → probabilidades |
| `poisson` | Fuerzas ofensiva/defensiva con decaimiento temporal + Dixon-Coles |
| `poisson_context` | Poisson + ajuste por lesiones confirmadas |
| `ml_calibrated` | LightGBM/XGBoost entrenado con 11 features históricas; degrada a Poisson si no hay modelo entrenado |

---

## Variables de entorno clave

| Variable | Descripción | Requerida en prod |
|---|---|---|
| `ADMIN_TOKEN` | Protege `/api/admin/*` y `/api/pipelines/*` | Sí |
| `API_FOOTBALL_KEY` | API key de api-sports.io | Recomendada |
| `OPENROUTER_API_KEY` | API key de OpenRouter (LLM lesiones) | Recomendada |
| `CORS_ORIGINS` | URLs permitidas de CORS, separadas por coma | Sí |
| `RATE_LIMIT_PUBLIC` | Límite para endpoints públicos (default: `60/minute`) | No |
| `RATE_LIMIT_ADMIN` | Límite para admin (default: `10/minute`) | No |
| `SCHEDULER_ENABLED` | Activar scheduler APScheduler (default: `true`) | No |

Ver todas en [`.env.example`](.env.example).

---

## Tests

```bash
cd backend
pytest --tb=short           # 191 tests
pytest tests/test_security.py  # seguridad + rate limiting
pytest tests/test_scheduler.py # scheduler + snapshots + métricas
```

```bash
cd frontend
npm run test:run            # 21 tests (vitest + RTL)
```

---

## Estructura

```
backend/app/
  core/          config.py (Pydantic Settings), logging.py
  db/            conexión SQLite WAL, migraciones, repositorios
  services/
    ingestion/   CSV loader, ELO scraper, API-Football
    prediction/  baseline, elo, poisson, poisson_context, ml_calibrated
    simulation/  Monte Carlo, bracket WC2026
    features/    team strengths con decaimiento temporal
    evaluation/  métricas (Brier, RPS, LogLoss), backtesting walk-forward
    ml/          feature_builder, trainer (LightGBM/XGBoost/RF)
    news/        scraper, LLM classifier, availability
    jobs/        pipeline (full_refresh, daily_update)
  api/routes/    health, admin, simulations, snapshots, jobs, ml, pipelines, evaluations, metrics
  workers/       RQ tasks
  scheduler/     APScheduler (full_refresh, news_update, check_and_snapshot)

frontend/src/
  pages/         Dashboard, Models, Simulations, Calibration, Snapshots, Jobs
  api/hooks/     React Query hooks (query + mutation)
  types/         TypeScript interfaces

data/
  raw/           CSVs semilla (teams, groups, fixtures, results, ELO)
  sqlite/        oraculo.db — excluido de git
  backups/       backups gzip — excluidos de git
  models/        modelos ML serializados — excluidos de git
```

---

## Licencia

MIT
