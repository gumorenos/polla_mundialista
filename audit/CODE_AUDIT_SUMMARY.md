# Code Audit Summary - Oraculo Mundial 2026

Audit date: 2026-06-13
Repository root: `D:\projects\claude\polla_mundialista`
Audit mode: read-only inspection plus markdown report creation. No application/source code was modified. No tests, package installs, commits, pushes, branch changes, or destructive commands were run.

## 1. Executive Summary

Oraculo Mundial 2026 is a coherent MVP for World Cup prediction: FastAPI backend, SQLite WAL persistence, Redis/RQ workers, APScheduler, statistical/ML models, OpenRouter-assisted injury extraction, and a React/Vite dashboard.

Overall quality score: 6/10.

The biggest issue is not model code quality; it is production hardening. Admin auth fails open when `ADMIN_TOKEN` is missing, several expensive mutation/enqueue endpoints are public, and the frontend has no way to supply admin credentials to protected pipeline endpoints. There is also a real backend/frontend API contract mismatch around model metrics that will break dashboard/model displays with real backend data.

No committed live secrets were found in the inspected source. No n8n integrations, AI-agent execution permissions, unsafe shell execution in application request paths, or client-side token storage were found. The LLM integration is limited to injury classification, but untrusted article text can still influence prediction adjustments through prompt-level manipulation if source validation is weak.

## 2. Repository Ranking

### Most Urgent Attention

| Rank | Repository | Reason |
|---|---|---|
| 1 | `backend` | Fail-open auth, public enqueue/write endpoints, expensive job execution, data correctness bugs |
| 2 | `frontend` | Cannot authenticate admin actions; model metrics contract mismatch |
| 3 | `docker` | Effective frontend image misses hardened nginx config; root/reproducibility hardening gaps |
| 4 | `docs` | Deployment docs mention safe setup but cannot enforce it |
| 5 | `data` | Mostly seed data; lower direct risk |

### Biggest Security Risk

| Rank | Repository | Reason |
|---|---|---|
| 1 | `backend` | Public mutation/job surfaces and fail-open admin token behavior |
| 2 | `docker` | Deployment hardening drift and root container posture |
| 3 | `frontend` | Operational auth gap can lead to unsafe backend configuration |
| 4 | `data` | Model/job artifacts need permission protection, but checked-in seed data is low risk |
| 5 | `docs` | Documentation cannot enforce runtime controls |

### Highest Improvement Potential

| Rank | Repository | Reason |
|---|---|---|
| 1 | `backend` | Small auth/validation fixes would remove most critical risk |
| 2 | `frontend` | Contract/auth fixes would make the UI production-usable |
| 3 | `docker` | Low-effort nginx and non-root/reproducible build improvements |
| 4 | `docs` | Can clarify operator-safe deployment and restore procedures |
| 5 | `data` | Improve test fixture generation and final group data process |

## 3. Critical Findings

### Finding C-1: Admin token protection fails open

- Severity: Critical
- Repository: `backend`
- File/path: `backend/app/core/config.py:91`, `backend/app/api/routes/admin.py:18-21`, `backend/app/api/routes/pipelines.py:24-25`, `backend/app/api/routes/ml.py:23-24`
- Evidence from the code: `ADMIN_TOKEN` defaults to `""`; route auth helpers return without rejecting if the token is empty.
- Why it matters: Missing production config makes privileged admin, pipeline, and ML actions public.
- Suggested fix: Fail closed in production. Reject startup with missing/placeholder `ADMIN_TOKEN`; use a shared auth dependency.
- Estimated effort: Low
- Fix immediately or later: Immediately

## 4. High-Priority Findings

### Finding H-1: Expensive write/enqueue endpoints are public

- Severity: High
- Repository: `backend`
- File/path: `backend/app/api/routes/simulations.py:33-54`, `backend/app/api/routes/health.py:18-23`, `backend/app/api/routes/snapshots.py:42-46`
- Evidence from the code: Public routes enqueue Monte Carlo runs, ping jobs, and manual snapshots. Simulations accept up to `100_000` iterations.
- Why it matters: Public users can generate persistent DB rows and CPU-heavy RQ work.
- Suggested fix: Require auth for enqueue/write routes and apply strict route-specific limits.
- Estimated effort: Low to Medium
- Fix immediately or later: Immediately

### Finding H-2: Frontend cannot authenticate protected pipeline actions

- Severity: High
- Repository: `frontend`
- File/path: `frontend/src/api/client.ts:13-21`, `frontend/src/api/hooks/index.ts:88`, `frontend/src/api/hooks/index.ts:96`
- Evidence from the code: Pipeline mutations send no `X-Admin-Token`, while backend rejects missing token when configured.
- Why it matters: The operator dashboard either fails in production or incentivizes unsafe empty-token deployment.
- Suggested fix: Add a real operator auth flow; do not store long-lived admin tokens in browser storage.
- Estimated effort: Medium
- Fix immediately or later: Immediately

### Finding H-3: Model metrics API contract is broken between backend and frontend

- Severity: High
- Repository: `backend`, `frontend`
- File/path: `backend/app/db/repositories/evaluations.py:59-64`, `backend/app/api/routes/evaluations.py:35`, `frontend/src/types/index.ts:30-34`, `frontend/src/pages/Dashboard.tsx:29-30`, `frontend/src/pages/Models.tsx:24-43`
- Evidence from the code: Backend returns `avg_brier`, `avg_log_loss`, and `n_evaluations`; frontend expects `brier_score`, `log_loss`, and `total_predictions`.
- Why it matters: Model comparison and dashboard best-model UI can be wrong or blank against real data.
- Suggested fix: Align backend response shape or frontend types, then add contract tests.
- Estimated effort: Low to Medium
- Fix immediately or later: Immediately

### Finding H-4: No CI workflow is checked in

- Severity: High
- Repository: all
- File/path: `.github/workflows` absent; test scripts exist in `backend/pyproject.toml` and `frontend/package.json`
- Evidence from the code: Local test/lint/typecheck configs exist, but no project workflow directory is present.
- Why it matters: Security and contract regressions are not automatically blocked.
- Suggested fix: Add CI for backend tests/lint, frontend typecheck/tests/build, contract checks, dependency scans, and Docker builds.
- Estimated effort: Medium
- Fix immediately or later: Immediately

## 5. Medium-Priority Findings

### Finding M-1: Admin-specific rate limit is configured but unused

- Severity: Medium
- Repository: `backend`
- File/path: `.env.example:51-52`, `backend/app/core/config.py:133-134`, `backend/app/main.py:43-44`
- Evidence from the code: `RATE_LIMIT_ADMIN` exists but only `RATE_LIMIT_PUBLIC` is applied as a default limit.
- Why it matters: Expensive privileged endpoints do not get stricter throttling.
- Suggested fix: Add route-specific limits to admin, pipeline, ML, simulation enqueue, snapshot-create, and ping routes.
- Estimated effort: Low
- Fix immediately or later: Immediately with auth fixes

### Finding M-2: `run-all-models` creates orphan job rows

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/api/routes/pipelines.py:125-151`
- Evidence from the code: The route creates one set of jobs in an unused loop, then creates and enqueues a second set.
- Why it matters: Monitoring and job counts become polluted with rows that never run.
- Suggested fix: Remove the first loop.
- Estimated effort: Low
- Fix immediately or later: Later

### Finding M-3: DB group data is bypassed because code orders by a missing column

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/db/migrations.py:59`, `backend/app/services/ingestion/csv_loader.py:137`, `backend/app/services/simulation/monte_carlo.py:215-216`
- Evidence from the code: `group_teams` has no `position`; loader inserts only `group_id/team_id`; simulation orders by `gt.position` and falls back to constants.
- Why it matters: CSV/DB group changes may not affect simulations.
- Suggested fix: Add position support or remove that ordering; add a DB-backed group loading test.
- Estimated effort: Low to Medium
- Fix immediately or later: Later before final tournament data

### Finding M-4: Production frontend image ignores hardened nginx config

- Severity: Medium
- Repository: `docker`
- File/path: `docker/Dockerfile.frontend:15`, `frontend/nginx.conf`, `docker/nginx.prod.conf:5-13`
- Evidence from the code: Dockerfile copies `frontend/nginx.conf`; hardened headers live in `docker/nginx.prod.conf`.
- Why it matters: Intended security headers are not in the deployed image.
- Suggested fix: Use the hardened config in the image or harden the frontend config directly.
- Estimated effort: Low
- Fix immediately or later: Before public deployment

### Finding M-5: Scheduler is embedded in the API process

- Severity: Medium
- Repository: `backend`, `docker`
- File/path: `backend/app/main.py:32-36`, `backend/app/core/config.py:139`, `docker-compose.prod.yml:46`
- Evidence from the code: API starts APScheduler during lifespan; production API has `SCHEDULER_ENABLED=true`.
- Why it matters: Scaling API replicas can duplicate scheduled jobs.
- Suggested fix: Run one dedicated scheduler service and disable scheduler in API containers.
- Estimated effort: Medium
- Fix immediately or later: Later unless scaling API

### Finding M-6: Dependency/build reproducibility and container hardening gaps

- Severity: Medium
- Repository: `backend`, `frontend`, `docker`
- File/path: `backend/requirements.txt`, `docker/Dockerfile.backend:10`, `docker/Dockerfile.frontend:6`
- Evidence from the code: Python requirements use broad ranges; frontend Docker build uses `npm install --legacy-peer-deps`; Dockerfiles do not define non-root runtime users.
- Why it matters: Builds can drift and container compromise impact is higher.
- Suggested fix: Pin/lock dependencies, use `npm ci`, add non-root users, and scan images.
- Estimated effort: Medium
- Fix immediately or later: Later

### Finding M-7: LLM injury classification can be influenced by untrusted article text

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/services/news/llm_classifier.py:95-109`, `backend/app/services/news/availability.py:123-141`
- Evidence from the code: Article text is inserted into the LLM prompt; validated output can affect prediction adjustments.
- Why it matters: Prompt injection or low-quality sources can alter model context.
- Suggested fix: Delimit untrusted content, require evidence snippets/source facts, and keep multi-source confidence thresholds.
- Estimated effort: Medium
- Fix immediately or later: Later

### Finding M-8: Local-only backups are not enough for production recovery

- Severity: Medium
- Repository: `backend`, `docs`
- File/path: `backend/scripts/backup_sqlite.sh:11-15`, `backend/scripts/backup_sqlite.sh:40-43`, `docs/DEPLOY_ORACLE.md:145-155`
- Evidence from the code: Backups are local under `data/backups` and old backups are pruned.
- Why it matters: VM/disk/account loss can remove both primary DB and backups.
- Suggested fix: Sync encrypted backups to external object storage and test restore.
- Estimated effort: Medium
- Fix immediately or later: Later before production data matters

## 6. Main Risks

- Public unauthenticated job creation and persistent writes
- Production misconfiguration due to fail-open secret handling
- Operational UI unusable with secure auth enabled
- Contract drift between backend and frontend
- Lack of CI gates for tests, type checks, contracts, dependencies, and Docker
- SQLite/job queue saturation under public traffic
- LLM trust quality affecting predictions

## 7. Security Concerns

- No committed live secrets found; only placeholders in `.env.example`.
- Admin token handling must fail closed.
- Public write/enqueue routes should be authenticated.
- `joblib.load` should only load trusted model paths under trusted permissions.
- No n8n integrations or AI-agent execution permission surfaces were found.
- No application request-path shell execution (`os.system`, `shell=True`) was found.
- No client-side token storage or raw HTML rendering was found.

## 8. Technical Debt

- Scheduler lifecycle coupled to API process
- SQLite MVP architecture may need PostgreSQL if traffic/concurrency grows
- Broad Python dependency ranges and non-reproducible Docker frontend install
- Backend/frontend contract not generated or enforced
- Tests can generate tracked seed data during collection
- Local-only backup strategy
- Existing docs contain status claims that are now stale relative to findings

## 9. Suggested Roadmap of Fixes

1. Fail closed for `ADMIN_TOKEN` in production and add tests for missing/placeholder tokens.
2. Require auth and strict route limits for all job-enqueue/write endpoints.
3. Add a real operator auth path for the dashboard.
4. Align `/api/evaluations/summary` response with frontend types and add contract tests.
5. Remove orphan job creation in `run-all-models`.
6. Fix DB-backed group loading and add a regression test.
7. Add CI for backend, frontend, contract, dependency, and Docker checks.
8. Use the hardened nginx config in the production frontend image.
9. Improve dependency locking, Docker non-root users, and image scanning.
10. Add off-host encrypted backups and restore verification.

## 10. Recommended Next Actions

- Do not expose this service publicly until C-1, H-1, H-2, H-3, and H-4 are addressed.
- Run the backend and frontend test suites after fixing the auth and contract issues.
- Run dependency/container vulnerability scans before production deployment.
- Add a small smoke test that builds the Docker images and confirms the effective nginx headers.
- Add operational documentation for the final admin/auth model.

## Per-Repository Scores

| Repository | Quality score | Main risks | Recommended next action |
|---|---:|---|---|
| `backend` | 6/10 | Fail-open auth, public expensive writes, job/data correctness bugs | Fix auth/rate limits/contract first |
| `frontend` | 6/10 | No admin auth flow, API contract mismatch | Add operator auth and real contract tests |
| `docker` | 5/10 | Hardened config unused, reproducibility/non-root gaps | Use production nginx config and harden images |
| `data` | 7/10 | Generated/test data drift, final groups not authoritative | Make fixture generation temp-only; finalize group process |
| `docs` | 7/10 | Docs describe desired controls but app does not enforce them | Update after auth/deploy hardening |

Overall quality score: 6/10.
