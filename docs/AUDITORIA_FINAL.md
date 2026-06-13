# Auditoría Final — Oráculo Mundial 2026

**Fecha:** 2026-06-13  
**Branch:** main  
**Commit base:** efb268f

---

## 1. Qué está completo

### Backend (FastAPI + SQLite + Redis/RQ)

| Componente | Estado |
|---|---|
| Config central (`app/core/config.py`) con pydantic-settings 2.x | ✅ |
| Logging estructurado (`app/core/logging.py`) | ✅ |
| Migraciones SQLite (`app/db/migrations.py`) — 20 tablas | ✅ |
| Repositorios de datos (`app/db/repositories/`) | ✅ |
| Worker RQ (`app/workers/tasks.py`) — full_refresh, daily_update, news, pre_match_snapshot | ✅ |
| Ingesta CSV + ELO scraper + API-Football (`app/services/ingestion/`) | ✅ |
| Features con decaimiento temporal (`app/services/features/strengths.py`) | ✅ |
| 5 modelos de predicción: baseline, elo, poisson, poisson_context, ml_calibrated | ✅ |
| Monte Carlo 30k iteraciones + bracket WC2026 (`app/services/simulation/`) | ✅ |
| Noticias + clasificador LLM de lesiones (`app/services/news/`) | ✅ |
| ML calibrador LightGBM/XGBoost (`app/services/ml/`) | ✅ |
| Evaluación: Brier/LogLoss/RPS/Accuracy/Calibration + backtesting walk-forward | ✅ |
| Pipeline completo full_refresh + daily_update (`app/services/pipeline/pipeline.py`) | ✅ |
| Scheduler APScheduler (cron full_refresh, news, snapshot horario) | ✅ |
| Rate limiting slowapi (60/min público, 10/min admin) | ✅ |
| Auth por token (`X-Admin-Token`) en endpoints admin y pipelines | ✅ |

### API Endpoints

| Grupo | Endpoints | Estado |
|---|---|---|
| Health | GET /api/health | ✅ |
| Admin | POST /api/admin/ingest | ✅ |
| Simulations | GET /api/simulations/latest, POST /api/simulations/run, GET /api/simulations/{id} | ✅ |
| Snapshots | GET /api/snapshots, POST /api/snapshots/{run_id}, GET /api/snapshots/{id}/compare | ✅ |
| Jobs | GET /api/jobs, GET /api/jobs/{id} | ✅ |
| ML | GET /api/ml/status, POST /api/ml/train | ✅ |
| Pipelines | POST /api/pipelines/full-refresh, POST /api/pipelines/daily-update | ✅ |
| Evaluations | GET /api/evaluations/summary, GET /api/evaluations/calibration | ✅ |
| Metrics | GET /api/metrics | ✅ |

### Frontend (React + Vite + TypeScript)

| Componente | Estado |
|---|---|
| Dashboard — métricas rápidas + top 5 campeones + botones de pipeline | ✅ |
| Models — tabla comparativa con sorting Brier/LogLoss/RPS/Accuracy | ✅ |
| Simulations — selector de modelo, botón Simular, tabla completa de equipos | ✅ |
| Calibration — diagrama de fiabilidad Recharts + métricas por modelo | ✅ |
| Snapshots — listado de snapshots con badges de trigger | ✅ |
| Jobs — estado, progreso, duración, errores, auto-refresh 5s | ✅ |
| React Query v5 hooks centralizados (`api/hooks/index.ts`) | ✅ |
| TypeScript types completos (`types/index.ts`) | ✅ |
| TailwindCSS dark theme | ✅ |

### Infraestructura

| Componente | Estado |
|---|---|
| docker-compose.prod.yml (ARM64, Oracle Cloud) | ✅ |
| Healthchecks en todos los servicios | ✅ |
| Volúmenes nombrados para persistencia | ✅ |
| Redis en red interna (sin puerto externo) | ✅ |
| API en 127.0.0.1:8000 (no expuesta directamente) | ✅ |
| scripts/backup_sqlite.sh (WAL-safe, retención 7 días) | ✅ |
| DEPLOY_ORACLE.md con instrucciones completas | ✅ |

### Tests

| Suite | Tests | Estado |
|---|---|---|
| test_ingestion.py | ~10 | ✅ |
| test_features.py | ~8 | ✅ |
| test_models.py | ~12 | ✅ |
| test_news.py | ~8 | ✅ |
| test_simulation.py | ~10 | ✅ |
| test_security.py | 8 | ✅ |
| Frontend vitest (6 archivos) | 21 | ✅ |

---

## 2. Qué quedó parcial

| Componente | Razón |
|---|---|
| Integración con API-Football en producción | Requiere clave de API real; el servicio está implementado y testeado con mocks, pero no se ha ejecutado contra la API real |
| OpenRouter LLM en producción | Ídem — requiere `OPENROUTER_API_KEY`; el clasificador de lesiones está completo pero no probado end-to-end con la API real |
| Normalización de nombres de equipos (`app/services/normalization/`) | Implementada con diccionario estático; no cubre variantes de idiomas no contempladas en los CSVs iniciales |
| Bracket WC2026 completo | Las eliminatorias están implementadas; los 48 equipos clasificados al Mundial 2026 son un placeholder hasta que FIFA confirme todos los grupos |
| Tests de integración end-to-end | Los tests actuales son unitarios + de integración ligera; no hay tests E2E con Playwright/Cypress para el frontend |

---

## 3. Bugs conocidos

| ID | Módulo | Descripción | Impacto | Workaround |
|---|---|---|---|---|
| BUG-001 | `app/db/repositories/simulations.py` | `get_latest_by_model` filtraba por `status='finished'`; corregido a `status='completed'` en P11 | Bajo (resuelto) | — |
| BUG-002 | `app/core/config.py` | pydantic-settings ≥2.7 falla al parsear `List[str]` desde valores comma-separated antes de llamar al `field_validator`; corregido con `_LenientEnvSource` en P12 | Alto en Docker (resuelto) | — |
| BUG-003 | `app/api/routes/admin.py` | Si Redis no está disponible al hacer POST /api/admin/ingest con token correcto, retorna 500 sin mensaje informativo | Bajo | Verificar Redis antes de llamar |
| BUG-004 | `app/services/news/scraper.py` | El scraper puede ser bloqueado por rate limiting de fuentes (ESPN, BBC) en ejecuciones frecuentes; sin retry exponencial implementado | Medio | `NEWS_DAYS_LOOKBACK` configurable |
| BUG-005 | Frontend `Calibration.tsx` | `ResponsiveContainer` de Recharts requiere `ResizeObserver`; falla en entornos sin soporte DOM (SSR, tests sin polyfill) | Bajo (resuelto en tests) | Polyfill en `test/setup.ts` |

---

## 4. Checklist funcional

```
[x] Backend levanta en Docker (GET /api/health → 200)
[x] Frontend levanta en Docker (GET localhost:3000 → 200)
[x] Redis levanta y worker procesa jobs
[x] SQLite en WAL mode (siempre configurado en db/connection.py)
[x] Admin endpoints protegidos con X-Admin-Token
[x] Rate limiting activo (60/min público)
[x] Backup script funcional (scripts/backup_sqlite.sh)
[x] docker-compose.prod.yml levanta stack completo
[x] README explica setup local, Docker y producción
[ ] API-Football real (requiere clave)
[ ] OpenRouter LLM real (requiere clave)
[ ] Nginx/Caddy reverse proxy delante de :8000 (pendiente deploy)
```

---

## 5. Comandos para levantar el sistema

### Desarrollo local

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Worker (terminal separada)
rq worker --url redis://localhost:6379/0 default long news

# Frontend (terminal separada)
cd frontend
npm install && npm run dev
```

### Docker (producción Oracle Cloud ARM64)

```bash
cp .env.example .env          # completar claves reales
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps  # verificar healthy
```

### Tests

```bash
cd backend && pytest -v
cd frontend && npm test
```

### Backup manual

```bash
bash backend/scripts/backup_sqlite.sh
```

---

## 7. Fixes post-auditoría (Fix-1)

Aplicados el 2026-06-13:

| # | Problema | Solución |
|---|---|---|
| Fix-1.1 | `ADMIN_TOKEN` fail-open (acceso sin token cuando vacío) | `require_admin` dependency fail-closed: 503 si no configurado, 403 si incorrecto. Validador en config rechaza token vacío en `ENVIRONMENT=production`. |
| Fix-1.2 | `POST /api/simulations/run`, `POST /api/snapshots/{run_id}` públicos | Ambos endpoints añadidos a `Depends(require_admin)` + rate limit admin |
| Fix-1.3 | `GET /api/jobs/ping` encolaba jobs reales | Reemplazado por health check puro: solo llama `Redis.ping()`, retorna `{"redis":"ok"}` o 503 |
| Fix-1.4 | Frontend no enviaba `X-Admin-Token` en mutaciones admin | `client.ts` lee `VITE_ADMIN_TOKEN` (build-time), botones deshabilitados si no configurado |
| Fix-1.5 | Contrato roto backend→frontend para métricas (`avg_brier` vs `brier_score`) | `GET /api/evaluations/summary` normaliza a `brier_score`, `log_loss`, `rps`, `accuracy`, `total_predictions` |
| Fix-1.6 | Rate limit admin configurado pero no aplicado | `@limiter.limit(settings.RATE_LIMIT_ADMIN)` en todos los endpoints admin/pipelines/ml/simulations |
| Fix-1.7 | `team_id: number` en TypeScript, backend usa strings | `TeamResult.team_id` corregido a `string` |
| Fix-1.8 | `run-all-models` creaba doble de jobs (dos loops) | Colapsado a un único loop que crea job + encola atomicamente |

Tests añadidos/actualizados: `test_security.py` (14 tests), `test_health.py` (reemplazado ping test), `test_scheduler.py` (auth en snapshots), `test_ingestion.py` (token en admin), `test_health.py` (test_existing_snapshot timing fix).

---

## 6. Próximos pasos

### Alta prioridad

1. **Reverse proxy (Nginx/Caddy)**: exponer puerto 443 con TLS en Oracle Cloud; los contenedores sólo escuchan en `127.0.0.1`.
2. **Claves de API reales**: configurar `API_FOOTBALL_KEY` y `OPENROUTER_API_KEY` en `.env` de producción y ejecutar primer `full_refresh` real.
3. **Datos históricos**: importar CSVs de partidos 2010-2026 para entrenar los modelos con datos reales.

### Mejoras de modelos

4. **Migración a PostgreSQL**: SQLite es suficiente para el MVP pero un World Cup genera picos de tráfico; PostgreSQL con connection pool (asyncpg) mejora la concurrencia. Ver DT-007.
5. **SHAP explicability**: añadir `shap` al modelo ML calibrado para mostrar en el frontend qué features más influyen en cada predicción.
6. **Odds de apuestas como benchmark**: integrar API de Odds (The Odds API) para comparar probabilidades predichas vs. mercado y calcular Kelly criterion.

### Calidad

7. **Tests E2E con Playwright**: cubrir flujo completo Dashboard → trigger pipeline → ver jobs → ver simulación actualizada.
8. **Retry exponencial en scraper de noticias**: evitar bloqueos de fuentes con `tenacity`.
9. **Versionado de modelos**: guardar cada modelo ML entrenado con timestamp en `data/models/` y exponer historial vía API.
