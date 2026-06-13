import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Dashboard from '../pages/Dashboard'

vi.mock('../api/hooks', () => ({
  useModelsComparison: () => ({
    data: [
      { model_name: 'poisson', brier_score: 0.21, log_loss: 0.95, rps: 0.18, accuracy: 0.52, total_predictions: 120 },
      { model_name: 'elo', brier_score: 0.23, log_loss: 1.02, rps: 0.20, accuracy: 0.49, total_predictions: 120 },
    ],
    isLoading: false,
    error: null,
  }),
  useSimulations: () => ({
    data: {
      run: { id: 'r1', model_name: 'poisson', iterations: 30000, status: 'completed', created_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:05:00Z' },
      team_results: [
        { team_id: 'BRA', team_name: 'Brasil', win_tournament: 0.18, reach_final: 0.32, reach_semi_final: 0.47, reach_quarter_final: 0.6, reach_round_of_16: 0.9, qualify: 0.95 },
        { team_id: 'ARG', team_name: 'Argentina', win_tournament: 0.16, reach_final: 0.28, reach_semi_final: 0.42, reach_quarter_final: 0.55, reach_round_of_16: 0.85, qualify: 0.93 },
      ],
    },
    isLoading: false,
    error: null,
  }),
  useTriggerFullRefresh: () => ({ mutate: vi.fn(), isPending: false }),
  useTriggerDailyUpdate: () => ({ mutate: vi.fn(), isPending: false }),
}))

describe('Dashboard', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    expect(screen.getByText('Oráculo Mundial 2026')).toBeInTheDocument()
  })

  it('shows the best model name', () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    expect(screen.getByText('poisson')).toBeInTheDocument()
  })

  it('shows top teams table', () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    expect(screen.getByText('Brasil')).toBeInTheDocument()
    expect(screen.getByText('Argentina')).toBeInTheDocument()
  })

  it('shows metric cards', () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    expect(screen.getByText('Modelos evaluados')).toBeInTheDocument()
  })
})
