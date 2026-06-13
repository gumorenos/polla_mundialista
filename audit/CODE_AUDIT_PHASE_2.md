# Code Audit Phase 2 - Backend, APIs, Authentication

Audit date: 2026-06-13
Audit mode: read-only inspection; tests were not run.

## Backend Surface Reviewed

Reviewed:

- FastAPI app setup and middleware: `backend/app/main.py`
- Admin, pipeline, simulation, ML, jobs, snapshots, metrics, evaluation, health routes
- Worker task entry points and job orchestration
- SQLite repositories and migration shape
- CSV/API/ELO/news/LLM ingestion paths
- Monte Carlo simulation and ML model load paths

Not fully reviewed:

- Every row/field in seed CSVs and calibration JSON exports
- Runtime behavior under real Redis/API-Football/OpenRouter dependencies
- Dependency vulnerability state, because scanners were not run

## Findings

### Finding P2-1: Admin/pipeline/ML auth fails open when the token is unset

- Severity: Critical
- Repository: `backend`
- File/path: `backend/app/api/routes/admin.py`, `backend/app/api/routes/pipelines.py`, `backend/app/api/routes/ml.py`, `backend/app/core/config.py`
- Evidence from the code:
  - `backend/app/core/config.py:91` sets `ADMIN_TOKEN: str = ""`.
  - `backend/app/api/routes/admin.py:18-21` logs and returns if `ADMIN_TOKEN` is empty.
  - `backend/app/api/routes/pipelines.py:24-25` returns if `ADMIN_TOKEN` is empty.
  - `backend/app/api/routes/ml.py:23-24` returns if `ADMIN_TOKEN` is empty.
- Why it matters: These endpoints enqueue ingestion, full refresh, daily update, all-model simulation, news refresh, and ML training jobs. Missing env configuration turns privileged mutation routes into public endpoints.
- Suggested fix: Make missing admin token a startup error in production. Consider a shared dependency that always rejects admin routes unless a valid token is configured and supplied.
- Estimated effort: Low
- Fix immediately or later: Immediately

### Finding P2-2: Expensive write/enqueue endpoints are public

- Severity: High
- Repository: `backend`
- File/path: `backend/app/api/routes/simulations.py`, `backend/app/api/routes/health.py`, `backend/app/api/routes/snapshots.py`
- Evidence from the code:
  - `backend/app/api/routes/simulations.py:33-54` exposes `POST /api/simulations/run` without auth and enqueues RQ work.
  - `backend/app/api/routes/simulations.py:26` allows up to `100_000` iterations per request.
  - `backend/app/api/routes/health.py:18-23` exposes `GET /api/jobs/ping` and enqueues a job.
  - `backend/app/api/routes/snapshots.py:42-46` exposes manual snapshot creation with caller-controlled `label` and `description`.
- Why it matters: Any user who can reach the API can create persistent rows and queue CPU-heavy jobs. Even with public rate limiting, the default `60/minute` is too high for expensive Monte Carlo work.
- Suggested fix: Require admin auth for job-enqueueing and snapshot-create endpoints, or introduce scoped write tokens and low route-specific rate limits. Keep read-only prediction endpoints public.
- Estimated effort: Low to Medium
- Fix immediately or later: Immediately

### Finding P2-3: Frontend cannot call protected pipeline endpoints when auth is configured

- Severity: High
- Repository: `frontend`, `backend`
- File/path: `frontend/src/api/client.ts`, `frontend/src/api/hooks/index.ts`, `backend/app/api/routes/pipelines.py`
- Evidence from the code:
  - `frontend/src/api/client.ts:13-21` sets only `Content-Type` plus caller-provided headers.
  - `frontend/src/api/hooks/index.ts:88` posts to `/api/pipelines/full-refresh` without `X-Admin-Token`.
  - `frontend/src/api/hooks/index.ts:96` posts to `/api/pipelines/daily-update` without `X-Admin-Token`.
  - `backend/app/api/routes/pipelines.py:26-30` rejects missing/wrong tokens when `ADMIN_TOKEN` is set.
- Why it matters: The dashboard's primary operational actions fail in a correctly protected deployment. The likely workaround is dangerous: leaving `ADMIN_TOKEN` empty.
- Suggested fix: Add an explicit admin/operator auth design. Options include a server-side session, reverse-proxy auth, an operator-only UI route, or a local-only admin token entry that is never persisted.
- Estimated effort: Medium
- Fix immediately or later: Immediately before using the UI for operations

### Finding P2-4: `run-all-models` creates orphan job rows

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/api/routes/pipelines.py`
- Evidence from the code:
  - `backend/app/api/routes/pipelines.py:125-131` loops over `_ALL_MODELS` and creates jobs, but the created `job_id` values are not used.
  - `backend/app/api/routes/pipelines.py:134-151` loops again, creates a second job per model, and enqueues those jobs.
- Why it matters: Every call creates five extra `jobs` rows stuck in `enqueued` state. This pollutes monitoring, inflates running counts, and makes operational triage harder.
- Suggested fix: Remove the first unused loop. Create one job row per model, enqueue it, then update `result_ref`.
- Estimated effort: Low
- Fix immediately or later: Later, but before heavy production use

### Finding P2-5: DB-loaded group composition is silently bypassed

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/db/migrations.py`, `backend/app/services/ingestion/csv_loader.py`, `backend/app/services/simulation/monte_carlo.py`
- Evidence from the code:
  - `backend/app/db/migrations.py:59` creates `group_teams` without a `position` column.
  - `backend/app/services/ingestion/csv_loader.py:137` inserts only `(group_id, team_id)` into `group_teams`.
  - `backend/app/services/simulation/monte_carlo.py:215-216` orders by `gt.position`, catches errors, and falls back to hard-coded `GROUPS_2026`.
- Why it matters: Updating groups in CSV/database does not reliably affect simulations. The fallback masks the schema bug, so operators may believe current DB data is being used when it is not.
- Suggested fix: Add a `position` column or remove the order by `gt.position`. Add a test that seeds DB groups and asserts `_load_groups` returns DB values rather than constants.
- Estimated effort: Low to Medium
- Fix immediately or later: Later, before using final 2026 groups

### Finding P2-6: Evaluation summary API contract does not match the frontend contract

- Severity: High
- Repository: `backend`, `frontend`
- File/path: `backend/app/db/repositories/evaluations.py`, `backend/app/api/routes/evaluations.py`, `frontend/src/types/index.ts`, `frontend/src/pages/*.tsx`
- Evidence from the code:
  - `backend/app/db/repositories/evaluations.py:59-64` returns `n_evaluations`, `avg_brier`, `avg_log_loss`, `avg_rps`, and `avg_accuracy`.
  - `backend/app/api/routes/evaluations.py:35` returns that aggregate directly.
  - `frontend/src/types/index.ts:30-34` expects `brier_score`, `log_loss`, `rps`, `accuracy`, and `total_predictions`.
  - `frontend/src/pages/Dashboard.tsx:29-30` sorts by `brier_score`.
  - `frontend/src/pages/Models.tsx:24-43` renders fields that the backend does not return.
- Why it matters: Model comparison, best-model selection, dashboard metrics, and calibration summary can display blanks or sort incorrectly against real backend data.
- Suggested fix: Normalize the backend response shape or update the frontend types/pages to consume the backend's aggregate field names. Add integration/contract tests that call the real route and render the real response.
- Estimated effort: Low to Medium
- Fix immediately or later: Immediately

### Finding P2-7: Route-specific admin rate limiting is missing

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/main.py`, `backend/app/core/config.py`, admin/pipeline/simulation routes
- Evidence from the code:
  - `backend/app/core/config.py:133-134` defines both public and admin rate limits.
  - `backend/app/main.py:43-44` applies only `settings.RATE_LIMIT_PUBLIC` as a default.
  - Admin and job routes have no route-specific `RATE_LIMIT_ADMIN` decorator.
- Why it matters: Expensive write routes share the public default limit and do not get stricter controls.
- Suggested fix: Apply route-level limits using the configured admin limit. Use lower limits for full refresh, ML training, and simulation enqueue routes.
- Estimated effort: Low
- Fix immediately or later: Immediately with auth changes

### Finding P2-8: RQ task failure handling can leave jobs stuck in nonterminal states

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/workers/tasks.py`, `backend/app/services/simulation/monte_carlo.py`
- Evidence from the code:
  - `backend/app/workers/tasks.py:73-104` updates simulation job status to `running`, then calls `run_monte_carlo`; exceptions outside the inner `run_monte_carlo` failure path can propagate without updating the job row to `failed`.
  - `backend/app/services/simulation/monte_carlo.py:187-204` raises `ValueError` for unknown `model_name` before creating a simulation run.
  - `backend/app/api/routes/simulations.py:24-26` accepts any `model_name` string.
- Why it matters: Invalid or unexpected jobs can remain `running` or `enqueued`, making monitoring inaccurate and confusing retry/cleanup decisions.
- Suggested fix: Validate `model_name` at request boundaries and wrap RQ task bodies in final exception handlers that mark job rows `failed`.
- Estimated effort: Low
- Fix immediately or later: Later

### Finding P2-9: LLM classification is prompt-injection resistant only by output validation, not by stronger source isolation

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/services/news/llm_classifier.py`, `backend/app/services/news/availability.py`, `backend/app/services/news/scraper.py`
- Evidence from the code:
  - `backend/app/services/news/llm_classifier.py:95-109` inserts untrusted `article_text` into a user prompt.
  - `backend/app/services/news/llm_classifier.py:100-107` asks for JSON and `backend/app/services/news/llm_classifier.py:141-151` validates JSON.
  - `backend/app/services/news/availability.py:123-141` persists the classification and can mark injuries as affecting predictions.
- Why it matters: A hostile or low-quality article can instruct the LLM to misclassify. Validation prevents malformed output, but it does not guarantee factual grounding or instruction isolation.
- Suggested fix: Delimit article text explicitly, require quoted evidence snippets or source facts in the schema, cross-check with source/domain rules, and never let a single LLM output affect predictions without independent source thresholds.
- Estimated effort: Medium
- Fix immediately or later: Later, before relying on automated injury adjustments

### Finding P2-10: `joblib.load` is safe only while the model path remains fully trusted

- Severity: Medium
- Repository: `backend`
- File/path: `backend/app/services/prediction/ml_calibrated.py`, `backend/app/db/repositories/ml.py`
- Evidence from the code:
  - `backend/app/services/prediction/ml_calibrated.py:103-110` loads `model_path` from the DB with `joblib.load`.
  - `backend/app/db/repositories/ml.py:40-58` persists model paths from training output.
- Why it matters: `joblib.load` can execute code when loading malicious serialized content. The current path is server-generated, but if the DB or model directory is writable by an attacker, model loading becomes a code-execution primitive.
- Suggested fix: Keep model storage non-public, validate model paths stay under `settings.ML_MODELS_PATH`, avoid loading arbitrary paths from DB, and restrict permissions on model volumes.
- Estimated effort: Low to Medium
- Fix immediately or later: Later, as defense in depth

## Positive Notes

- SQL uses parameterized queries in reviewed repository methods and routes.
- No application path using `os.system`, `shell=True`, or runtime `eval`/`exec` was found in source.
- External HTTP clients use timeouts.
- LLM output is schema-validated and failures degrade to `UNRELATED`.
- CSV ingestion performs basic validation for goals and dates.

## Phase 2 Summary

Backend implementation is functional and generally straightforward, but the auth model is the top risk. Fix fail-open admin auth, protect public enqueue/write endpoints, and align backend/frontend API contracts before exposing the app beyond a trusted environment.
