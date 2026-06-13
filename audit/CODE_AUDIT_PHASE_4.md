# Code Audit Phase 4 - Tests, CI/CD, Deployment

Audit date: 2026-06-13
Audit mode: read-only inspection. Test/static-analysis commands were not run.

## Test Inventory

Backend tests under `backend/tests` cover migrations, repositories, ingestion, features, prediction models, ML, news, pipeline behavior, scheduler, health, simulation, and security. Frontend tests under `frontend/src/tests` cover page render smoke tests with mocked hooks.

Evidence:

- Backend pytest configuration: `backend/pyproject.toml:1-5`
- Frontend scripts: `frontend/package.json:9-12`
- README test commands: `README.md:164-171`
- Security tests set `ADMIN_TOKEN` before testing rejection: `backend/tests/test_security.py:32-34`
- Frontend model/dashboard tests mock `brier_score` fields that backend summary does not return: `frontend/src/tests/Models.test.tsx:9-10`, `frontend/src/tests/Dashboard.test.tsx:9-10`

## CI/CD and Deployment Inventory

- No root `.github/workflows` directory was found in this checkout.
- Docker Compose production config exists: `docker-compose.prod.yml`.
- Dockerfiles exist for backend and frontend.
- Oracle Cloud deployment docs exist in `docs/DEPLOY_ORACLE.md`.
- Local SQLite backup script exists in `backend/scripts/backup_sqlite.sh`.

## Findings

### Finding P4-1: No CI workflow is checked in

- Severity: High
- Repository: root / all units
- File/path: `.github/workflows` absent, `backend/pyproject.toml`, `frontend/package.json`
- Evidence from the code:
  - `backend/pyproject.toml:1-14` configures pytest and ruff.
  - `frontend/package.json:8-12` exposes build, typecheck, and test scripts.
  - No project `.github/workflows` directory was present.
- Why it matters: The project has tests and lint/typecheck hooks, but nothing enforces them on pull requests or deployment changes. Contract drift like the evaluation summary mismatch can land unnoticed.
- Suggested fix: Add CI that runs backend tests, frontend typecheck, frontend tests, frontend build, dependency/audit checks, and Docker build checks.
- Estimated effort: Medium
- Fix immediately or later: Immediately

### Finding P4-2: Security tests do not cover the fail-open token state

- Severity: High
- Repository: `backend`
- File/path: `backend/tests/test_security.py`, `backend/app/api/routes/admin.py`, `backend/app/api/routes/pipelines.py`, `backend/app/api/routes/ml.py`
- Evidence from the code:
  - `backend/tests/test_security.py:32-34` forces `ADMIN_TOKEN="supersecret"` before auth tests.
  - `backend/app/api/routes/admin.py:18-21`, `backend/app/api/routes/pipelines.py:24-25`, and `backend/app/api/routes/ml.py:23-24` allow access when `ADMIN_TOKEN` is empty.
- Why it matters: Tests prove rejection only when a token is set. They do not catch the highest-risk production misconfiguration.
- Suggested fix: Add tests for `ENVIRONMENT=production` with empty and placeholder `ADMIN_TOKEN`, and assert startup failure or route rejection. Add tests for ML and all pipeline admin routes.
- Estimated effort: Low
- Fix immediately or later: Immediately

### Finding P4-3: Frontend tests mock an API contract that differs from the backend

- Severity: High
- Repository: `frontend`, `backend`
- File/path: `frontend/src/tests/Models.test.tsx`, `frontend/src/tests/Dashboard.test.tsx`, `backend/app/db/repositories/evaluations.py`
- Evidence from the code:
  - Frontend tests use mocked rows with `brier_score`, `log_loss`, `rps`, `accuracy`, and `total_predictions`.
  - Backend summary returns aggregate fields such as `avg_brier` and `n_evaluations`.
- Why it matters: The UI tests pass even though real backend data will not satisfy the mocked shape. This hides user-visible bugs.
- Suggested fix: Add a small contract fixture generated from the backend route, or define a shared OpenAPI/type generation step. Update frontend tests to use real response shapes.
- Estimated effort: Medium
- Fix immediately or later: Immediately

### Finding P4-4: Public mutation routes lack tests for authorization/rate limiting

- Severity: Medium
- Repository: `backend`
- File/path: `backend/tests/test_health.py`, `backend/tests/test_scheduler.py`, `backend/tests/test_security.py`, route files
- Evidence from the code:
  - `backend/tests/test_health.py:32` calls `/api/jobs/ping`.
  - `backend/tests/test_scheduler.py:241-246` creates manual snapshots.
  - There are no tests asserting these write/enqueue routes require auth.
- Why it matters: A future change could expand public mutation behavior without failing tests. Current tests normalize unauthenticated write routes.
- Suggested fix: Add authorization and rate-limit tests for `/api/simulations/run`, `/api/jobs/ping`, `/api/snapshots/{run_id}`, `/api/ml/train`, and every pipeline/admin endpoint.
- Estimated effort: Low to Medium
- Fix immediately or later: Immediately with auth changes

### Finding P4-5: Docker build/deploy hardening is not tested

- Severity: Medium
- Repository: `docker`
- File/path: `docker/Dockerfile.backend`, `docker/Dockerfile.frontend`, `docker/nginx.prod.conf`, `frontend/nginx.conf`
- Evidence from the code:
  - `docker/Dockerfile.frontend:15` copies `frontend/nginx.conf`.
  - `docker/nginx.prod.conf:5-13` contains security headers that the image does not use.
  - Dockerfiles do not set explicit non-root users.
- Why it matters: Deployment config drift can silently ship less hardened images.
- Suggested fix: Add CI checks that build both images and inspect the effective nginx config. Add container lint/scanning.
- Estimated effort: Medium
- Fix immediately or later: Later, but before public production use

### Finding P4-6: No automated dependency or container vulnerability scanning is present

- Severity: Medium
- Repository: `backend`, `frontend`, `docker`
- File/path: `backend/requirements.txt`, `frontend/package-lock.json`, Dockerfiles
- Evidence from the code:
  - Python dependencies are broad ranges in `backend/requirements.txt`.
  - Frontend lockfile exists but no audit script is defined in `frontend/package.json`.
  - No CI workflow was found to run audits or image scans.
- Why it matters: The stack includes web framework, HTTP clients, HTML parsing, ML libraries, Redis/RQ, and Nginx. Vulnerable transitive dependencies can enter unnoticed.
- Suggested fix: Add `pip-audit` or equivalent for Python, `npm audit`/Dependabot for frontend, and container scanning such as Trivy/Grype in CI.
- Estimated effort: Medium
- Fix immediately or later: Later

### Finding P4-7: Backups are local-only and prune automatically

- Severity: Medium
- Repository: `backend`, `docs`
- File/path: `backend/scripts/backup_sqlite.sh`, `docs/DEPLOY_ORACLE.md`, `.gitignore`
- Evidence from the code:
  - `backend/scripts/backup_sqlite.sh:11-15` stores backups under `data/backups` and keeps `MAX_BACKUPS=7`.
  - `backend/scripts/backup_sqlite.sh:40-43` deletes older backup files.
  - `docs/DEPLOY_ORACLE.md:145-155` documents local cron backups.
  - `.gitignore:46` excludes `data/backups`.
- Why it matters: Local backups do not protect against VM loss, disk failure, account compromise, or accidental deletion beyond seven retained files.
- Suggested fix: Sync encrypted backups to Object Storage/S3/R2, test restore procedures, and monitor backup age/size.
- Estimated effort: Medium
- Fix immediately or later: Later, before production data matters

### Finding P4-8: Tests can mutate tracked seed data during collection

- Severity: Low
- Repository: `backend`, `data`
- File/path: `backend/tests/conftest.py`, `data/raw/generate_historical.py`
- Evidence from the code:
  - `backend/tests/conftest.py:29-36` generates `data/raw/historical_results.csv` if missing or too small.
  - `data/raw/generate_historical.py` writes to `data/raw/historical_results.csv`.
- Why it matters: Test collection can modify a tracked seed file, causing dirty working trees and hiding fixture/data drift.
- Suggested fix: Generate test data into a temp directory or require the fixture file to be committed and fail if missing.
- Estimated effort: Low
- Fix immediately or later: Later

## Recommended CI Pipeline

1. Backend lint/static: `ruff check backend/app backend/tests`
2. Backend tests: `pytest`
3. Frontend typecheck: `npm run typecheck`
4. Frontend tests: `npm run test:run`
5. Frontend build: `npm run build`
6. Contract check: assert `/api/evaluations/summary` shape matches frontend types
7. Dependency scans: Python and npm
8. Docker build and nginx config assertion

## Phase 4 Summary

The project has meaningful local test coverage, especially backend domain logic. The highest gaps are automation and contract/security coverage: no CI, no fail-open auth tests, no backend-to-frontend contract test, and no automated dependency/container scanning.
