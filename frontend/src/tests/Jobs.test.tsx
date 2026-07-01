import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Jobs, { parseJobType } from '../pages/Jobs'

const BASE_JOB = {
  rq_job_id: null,
  progress: 0,
  error_message: null,
  result_ref: null,
  last_heartbeat: null,
  finished_at: null,
}

vi.mock('../api/hooks', () => ({
  useAuthStatus: () => ({ data: { authenticated: true }, isLoading: false, error: null }),
  useJobs: () => ({
    data: [
      {
        ...BASE_JOB,
        id: 'j1',
        job_type: 'full_refresh',
        status: 'completed',
        progress: 1.0,
        created_at: '2026-01-15T10:00:00Z',
        started_at: '2026-01-15T10:00:05Z',
        finished_at: '2026-01-15T10:03:30Z',
      },
      {
        ...BASE_JOB,
        id: 'j2',
        job_type: 'simulation',
        status: 'failed',
        progress: 0.3,
        error_message: 'Connection timeout',
        created_at: '2026-01-16T08:00:00Z',
        started_at: '2026-01-16T08:00:02Z',
      },
      {
        ...BASE_JOB,
        id: 'j3',
        job_type: 'daily_update',
        status: 'running',
        progress: 0.5,
        // recent heartbeat — should NOT show stuck badge
        last_heartbeat: new Date(Date.now() - 10_000).toISOString(),
        created_at: new Date(Date.now() - 60_000).toISOString(),
        started_at: new Date(Date.now() - 60_000).toISOString(),
      },
      {
        ...BASE_JOB,
        id: 'j4',
        job_type: 'simulation_full_poisson',
        status: 'completed',
        progress: 1.0,
        created_at: '2026-01-17T08:00:00Z',
      },
      {
        ...BASE_JOB,
        id: 'j5',
        job_type: 'simulation_bracket_elo',
        status: 'completed',
        progress: 1.0,
        created_at: '2026-01-17T09:00:00Z',
      },
    ],
    isLoading: false,
    error: null,
  }),
  useCancelJob: () => ({ mutate: vi.fn(), isPending: false }),
  usePurgeJobs: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteJobRecord: () => ({ mutate: vi.fn(), isPending: false }),
}))

describe('Jobs', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('Background Jobs')).toBeInTheDocument()
  })

  it('shows job types with friendly labels for legacy and new naming', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('Full Refresh')).toBeInTheDocument()
    expect(screen.getByText('Simulación')).toBeInTheDocument() // legacy bare 'simulation'
    expect(screen.getByText('Daily Update')).toBeInTheDocument()
    expect(screen.getByText('Monte Carlo — Poisson')).toBeInTheDocument() // simulation_full_poisson
    expect(screen.getByText('Bracket vivo — ELO')).toBeInTheDocument() // simulation_bracket_elo
  })

  it('shows status badges', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0)
    expect(screen.getByText('failed')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
  })

  it('shows error message for failed jobs', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('Connection timeout')).toBeInTheDocument()
  })

  it('shows elapsed time for running jobs', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    // The running job started ~60s ago so elapsed column should show something
    const elapsed = screen.queryByText(/\d+s$/)
    expect(elapsed).not.toBeNull()
  })

  it('does not show stuck badge when heartbeat is recent', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    // j3 has a recent heartbeat — should NOT show "atascado?" badge
    expect(screen.queryByText(/atascado/)).toBeNull()
  })
})

describe('parseJobType', () => {
  it('parses new full-simulation naming', () => {
    expect(parseJobType('simulation_full_poisson')).toEqual({
      origin: 'full_monte_carlo', model: 'poisson', label: 'Monte Carlo — Poisson',
    })
  })

  it('parses new bracket naming', () => {
    expect(parseJobType('simulation_bracket_consensus')).toEqual({
      origin: 'bracket', model: 'consensus', label: 'Bracket vivo — Consenso',
    })
  })

  it('parses legacy bracket naming (pre Fase-1)', () => {
    expect(parseJobType('bracket_elo')).toEqual({
      origin: 'bracket', model: 'elo', label: 'Bracket vivo — ELO',
    })
  })

  it('parses legacy simulation_<model> naming (pre Fase-1)', () => {
    expect(parseJobType('simulation_poisson')).toEqual({
      origin: 'full_monte_carlo', model: 'poisson', label: 'Monte Carlo — Poisson',
    })
  })

  it('parses legacy bare "simulation"', () => {
    expect(parseJobType('simulation')).toEqual({
      origin: 'full_monte_carlo', model: null, label: 'Simulación',
    })
  })

  it('parses pipeline job types', () => {
    expect(parseJobType('daily_update').label).toBe('Daily Update')
    expect(parseJobType('full_refresh').label).toBe('Full Refresh')
    expect(parseJobType('nightly_update_and_simulations').label).toBe('Nightly (update + simulaciones)')
  })

  it('falls back to the raw job_type for unknown values', () => {
    expect(parseJobType('something_weird')).toEqual({
      origin: 'other', model: null, label: 'something_weird',
    })
  })
})
