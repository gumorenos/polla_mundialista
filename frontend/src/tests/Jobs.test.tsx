import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Jobs from '../pages/Jobs'

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
    ],
    isLoading: false,
    error: null,
  }),
  useCancelJob: () => ({ mutate: vi.fn(), isPending: false }),
}))

describe('Jobs', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('Background Jobs')).toBeInTheDocument()
  })

  it('shows job types', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('full_refresh')).toBeInTheDocument()
    expect(screen.getByText('simulation')).toBeInTheDocument()
    expect(screen.getByText('daily_update')).toBeInTheDocument()
  })

  it('shows status badges', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('completed')).toBeInTheDocument()
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
