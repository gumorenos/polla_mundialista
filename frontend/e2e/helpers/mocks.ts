/**
 * API mock helpers for Playwright E2E tests.
 *
 * IMPORTANT: Playwright matches routes in LIFO order (last registered = first matched).
 * Always call mockAllApiStubs() FIRST, then specific mocks afterwards so specific
 * mocks take priority over the catch-all stub.
 */
import type { Page } from '@playwright/test'

const TEAM_RESULTS = [
  {
    team_id: 'ESP', team_name: 'España', win_tournament: 0.18, reach_final: 0.31,
    reach_semi_final: 0.46, reach_quarter_final: 0.60, reach_round_of_16: 0.88, qualify: 0.93,
  },
  {
    team_id: 'FRA', team_name: 'Francia', win_tournament: 0.15, reach_final: 0.27,
    reach_semi_final: 0.41, reach_quarter_final: 0.56, reach_round_of_16: 0.85, qualify: 0.91,
  },
  {
    team_id: 'BRA', team_name: 'Brasil', win_tournament: 0.14, reach_final: 0.26,
    reach_semi_final: 0.40, reach_quarter_final: 0.54, reach_round_of_16: 0.84, qualify: 0.90,
  },
]

const SIM_RUN = {
  id: 'run-1',
  model_name: 'poisson',
  iterations: 30000,
  status: 'completed',
  created_at: '2026-06-01T10:00:00Z',
  finished_at: '2026-06-01T10:05:00Z',
}

/**
 * Stub ALL /api/** calls with an empty 200 response.
 * Register this FIRST so that more specific mocks registered later take priority.
 */
export async function mockAllApiStubs(page: Page): Promise<void> {
  await page.route('/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  )
}

/** Mock /api/auth/status as authenticated (register AFTER mockAllApiStubs) */
export async function mockAuthOk(page: Page): Promise<void> {
  await page.route('/api/auth/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ authenticated: true, must_change_password: false }),
    })
  )
  await page.route('/api/auth/password-changed', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ password_changed: true }),
    })
  )
}

/** Mock /api/auth/status as unauthenticated (register AFTER mockAllApiStubs) */
export async function mockAuthNone(page: Page): Promise<void> {
  await page.route('/api/auth/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ authenticated: false, must_change_password: false }),
    })
  )
}

/** Mock model evaluation/metrics endpoints (register AFTER mockAllApiStubs) */
export async function mockEvaluationData(page: Page): Promise<void> {
  const metrics = [
    { model_name: 'poisson', brier_score: 0.210, log_loss: 0.95, rps: 0.18, accuracy: 0.52, total_predictions: 120 },
    { model_name: 'elo',     brier_score: 0.225, log_loss: 1.00, rps: 0.20, accuracy: 0.49, total_predictions: 120 },
    { model_name: 'baseline',brier_score: 0.280, log_loss: 1.10, rps: 0.24, accuracy: 0.42, total_predictions: 120 },
  ]
  await page.route('/api/evaluations/summary', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(metrics) })
  )
  await page.route('/api/evaluations/calibration*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )
}

/** Mock the core simulation endpoints (register AFTER mockAllApiStubs) */
export async function mockSimulationData(page: Page, model = 'poisson'): Promise<void> {
  const body = JSON.stringify({
    run: { ...SIM_RUN, model_name: model },
    team_results: TEAM_RESULTS,
  })

  await page.route('/api/simulations/latest*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body })
  )

  const comparisonBody = JSON.stringify({
    models: ['poisson', 'elo', 'baseline'],
    teams: TEAM_RESULTS.map((t) => ({
      ...t,
      poisson: t.win_tournament,
      elo: t.win_tournament * 0.95,
      baseline: t.win_tournament * 0.85,
    })),
  })
  await page.route('/api/simulations/comparison', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: comparisonBody })
  )

  await page.route('/api/simulations/diff*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'no_previous_simulation' }),
    })
  )
}

/**
 * Full authenticated setup: stubs all API, then overrides auth + simulation.
 * Convenience wrapper that sets up routes in the correct order.
 */
export async function setupAuthenticated(page: Page): Promise<void> {
  await mockAllApiStubs(page)    // catch-all first (lowest priority)
  await mockAuthOk(page)         // auth routes
  await mockEvaluationData(page) // evaluation routes (Dashboard uses these)
  await mockSimulationData(page) // sim routes last (highest priority)
}

/**
 * Unauthenticated setup: stubs all API, then marks auth as not logged in.
 */
export async function setupUnauthenticated(page: Page): Promise<void> {
  await mockAllApiStubs(page)
  await mockAuthNone(page)
}
