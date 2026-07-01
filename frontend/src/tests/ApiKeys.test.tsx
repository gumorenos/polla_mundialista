import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ApiKeys from '../pages/ApiKeys'

const mockCreateMutate = vi.fn()
const mockRevokeMutate = vi.fn()

vi.mock('../api/hooks', () => ({
  useApiKeys: () => ({
    data: {
      keys: [
        {
          id: 'k1', prefix: 'om26_ab12cd3', label: 'mi-otro-proyecto',
          scopes: 'read', rate_limit_per_minute: 60, notes: null,
          created_at: '2026-01-01T00:00:00Z', last_used_at: '2026-01-02T00:00:00Z', revoked: 0,
        },
        {
          id: 'k2', prefix: 'om26_zz99yy8', label: 'proyecto-viejo',
          scopes: 'read', rate_limit_per_minute: 60, notes: null,
          created_at: '2025-12-01T00:00:00Z', last_used_at: null, revoked: 1,
        },
      ],
    },
    isLoading: false,
    error: null,
  }),
  useCreateApiKey: () => ({
    mutate: mockCreateMutate,
    isPending: false,
    isError: false,
  }),
  useRevokeApiKey: () => ({
    mutate: mockRevokeMutate,
    isPending: false,
  }),
}))

describe('ApiKeys', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><ApiKeys /></MemoryRouter>)
    expect(screen.getByText('API Keys')).toBeInTheDocument()
  })

  it('lists keys with prefix, never the full key', () => {
    render(<MemoryRouter><ApiKeys /></MemoryRouter>)
    expect(screen.getByText('mi-otro-proyecto')).toBeInTheDocument()
    expect(screen.getByText(/om26_ab12cd3/)).toBeInTheDocument()
  })

  it('shows revoked state for revoked keys', () => {
    render(<MemoryRouter><ApiKeys /></MemoryRouter>)
    expect(screen.getByText('Revocada')).toBeInTheDocument()
    expect(screen.getByText('Activa')).toBeInTheDocument()
  })

  it('only shows a revoke button for active keys', () => {
    render(<MemoryRouter><ApiKeys /></MemoryRouter>)
    const revokeButtons = screen.getAllByText('Revocar')
    expect(revokeButtons).toHaveLength(1)
  })

  it('calls create mutation with label when submitting the form', () => {
    render(<MemoryRouter><ApiKeys /></MemoryRouter>)
    const input = screen.getByPlaceholderText('Nombre del proyecto consumidor')
    fireEvent.change(input, { target: { value: 'nuevo-proyecto' } })
    fireEvent.click(screen.getByText('Crear key'))
    expect(mockCreateMutate).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'nuevo-proyecto' }),
      expect.anything(),
    )
  })
})
