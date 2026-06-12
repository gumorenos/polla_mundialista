import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Snapshots from '../pages/Snapshots'

vi.mock('../api/hooks', () => ({
  useSnapshots: () => ({
    data: [
      { id: 's1', label: 'Post Full Refresh', description: 'Auto-snapshot', trigger: 'full_refresh', simulation_run_id: 'r1', created_at: '2026-01-15T10:00:00Z' },
      { id: 's2', label: null, description: null, trigger: 'daily_update', simulation_run_id: null, created_at: '2026-01-16T08:00:00Z' },
    ],
    isLoading: false,
    error: null,
  }),
}))

describe('Snapshots', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><Snapshots /></MemoryRouter>)
    expect(screen.getByText('Snapshots')).toBeInTheDocument()
  })

  it('shows snapshot labels', () => {
    render(<MemoryRouter><Snapshots /></MemoryRouter>)
    expect(screen.getByText('Post Full Refresh')).toBeInTheDocument()
  })

  it('shows trigger badges', () => {
    render(<MemoryRouter><Snapshots /></MemoryRouter>)
    expect(screen.getByText('full_refresh')).toBeInTheDocument()
    expect(screen.getByText('daily_update')).toBeInTheDocument()
  })
})
