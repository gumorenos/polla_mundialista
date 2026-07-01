import { useState } from 'react'
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '../api/hooks'
import type { ApiKeyRecord } from '../api/hooks'

function fmtDate(d: string | null) {
  return d ? new Date(d).toLocaleString() : '—'
}

function NewKeyReveal({ apiKey, onDismiss }: { apiKey: { key: string; label: string }; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(apiKey.key).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="rounded-lg border border-yellow-700 bg-yellow-950/30 p-4 space-y-3">
      <p className="text-sm font-semibold text-yellow-300">
        API key creada para «{apiKey.label}»
      </p>
      <p className="text-xs text-yellow-400">
        Guárdala ahora — no se puede recuperar después (solo se guarda su hash).
      </p>
      <div className="flex items-center gap-2">
        <code className="flex-1 overflow-x-auto rounded bg-gray-900 px-3 py-2 text-xs text-green-300 font-mono">
          {apiKey.key}
        </code>
        <button
          onClick={handleCopy}
          className="rounded bg-blue-700 px-3 py-2 text-xs text-white hover:bg-blue-600 whitespace-nowrap"
        >
          {copied ? '✓ Copiada' : 'Copiar'}
        </button>
      </div>
      <div className="rounded bg-gray-900 px-3 py-2">
        <p className="text-xs text-gray-500 mb-1">Ejemplo de uso:</p>
        <code className="text-xs text-gray-300 font-mono break-all">
          curl -H "X-API-Key: {apiKey.key}" https://tu-dominio.com/api/public/v1/simulations/latest?model=consensus
        </code>
      </div>
      <button
        onClick={onDismiss}
        className="text-xs text-gray-400 hover:text-gray-200 underline"
      >
        Cerrar
      </button>
    </div>
  )
}

function ApiKeyRow({ apiKey, onRevoke, isRevoking }: { apiKey: ApiKeyRecord; onRevoke: (id: string) => void; isRevoking: boolean }) {
  return (
    <tr className="border-b border-gray-800/50">
      <td className="py-2 font-mono text-xs text-gray-300">{apiKey.prefix}…</td>
      <td className="py-2 text-white">{apiKey.label}</td>
      <td className="py-2 text-gray-400">{apiKey.scopes}</td>
      <td className="py-2 text-gray-400">{apiKey.rate_limit_per_minute}/min</td>
      <td className="py-2 text-gray-500 text-xs">{fmtDate(apiKey.created_at)}</td>
      <td className="py-2 text-gray-500 text-xs">{fmtDate(apiKey.last_used_at)}</td>
      <td className="py-2">
        {apiKey.revoked ? (
          <span className="text-xs text-red-400">Revocada</span>
        ) : (
          <span className="text-xs text-green-400">Activa</span>
        )}
      </td>
      <td className="py-2">
        {!apiKey.revoked && (
          <button
            onClick={() => onRevoke(apiKey.id)}
            disabled={isRevoking}
            className="rounded px-2 py-1 text-xs font-medium bg-red-900 text-red-300 hover:bg-red-700 disabled:opacity-50"
          >
            Revocar
          </button>
        )}
      </td>
    </tr>
  )
}

export default function ApiKeys() {
  const { data, isLoading, error } = useApiKeys()
  const createKey = useCreateApiKey()
  const revokeKey = useRevokeApiKey()
  const [label, setLabel] = useState('')
  const [notes, setNotes] = useState('')
  const [revealedKey, setRevealedKey] = useState<{ key: string; label: string } | null>(null)

  function handleCreate() {
    if (!label.trim()) return
    createKey.mutate(
      { label: label.trim(), notes: notes.trim() || undefined },
      {
        onSuccess: (res) => {
          setRevealedKey({ key: res.key, label: res.label })
          setLabel('')
          setNotes('')
        },
      },
    )
  }

  function handleRevoke(id: string) {
    if (!window.confirm('¿Revocar esta API key? No se puede deshacer.')) return
    revokeKey.mutate(id)
  }

  return (
    <div className="p-4 sm:p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">API Keys</h2>
        <p className="mt-1 text-sm text-gray-400">
          Gestión de claves para la API pública de solo lectura (<code>/api/public/v1</code>).
        </p>
      </div>

      {revealedKey && <NewKeyReveal apiKey={revealedKey} onDismiss={() => setRevealedKey(null)} />}

      <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Crear nueva key</h3>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Nombre del proyecto consumidor"
            className="flex-1 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200"
          />
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notas (opcional)"
            className="flex-1 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200"
          />
          <button
            onClick={handleCreate}
            disabled={createKey.isPending || !label.trim()}
            className="rounded bg-blue-700 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50 whitespace-nowrap"
          >
            {createKey.isPending ? 'Creando…' : 'Crear key'}
          </button>
        </div>
        {createKey.isError && (
          <p className="text-xs text-red-400">Error: {createKey.error.message}</p>
        )}
      </div>

      {isLoading && <p className="text-gray-400">Cargando keys…</p>}
      {error && <p className="text-red-400">Error al cargar las API keys.</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm px-2">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Prefijo</th>
                <th className="px-4 py-2 font-medium">Label</th>
                <th className="px-4 py-2 font-medium">Scopes</th>
                <th className="px-4 py-2 font-medium">Rate limit</th>
                <th className="px-4 py-2 font-medium">Creada</th>
                <th className="px-4 py-2 font-medium">Último uso</th>
                <th className="px-4 py-2 font-medium">Estado</th>
                <th className="px-4 py-2 font-medium">Acciones</th>
              </tr>
            </thead>
            <tbody className="px-4">
              {data.keys.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-gray-500">
                    Sin API keys creadas todavía.
                  </td>
                </tr>
              )}
              {data.keys.map((k) => (
                <ApiKeyRow key={k.id} apiKey={k} onRevoke={handleRevoke} isRevoking={revokeKey.isPending} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
