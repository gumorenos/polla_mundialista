import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export default function ChangePassword() {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const handleSubmit = async () => {
    if (!oldPassword || !newPassword || !confirmPassword) {
      setError('Completa todos los campos')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('Las contraseñas no coinciden')
      return
    }
    if (newPassword.length < 6) {
      setError('Mínimo 6 caracteres')
      return
    }

    setLoading(true)
    setError('')
    try {
      const res = await api.post<{ status: string; message: string }>(
        '/api/auth/change-password',
        { old_password: oldPassword, new_password: newPassword },
      )
      setSuccess(res.message)
      await qc.invalidateQueries({ queryKey: ['auth-status'] })
      await qc.refetchQueries({ queryKey: ['auth-status'] })
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
        <h1 className="text-xl font-bold text-white">Cambiar contraseña</h1>
        <p className="text-yellow-400 text-sm">
          Debes establecer una contraseña segura antes de continuar.
        </p>
        <input
          type="password"
          placeholder="Contraseña actual"
          value={oldPassword}
          onChange={e => setOldPassword(e.target.value)}
          disabled={loading}
          className="w-full bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 focus:outline-none focus:border-green-500"
        />
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
          placeholder="Confirmar nueva contraseña"
          value={confirmPassword}
          onChange={e => setConfirmPassword(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          disabled={loading}
          className="w-full bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 focus:outline-none focus:border-green-500"
        />
        {error && <p className="text-red-400 text-sm">{error}</p>}
        {success && <p className="text-green-400 text-sm">{success}</p>}
        <button
          onClick={handleSubmit}
          disabled={loading || !oldPassword || !newPassword || !confirmPassword}
          className="w-full bg-green-600 hover:bg-green-700 text-white py-2 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? 'Guardando…' : 'Cambiar contraseña'}
        </button>
      </div>
    </div>
  )
}
