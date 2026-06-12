import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Models from '../pages/Models'

vi.mock('../api/hooks', () => ({
  useModelsComparison: () => ({
    data: [
      { model_name: 'poisson', brier_score: 0.21, log_loss: 0.95, rps: 0.18, accuracy: 0.52, total_predictions: 120 },
      { model_name: 'baseline', brier_score: 0.28, log_loss: 1.10, rps: 0.24, accuracy: 0.42, total_predictions: 120 },
    ],
    isLoading: false,
    error: null,
  }),
}))

describe('Models', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><Models /></MemoryRouter>)
    expect(screen.getByText('Comparación de modelos')).toBeInTheDocument()
  })

  it('shows model names in table', () => {
    render(<MemoryRouter><Models /></MemoryRouter>)
    expect(screen.getByText('poisson')).toBeInTheDocument()
    expect(screen.getByText('baseline')).toBeInTheDocument()
  })

  it('shows metric column headers', () => {
    render(<MemoryRouter><Models /></MemoryRouter>)
    expect(screen.getByText(/Brier/i)).toBeInTheDocument()
    expect(screen.getByText(/Accuracy/i)).toBeInTheDocument()
  })
})
