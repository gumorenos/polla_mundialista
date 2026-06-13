# Code Audit Phase 1 - Architecture, Dependencies, Configuration

Audit date: 2026-06-13
Repository root: `D:\projects\claude\polla_mundialista`
Audit mode: read-only inspection; no tests, package installs, commits, branch changes, or destructive commands were run.

## Scope

The checkout is a monorepo-style project. Per the instruction to treat each subfolder as an independent repository, the reviewed units are:

| Repository unit | Purpose | Review depth |
|---|---|---|
| `backend` | FastAPI API, SQLite data layer, RQ workers, APScheduler, prediction/ML/news services | Deep |
| `frontend` | React/Vite UI, TanStack Query hooks, dashboard pages | Deep |
| `docker` | Backend/frontend image definitions and production nginx config | Deep |
| `data` | Seed CSV/JSON data and generated calibration exports | Targeted |
| `docs` | Deployment and project documentation | Targeted |

Excluded from review: `.git`, `frontend/node_modules`, `frontend/dist`, generated cache folders, and runtime data folders ignored by `.gitignore`.

## Architecture

Purpose: Oraculo Mundial 2026 is a FIFA World Cup 2026 prediction system. It combines seeded/historical football data, ELO/API ingestion, five prediction models, Monte Carlo tournament simulation, ML calibration, and LLM-assisted injury extraction.

Tech stack:

| Layer | Evidence | Stack |
|---|---|---|
| Backend API | `README.md`, `backend/requirements.txt` | Python 3.11, FastAPI, Uvicorn |
| Data | `backend/app/db/connection.py`, `backend/app/db/migrations.py` | SQLite WAL, repository classes |
| Workers/scheduler | `backend/app/workers/tasks.py`, `backend/app/scheduler/scheduler.py` | Redis, RQ, APScheduler |
| ML/statistics | `backend/requirements.txt`, `backend/app/services/ml/trainer.py` | pandas, numpy, scipy, scikit-learn, LightGBM, XGBoost |
| LLM/news | `backend/app/services/news/*` | Google News RSS/article scraping, OpenRouter |
| Frontend | `frontend/package.json`, `frontend/src` | React 18, Vite, TypeScript, TanStack Query, Recharts |
| Deployment | `docker-compose*.yml`, `docker/*` | Docker Compose, Nginx, Redis |

Primary architecture concerns:

- The backend combines API serving, migration execution, and scheduler startup in the same FastAPI lifespan (`backend/app/main.py:24-36`). This is simple for one replica but risky if the API is scaled horizontally because every API process can register scheduled jobs.
- SQLite WAL is acceptable for the MVP, but the application has CPU-heavy job triggers and public polling endpoints. Concurrency, locking, and job queue saturation need operational limits before public production exposure.
- The Docker production compose file binds API and frontend to localhost (`docker-compose.prod.yml:47-48`, `docker-compose.prod.yml:131-132`), which is good, but the frontend image does not use the hardened production nginx config.

## Dependency Posture

Backend dependencies are declared as broad version ranges, for example `fastapi>=0.110.0,<1.0.0`, `httpx>=0.27.0`, `xgboost>=2.0.0`, and `lightgbm>=4.3.0` in `backend/requirements.txt`. There is no lockfile or hash-pinned Python dependency set.

Frontend dependencies are lockfile-backed (`frontend/package-lock.json` exists), but source manifests still use caret ranges such as `vite`, `vitest`, `@vitejs/plugin-react`, and React packages in `frontend/package.json`. The frontend Dockerfile uses `npm install --legacy-peer-deps` rather than `npm ci`, which weakens reproducibility (`docker/Dockerfile.frontend:6`).

No dependency vulnerability scanner was run. That would be a separate active check and was skipped because the audit was inspection-only.

## Configuration Findings

### Finding P1-1: Admin token protection fails open when `ADMIN_TOKEN` is missing

- Severity: Critical
- Repository: `backend`
- File/path: `backend/app/core/config.py`, `backend/app/api/routes/admin.py`, `backend/app/api/routes/pipelines.py`, `backend/app/api/routes/ml.py`, `.env.example`
- Evidence from the code:
  - `backend/app/core/config.py:91` defaults `ADMIN_TOKEN` to an empty string.
  - `backend/app/api/routes/admin.py:18-21` returns without rejecting if `settings.ADMIN_TOKEN` is empty.
  - `backend/app/api/routes/pipelines.py:24-25` has the same fail-open behavior.
  - `backend/app/api/routes/ml.py:23-24` has the same fail-open behavior.
  - `.env.example:45` uses `ADMIN_TOKEN=change_me_in_production`, but there is no startup validation that rejects missing or placeholder secrets.
- Why it matters: If production starts without a real token, admin, pipeline, and ML training endpoints become unauthenticated. These endpoints enqueue expensive jobs and mutate persistent state.
- Suggested fix: Fail closed in production. Validate at startup that `ENVIRONMENT=production` requires a non-empty, non-placeholder `ADMIN_TOKEN`. Change `_require_admin` to reject when no token is configured outside explicit local development.
- Estimated effort: Low
- Fix immediately or later: Immediately

### Finding P1-2: Production image does not use the hardened nginx config

- Severity: Medium
- Repository: `docker`
- File/path: `docker/Dockerfile.frontend`, `frontend/nginx.conf`, `docker/nginx.prod.conf`
- Evidence from the code:
  - `docker/Dockerfile.frontend:15` copies `nginx.conf` from the frontend build context.
  - `frontend/nginx.conf` lacks the security headers and `server_tokens off` present in `docker/nginx.prod.conf:5-13`.
  - `docker/nginx.prod.conf` appears unused by the frontend Dockerfile.
- Why it matters: The repo contains a hardened production nginx configuration, but the deployed frontend image uses the less hardened config. This creates drift between intended and actual deployment hardening.
- Suggested fix: Copy the production nginx config into the production frontend image, or remove the unused config and harden `frontend/nginx.conf` directly. Add a build/test assertion that the deployed config contains expected headers.
- Estimated effort: Low
- Fix immediately or later: Immediately before public deployment

### Finding P1-3: Docker images run as root and dependency installation is not reproducible enough

- Severity: Medium
- Repository: `docker`, `backend`, `frontend`
- File/path: `docker/Dockerfile.backend`, `docker/Dockerfile.frontend`, `backend/requirements.txt`, `frontend/package.json`
- Evidence from the code:
  - `docker/Dockerfile.backend:10` runs `pip install --no-cache-dir -r requirements.txt` from broad ranges.
  - `docker/Dockerfile.backend` does not define a non-root `USER`.
  - `docker/Dockerfile.frontend:6` runs `npm install --legacy-peer-deps`.
  - `docker/Dockerfile.frontend` does not define a non-root runtime user; the nginx base image defaults should not be assumed as an app security boundary.
- Why it matters: Broad dependency ranges and install-time resolution reduce build reproducibility. Running containers as root increases impact if a service or dependency is compromised.
- Suggested fix: Add pinned Python lock output or a constraints file, use `npm ci` for frontend builds, and define non-root runtime users where feasible. Add image scanning in CI.
- Estimated effort: Medium
- Fix immediately or later: Later, but before production hardening

### Finding P1-4: `RATE_LIMIT_ADMIN` is configured but not applied

- Severity: Medium
- Repository: `backend`
- File/path: `.env.example`, `backend/app/core/config.py`, `backend/app/main.py`
- Evidence from the code:
  - `.env.example:52` declares `RATE_LIMIT_ADMIN=10/minute`.
  - `backend/app/core/config.py:134` exposes `RATE_LIMIT_ADMIN`.
  - `backend/app/main.py:43-44` only sets `default_limits=[settings.RATE_LIMIT_PUBLIC]`; admin routes do not use the admin-specific limit.
- Why it matters: The most expensive mutation endpoints are not given stricter rate limits. If auth is misconfigured, public/default limits are the only control.
- Suggested fix: Apply `limiter.limit(settings.RATE_LIMIT_ADMIN)` to admin, pipeline, ML training, simulation-run, snapshot-create, and ping enqueue routes as appropriate.
- Estimated effort: Low
- Fix immediately or later: Immediately with auth fixes

### Finding P1-5: Scheduler is embedded in the API process by default

- Severity: Medium
- Repository: `backend`, `docker`
- File/path: `backend/app/core/config.py`, `backend/app/main.py`, `docker-compose.prod.yml`
- Evidence from the code:
  - `backend/app/core/config.py:139` defaults `SCHEDULER_ENABLED` to `True`.
  - `backend/app/main.py:32-36` starts/stops APScheduler during FastAPI lifespan.
  - `docker-compose.prod.yml:46` sets `SCHEDULER_ENABLED: "true"` on the API service; production compose has no dedicated scheduler service.
- Why it matters: One API replica is acceptable, but more than one replica would register duplicate scheduled jobs and duplicate full refresh/news/snapshot work.
- Suggested fix: Move scheduler into a separate service, or set `SCHEDULER_ENABLED=false` for API and run exactly one scheduler process.
- Estimated effort: Medium
- Fix immediately or later: Later unless API replicas are introduced

## Positive Notes

- `.gitignore` excludes `.env`, local databases, WAL files, backups, logs, node modules, build output, and ML artifacts.
- Production compose binds API/frontend ports to `127.0.0.1`, reducing direct exposure if a reverse proxy/tunnel is configured correctly.
- Config parsing handles comma-separated list env vars.
- SQLite connections enable WAL, busy timeout, and foreign keys.

## Phase 1 Summary

Architecture is coherent for an MVP and the stack choices match the stated purpose. The most urgent Phase 1 work is configuration hardening: production must not start without real secrets, admin limits need to apply to admin endpoints, and Docker should use the hardened nginx config that already exists.
