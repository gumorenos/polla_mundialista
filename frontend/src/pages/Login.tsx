import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

type LoginResponse = { status: string; must_change_password: boolean }

export default function Login() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [mustChange, setMustChange] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const navigate = useNavigate()
  const qc = useQueryClient()

  const handleLogin = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.post<LoginResponse>('/api/auth/login', { password })
      await qc.invalidateQueries({ queryKey: ['auth-status'] })
      await qc.refetchQueries({ queryKey: ['auth-status'] })
      if (res.must_change_password) {
        setMustChange(true)
      } else {
        navigate('/')
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Contraseña incorrecta')
    } finally {
      setLoading(false)
    }
  }

  const handleChangePassword = async () => {
    if (!newPassword || !confirmPassword) { setError('Completa ambos campos'); return }
    if (newPassword !== confirmPassword) { setError('Las contraseñas no coinciden'); return }
    if (newPassword.length < 6) { setError('Mínimo 6 caracteres'); return }

    setLoading(true)
    setError('')
    try {
      await api.post('/api/auth/change-password', {
        old_password: password,
        new_password: newPassword,
      })
      setError('Contraseña cambiada exitosamente')
      await qc.invalidateQueries({ queryKey: ['auth-status'] })
      await qc.refetchQueries({ queryKey: ['auth-status'] })
      setMustChange(false)
      setNewPassword('')
      setConfirmPassword('')
      navigate('/')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error al cambiar contraseña')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="bg-gray-800 p-8 rounded-lg w-80 space-y-4">
        <h1 className="text-xl font-bold text-white">Oráculo Mundial 2026</h1>

        {!mustChange ? (
          <>
            <input
              type="password"
              placeholder="Contraseña"
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleLogin()}
              disabled={loading}
              className="w-full bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
            />
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <button
              onClick={handleLogin}
              disabled={loading || !password}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Entrando…' : 'Entrar'}
            </button>
          </>
        ) : (
          <>
            <p className="text-yellow-400 text-sm">
              Cambia la contraseña antes de continuar.
            </p>
            <input
              type="password"
              placeholder="Nueva contraseña (mín. 6 caracteres)"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              disabled={loading}
              className="w-full bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 focus:outline-none focus:border-green-500"
            />
            <input
              type="password"
              placeholder="Confirmar contraseña"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleChangePassword()}
              disabled={loading}
              className="w-full bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 focus:outline-none focus:border-green-500"
            />
            {error && (
              <p className={error.includes('exitosamente') ? 'text-green-400 text-sm' : 'text-red-400 text-sm'}>
                {error}
              </p>
            )}
            <button
              onClick={handleChangePassword}
              disabled={loading || !newPassword || !confirmPassword}
              className="w-full bg-green-600 hover:bg-green-700 text-white py-2 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Guardando…' : 'Cambiar contraseña'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
