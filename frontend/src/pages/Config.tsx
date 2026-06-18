import { useState, useEffect } from 'react'
import { useAppConfig, useUpdateConfig, useResetConfig } from '../api/hooks'
import { useAuth } from '../hooks/useAuth'
import type { AppConfigEntry } from '../types'

// ---------------------------------------------------------------------------
// Config schema — drives the UI
// ---------------------------------------------------------------------------

interface ParamDef {
  key: string
  label: string
  description: string
  type: 'slider' | 'select'
  min?: number
  max?: number
  step?: number
  options?: number[]
  format: (v: number) => string
  parse: (v: string) => number
}

const PARAMS: ParamDef[] = [
  {
    key: 'NEWS_CONFIDENCE_THRESHOLD',
    label: 'Umbral de confianza LLM',
    description: 'Solo aplicar ajuste si el LLM está este % seguro de la lesión.',
    type: 'slider',
    min: 0.5, max: 1.0, step: 0.05,
    format: (v) => `${Math.round(v * 100)}%`,
    parse: (s) => parseFloat(s),
  },
  {
    key: 'INJURY_ATTACK_PENALTY',
    label: 'Penalización de ataque por lesión',
    description: 'Reducción en fuerza ofensiva cuando hay lesión de atacante.',
    type: 'slider',
    min: 0, max: 0.5, step: 0.01,
    format: (v) => `${Math.round(v * 100)}%`,
    parse: (s) => parseFloat(s),
  },
  {
    key: 'INJURY_DEFENSE_PENALTY',
    label: 'Penalización de defensa por lesión',
    description: 'Reducción en solidez defensiva cuando hay lesión defensiva.',
    type: 'slider',
    min: 0, max: 0.5, step: 0.01,
    format: (v) => `${Math.round(v * 100)}%`,
    parse: (s) => parseFloat(s),
  },
  {
    key: 'NEWS_MIN_SOURCES',
    label: 'Fuentes mínimas para confirmar',
    description: 'Cuántas fuentes distintas deben reportar la lesión para activar el ajuste.',
    type: 'select',
    options: [1, 2, 3, 4, 5],
    format: (v) => `${v}`,
    parse: (s) => parseInt(s, 10),
  },
  {
    key: 'NEWS_DAYS_LOOKBACK',
    label: 'Días de lookback de noticias',
    description: 'Solo considerar noticias de los últimos X días.',
    type: 'slider',
    min: 1, max: 30, step: 1,
    format: (v) => `${v} días`,
    parse: (s) => parseInt(s, 10),
  },
]

// ---------------------------------------------------------------------------
// Single parameter control
// ---------------------------------------------------------------------------

function ParamRow({
  def,
  entry,
  disabled,
  pending,
  onChange,
}: {
  def: ParamDef
  entry: AppConfigEntry | undefined
  disabled: boolean
  pending: boolean
  onChange: (key: string, value: string) => void
}) {
  const raw = entry?.value ?? ''
  const num = def.parse(raw)
  const displayValue = isNaN(num) ? raw : def.format(num)

  return (
    <div className="rounded-lg border p-4 space-y-3"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface2)' }}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            {def.label}
          </p>
          <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>
            {def.description}
          </p>
        </div>
        <span
          className="shrink-0 text-sm font-mono font-bold px-2 py-1 rounded"
          style={{ background: 'var(--color-surface)', color: 'var(--color-accent)' }}
        >
          {displayValue}
        </span>
      </div>

      {def.type === 'slider' && (
        <div className="flex items-center gap-3">
          <span className="text-xs w-8 text-right" style={{ color: 'var(--color-muted)' }}>
            {def.format(def.min!)}
          </span>
          <input
            type="range"
            min={def.min}
            max={def.max}
            step={def.step}
            value={isNaN(num) ? def.min : num}
            disabled={disabled || pending}
            onChange={(e) => onChange(def.key, e.target.value)}
            className="flex-1 h-2 rounded-full accent-blue-500 disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
          />
          <span className="text-xs w-8" style={{ color: 'var(--color-muted)' }}>
            {def.format(def.max!)}
          </span>
        </div>
      )}

      {def.type === 'select' && (
        <div className="flex gap-2">
          {def.options!.map((opt) => (
            <button
              key={opt}
              disabled={disabled || pending}
              onClick={() => onChange(def.key, String(opt))}
              className={`flex-1 rounded py-1.5 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                num === opt
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-700 hover:text-gray-100'
              }`}
              style={num !== opt ? { background: 'var(--color-surface)' } : undefined}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      {entry?.updated_at && (
        <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
          Última actualización: {new Date(entry.updated_at).toLocaleString()}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Config() {
  const { data: auth } = useAuth()
  const isAdmin = auth?.authenticated === true
  const { data: configEntries, isLoading, error } = useAppConfig()
  const updateConfig = useUpdateConfig()
  const resetConfig = useResetConfig()

  // Local draft state — keyed by config key
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState<string | null>(null)

  // Initialise draft from loaded config
  useEffect(() => {
    if (configEntries) {
      const initial: Record<string, string> = {}
      for (const e of configEntries) initial[e.key] = e.value
      setDraft(initial)
    }
  }, [configEntries])

  function handleChange(key: string, value: string) {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  async function handleSave() {
    const entries = Object.entries(draft)
    for (const [key, value] of entries) {
      const original = configEntries?.find((e) => e.key === key)?.value
      if (value !== original) {
        await updateConfig.mutateAsync({ key, value })
      }
    }
    setSaved(new Date().toLocaleTimeString())
  }

  async function handleReset() {
    if (!window.confirm('¿Restaurar todos los valores por defecto?')) return
    await resetConfig.mutateAsync()
    setSaved(null)
  }

  const configMap = Object.fromEntries(
    (configEntries ?? []).map((e) => [e.key, e])
  )

  const isPending = updateConfig.isPending || resetConfig.isPending

  return (
    <div className="p-4 sm:p-8 space-y-6 max-w-2xl">
      <div>
        <h2 className="text-2xl font-bold" style={{ color: 'var(--color-text)' }}>
          Configuración de lesiones
        </h2>
        <p className="mt-1 text-sm" style={{ color: 'var(--color-muted)' }}>
          Parámetros del pipeline de noticias — cambios efectivos en el próximo análisis.
        </p>
      </div>

      {!isAdmin && (
        <div className="rounded-lg border px-4 py-3 text-sm"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}>
          Solo lectura — inicia sesión como administrador para modificar.
        </div>
      )}

      {isLoading && (
        <p className="text-sm" style={{ color: 'var(--color-muted)' }}>Cargando configuración…</p>
      )}

      {error && (
        <p className="text-sm text-red-400">Error al cargar la configuración.</p>
      )}

      {configEntries && (
        <div className="space-y-4">
          {PARAMS.map((def) => (
            <ParamRow
              key={def.key}
              def={def}
              entry={draft[def.key] !== undefined
                ? { ...configMap[def.key], value: draft[def.key] }
                : configMap[def.key]
              }
              disabled={!isAdmin}
              pending={isPending}
              onChange={handleChange}
            />
          ))}
        </div>
      )}

      {isAdmin && configEntries && (
        <div className="flex flex-wrap gap-3 pt-2">
          <button
            onClick={handleSave}
            disabled={isPending}
            className="rounded bg-blue-700 px-5 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
          >
            {updateConfig.isPending ? 'Guardando…' : 'Guardar cambios'}
          </button>
          <button
            onClick={handleReset}
            disabled={isPending}
            className="rounded px-5 py-2 text-sm disabled:opacity-50"
            style={{ background: 'var(--color-surface2)', color: 'var(--color-muted)' }}
          >
            {resetConfig.isPending ? 'Restaurando…' : 'Restaurar valores por defecto'}
          </button>
          {saved && (
            <span className="self-center text-xs text-green-400">
              Guardado a las {saved}
            </span>
          )}
        </div>
      )}

      {(updateConfig.isError || resetConfig.isError) && (
        <p className="text-sm text-red-400">
          Error al guardar: {(updateConfig.error || resetConfig.error)?.message}
        </p>
      )}
    </div>
  )
}
