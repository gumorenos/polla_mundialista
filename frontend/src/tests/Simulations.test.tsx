import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Simulations from '../pages/Simulations'

const mockTeamResults = [
  { team_id: 1, team_name: 'Francia', win_tournament: 0.15, reach_final: 0.27, reach_semi_final: 0.40, reach_quarter_final: 0.55, reach_round_of_16: 0.88, qualify: 0.93 },
  { team_id: 2, team_name: 'Brasil', win_tournament: 0.18, reach_final: 0.30, reach_semi_final: 0.44, reach_quarter_final: 0.58, reach_round_of_16: 0.90, qualify: 0.95 },
]

vi.mock('../api/hooks', () => ({
  useSimulations: () => ({
    data: {
      run: { id: 'r1', model_name: 'poisson', iterations: 30000, status: 'completed', created_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:05:00Z' },
      team_results: mockTeamResults,
    },
    isLoading: false,
    error: null,
  }),
  useRunSimulation: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, data: null }),
  useSimulationComparison: () => ({ data: null, isLoading: false, error: null }),
  useSimulationDiff: () => ({ data: null, isLoading: false, error: null }),
  useShapGlobal: () => ({ data: null, isLoading: false, error: null }),
  useShapMatch: () => ({ data: null, isLoading: false, error: null }),
  useTeamNarrative: () => ({ data: null, isLoading: false, error: null }),
  useOddsValue: () => ({ data: null, isLoading: false, error: null }),
}))

describe('Simulations', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><Simulations /></MemoryRouter>)
    expect(screen.getByText('Simulaciones Monte Carlo')).toBeInTheDocument()
  })

  it('shows team results', () => {
    render(<MemoryRouter><Simulations /></MemoryRouter>)
    expect(screen.getByText('Brasil')).toBeInTheDocument()
    expect(screen.getByText('Francia')).toBeInTheDocument()
  })

  it('shows model selector', () => {
    render(<MemoryRouter><Simulations /></MemoryRouter>)
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('shows simulate button', () => {
    render(<MemoryRouter><Simulations /></MemoryRouter>)
    expect(screen.getByRole('button', { name: /Simular/i })).toBeInTheDocument()
  })
})
