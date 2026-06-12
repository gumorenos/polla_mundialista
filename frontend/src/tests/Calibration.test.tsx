import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Calibration from '../pages/Calibration'

vi.mock('../api/hooks', () => ({
  useCalibration: () => ({
    data: [
      { bin_center: 0.05, predicted_freq: 0.05, observed_freq: 0.04, count: 50 },
      { bin_center: 0.15, predicted_freq: 0.15, observed_freq: 0.14, count: 60 },
      { bin_center: 0.50, predicted_freq: 0.50, observed_freq: 0.52, count: 80 },
    ],
    isLoading: false,
    error: null,
  }),
  useModelsComparison: () => ({
    data: [
      { model_name: 'poisson', brier_score: 0.21, log_loss: 0.95, rps: 0.18, accuracy: 0.52, total_predictions: 120 },
    ],
    isLoading: false,
    error: null,
  }),
}))

describe('Calibration', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><Calibration /></MemoryRouter>)
    expect(screen.getByText('Calibración')).toBeInTheDocument()
  })

  it('shows model selector', () => {
    render(<MemoryRouter><Calibration /></MemoryRouter>)
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('shows metric values', () => {
    render(<MemoryRouter><Calibration /></MemoryRouter>)
    expect(screen.getByText(/Brier/i)).toBeInTheDocument()
    expect(screen.getByText(/Log-Loss/i)).toBeInTheDocument()
  })
})
