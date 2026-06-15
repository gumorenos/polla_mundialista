import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Jobs from '../pages/Jobs'

vi.mock('../api/hooks', () => ({
  useJobs: () => ({
    data: [
      {
        id: 'j1',
        rq_job_id: 'rq-abc',
        job_type: 'full_refresh',
        status: 'completed',
        progress: 1.0,
        error_message: null,
        result_ref: null,
        created_at: '2026-01-15T10:00:00Z',
        started_at: '2026-01-15T10:00:05Z',
        finished_at: '2026-01-15T10:03:30Z',
      },
      {
        id: 'j2',
        rq_job_id: 'rq-def',
        job_type: 'simulation',
        status: 'failed',
        progress: 0.3,
        error_message: 'Connection timeout',
        result_ref: null,
        created_at: '2026-01-16T08:00:00Z',
        started_at: '2026-01-16T08:00:02Z',
        finished_at: null,
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
  })

  it('shows status badges', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('completed')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
  })

  it('shows error message for failed jobs', () => {
    render(<MemoryRouter><Jobs /></MemoryRouter>)
    expect(screen.getByText('Connection timeout')).toBeInTheDocument()
  })
})
