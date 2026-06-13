# Code Audit Phase 3 - Frontend, State Management, UI Logic

Audit date: 2026-06-13
Audit mode: read-only inspection; frontend tests were not run.

## Frontend Surface Reviewed

Reviewed:

- API client and React Query hooks
- Pages: Dashboard, Models, Simulations, Calibration, Snapshots, Jobs
- App routing and layout
- TypeScript domain types
- Vitest page tests and jsdom setup

## Architecture and State Management

The frontend is a small Vite/React SPA. It uses:

- `fetch` wrapper in `frontend/src/api/client.ts`
- TanStack Query for server state and polling in `frontend/src/api/hooks/index.ts`
- React local state for selected model controls
- React Router for page navigation
- Recharts for calibration charts

There is no client-side authentication/session state, no token storage, and no raw HTML rendering in the reviewed source.

## Findings

### Finding P3-1: Frontend cannot authenticate admin mutations

- Severity: High
- Repository: `frontend`
- File/path: `frontend/src/api/client.ts`, `frontend/src/api/hooks/index.ts`, `frontend/src/pages/Dashboard.tsx`
- Evidence from the code:
  - `frontend/src/api/client.ts:13-21` sends only JSON headers unless callers pass headers.
  - `frontend/src/api/hooks/index.ts:88` posts to `/api/pipelines/full-refresh` with no admin token.
  - `frontend/src/api/hooks/index.ts:96` posts to `/api/pipelines/daily-update` with no admin token.
  - `frontend/src/pages/Dashboard.tsx:39-58` exposes Full Refresh and Daily Update buttons.
- Why it matters: In a correctly configured production backend, these UI controls return 403. If operators remove `ADMIN_TOKEN` to make them work, privileged backend actions become public.
- Suggested fix: Define an operator auth flow. Do not store long-lived admin secrets in localStorage. Prefer reverse-proxy auth, a short-lived session cookie, or an admin-only backend session endpoint.
- Estimated effort: Medium
- Fix immediately or later: Immediately

### Finding P3-2: Frontend uses the wrong model metrics response shape

- Severity: High
- Repository: `frontend`, `backend`
- File/path: `frontend/src/types/index.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Models.tsx`, `frontend/src/pages/Calibration.tsx`, `backend/app/db/repositories/evaluations.py`
- Evidence from the code:
  - `frontend/src/types/index.ts:30-34` defines `ModelMetrics` with `brier_score`, `log_loss`, `rps`, `accuracy`, and `total_predictions`.
  - `frontend/src/pages/Dashboard.tsx:29-30` sorts by `brier_score`.
  - `frontend/src/pages/Models.tsx:24-43` renders those same fields.
  - `frontend/src/pages/Calibration.tsx:50-53` reads those same fields.
  - `backend/app/db/repositories/evaluations.py:59-64` returns aggregate names such as `avg_brier`, `avg_log_loss`, and `n_evaluations`.
- Why it matters: Against real backend data, dashboard/model/calibration metric UI can render blanks, mis-sort models, or display misleading summaries. Current tests mock the frontend's expected shape instead of the backend's actual shape.
- Suggested fix: Either change backend `/api/evaluations/summary` to return the frontend contract, or update frontend types/pages to use backend aggregate fields. Add a contract test using the actual route response.
- Estimated effort: Low to Medium
- Fix immediately or later: Immediately

### Finding P3-3: Public UI can trigger expensive simulations

- Severity: High
- Repository: `frontend`, `backend`
- File/path: `frontend/src/pages/Simulations.tsx`, `frontend/src/api/hooks/index.ts`, `backend/app/api/routes/simulations.py`
- Evidence from the code:
  - `frontend/src/pages/Simulations.tsx:57-59` calls `runSim.mutate({ model_name: model })`.
  - `frontend/src/api/hooks/index.ts:80` posts to `/api/simulations/run`.
  - `backend/app/api/routes/simulations.py:33-54` enqueues the simulation without auth.
- Why it matters: The UI exposes a direct path to server-side CPU work and durable job rows. On a public deployment, casual or automated users can generate costly workloads.
- Suggested fix: Make simulation enqueue an authenticated/admin action, or add a public-safe request queue with low limits, deduplication, and max one running job per model.
- Estimated effort: Low to Medium
- Fix immediately or later: Immediately

### Finding P3-4: Dashboard mutates React Query cache data in place

- Severity: Low
- Repository: `frontend`
- File/path: `frontend/src/pages/Dashboard.tsx`
- Evidence from the code:
  - `frontend/src/pages/Dashboard.tsx:29-31` calls `metrics?.sort(...)`, which mutates the array returned by React Query.
  - `frontend/src/pages/Dashboard.tsx:33-35` correctly copies simulation rows before sorting with `(sim?.team_results ?? []).sort(...)` not copied; this also mutates the array returned by the query.
- Why it matters: Mutating cached server state can cause unexpected ordering changes across components and rerenders.
- Suggested fix: Use `[...(metrics ?? [])].sort(...)` and `[...(sim?.team_results ?? [])].sort(...)`.
- Estimated effort: Low
- Fix immediately or later: Later

### Finding P3-5: TypeScript types disagree with backend string IDs

- Severity: Low
- Repository: `frontend`
- File/path: `frontend/src/types/index.ts`, backend repositories/responses
- Evidence from the code:
  - `frontend/src/types/index.ts:53-57` declares `TeamResult.team_id: number`.
  - Backend team IDs are strings throughout migrations, repositories, and seed data, for example `simulation_team_results.team_id` references text team IDs.
  - Frontend tests also mock numeric IDs (`frontend/src/tests/Dashboard.test.tsx:14-15`), hiding the mismatch.
- Why it matters: Type drift weakens TypeScript value and can cause incorrect key assumptions or formatting bugs when real IDs are strings like `BRA` or team names.
- Suggested fix: Change frontend ID types to `string` where backend returns string IDs and update mocks accordingly.
- Estimated effort: Low
- Fix immediately or later: Later

### Finding P3-6: Error handling hides backend detail from operators

- Severity: Low
- Repository: `frontend`
- File/path: `frontend/src/api/client.ts`, pages using mutations
- Evidence from the code:
  - `frontend/src/api/client.ts:23-25` throws only `${status} ${statusText}` and discards JSON error bodies.
  - Dashboard mutation buttons do not render failure details for 403/429/500 responses.
- Why it matters: Operational users cannot distinguish missing admin token, rate limit, Redis failure, or validation errors from the UI.
- Suggested fix: Parse JSON error bodies when present, expose concise mutation errors near action buttons, and map 403/429 to actionable operator messages.
- Estimated effort: Low
- Fix immediately or later: Later

## Positive Notes

- No localStorage/sessionStorage token usage was found.
- No `dangerouslySetInnerHTML` or raw `innerHTML` usage was found.
- React Query polling intervals are constrained to jobs/status surfaces.
- Pages are simple and easy to reason about.

## Phase 3 Summary

The frontend is maintainable but currently out of contract with the backend and lacks an admin authentication story. Fixing API shape alignment and operator auth will address the most important UI risks.
