import { useState } from 'react'
import { useNews, useNewsSummary, useTriggerNews } from '../api/hooks'
import type { NewsClaim, NewsTeamSummary } from '../types'

const STATUS_LABELS: Record<string, string> = {
  injured: 'Lesión',
  doubtful: 'Dudoso',
  available: 'Disponible',
  unknown: 'Sin datos',
}

const STATUS_COLORS: Record<string, string> = {
  injured: 'bg-red-900/60 text-red-300',
  doubtful: 'bg-yellow-900/60 text-yellow-300',
  available: 'bg-green-900/60 text-green-300',
  unknown: 'bg-gray-800 text-gray-400',
}

const CLASSIFICATION_OPTIONS = [
  { value: '', label: 'Todos' },
  { value: 'injured', label: 'Lesión' },
  { value: 'doubtful', label: 'Dudoso' },
  { value: 'available', label: 'Disponible' },
  { value: 'unknown', label: 'Sin datos' },
]

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[status] ?? 'bg-gray-800 text-gray-400'}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

function TeamSummaryCard({ team }: { team: NewsTeamSummary }) {
  const attackImpact = team.attack_factor != null ? ((1 - team.attack_factor) * 100).toFixed(0) : null
  const defenseImpact = team.defense_factor != null ? ((team.defense_factor - 1) * 100).toFixed(0) : null

  return (
    <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-white text-sm">{team.team_name}</span>
        <span className="text-xs text-red-400 font-medium">{team.injury_count} afectado{team.injury_count !== 1 ? 's' : ''}</span>
      </div>
      <div className="flex flex-wrap gap-1">
        {team.players_affected.map((p) => (
          <span key={p} className="inline-block rounded bg-red-900/40 px-1.5 py-0.5 text-xs text-red-300">
            {p}
          </span>
        ))}
      </div>
      {(attackImpact || defenseImpact) && (
        <div className="flex gap-3 text-xs text-gray-400">
          {attackImpact && <span>Ataque: <span className="text-red-400">−{attackImpact}%</span></span>}
          {defenseImpact && <span>Defensa: <span className="text-red-400">+{defenseImpact}%</span></span>}
        </div>
      )}
    </div>
  )
}

function NewsRow({ item }: { item: NewsClaim }) {
  return (
    <tr className="border-t border-gray-800 hover:bg-gray-900">
      <td className="px-4 py-2 text-sm font-medium text-white">{item.player_name}</td>
      <td className="px-4 py-2 text-sm text-gray-300">{item.team_name}</td>
      <td className="px-4 py-2">
        <StatusBadge status={item.status} />
      </td>
      <td className="px-4 py-2 text-xs text-gray-400 max-w-xs">
        <span title={item.reason ?? ''} className="truncate block max-w-[200px]">
          {item.reason ?? '—'}
        </span>
      </td>
      <td className="px-4 py-2 text-xs">
        {item.confidence != null ? (
          <span className={item.confidence >= 0.7 ? 'text-green-400' : 'text-gray-400'}>
            {(item.confidence * 100).toFixed(0)}%
          </span>
        ) : '—'}
      </td>
      <td className="px-4 py-2 text-xs text-gray-400">
        {item.source_url ? (
          <a
            href={item.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:underline truncate block max-w-[120px]"
            title={item.source_url}
          >
            {item.source_name ?? new URL(item.source_url).hostname}
          </a>
        ) : (
          <span>{item.source_name ?? '—'}</span>
        )}
      </td>
      <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">
        {new Date(item.observed_at).toLocaleString()}
      </td>
    </tr>
  )
}

export default function News() {
  const [classificationFilter, setClassificationFilter] = useState('')
  const [teamFilter, setTeamFilter] = useState('')

  const triggerNews = useTriggerNews()
  const summary = useNewsSummary()
  const { data, isLoading, error } = useNews({
    classification: classificationFilter || undefined,
    team_id: teamFilter || undefined,
    limit: 100,
  })

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Noticias y Lesiones</h2>
          <p className="mt-1 text-sm text-gray-400">
            Análisis LLM de disponibilidad de jugadores para el Mundial 2026
            {data?.last_updated && (
              <span className="ml-2 text-gray-500">
                — Última actualización: {new Date(data.last_updated).toLocaleString()}
              </span>
            )}
          </p>
        </div>
        <button
          onClick={() => triggerNews.mutate()}
          disabled={triggerNews.isPending}
          className="rounded bg-blue-700 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
        >
          {triggerNews.isPending ? 'Encolando…' : 'Actualizar Noticias'}
        </button>
      </div>

      {triggerNews.isSuccess && (
        <div className="rounded bg-green-900/40 border border-green-800 px-4 py-2 text-sm text-green-300">
          Job de noticias encolado — id: {triggerNews.data.job_id}
        </div>
      )}

      {/* Team summaries with active injuries */}
      {summary.data && summary.data.teams.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3">
            Equipos con lesiones activas ({summary.data.teams.length})
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {summary.data.teams.map((team) => (
              <TeamSummaryCard key={team.team_id} team={team} />
            ))}
          </div>
        </div>
      )}

      {summary.data && summary.data.teams.length === 0 && (
        <div className="rounded-lg border border-gray-800 px-4 py-3 text-sm text-gray-400">
          Sin lesiones confirmadas en este momento.
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={classificationFilter}
          onChange={(e) => setClassificationFilter(e.target.value)}
          className="rounded border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-200"
        >
          {CLASSIFICATION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <input
          value={teamFilter}
          onChange={(e) => setTeamFilter(e.target.value.toUpperCase())}
          placeholder="Filtrar por equipo (ej: ARG)"
          className="rounded border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 w-48"
        />
        {(classificationFilter || teamFilter) && (
          <button
            onClick={() => { setClassificationFilter(''); setTeamFilter('') }}
            className="text-xs text-gray-400 hover:text-gray-200"
          >
            Limpiar filtros
          </button>
        )}
      </div>

      {/* Claims table */}
      {isLoading && <p className="text-gray-400">Cargando noticias…</p>}
      {error && <p className="text-red-400">Error al cargar noticias.</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-gray-900">
              <tr>
                {['Jugador', 'Equipo', 'Estado', 'Razón', 'Confianza', 'Fuente', 'Observado'].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-gray-500">
                    Sin noticias analizadas aún. Pulsa «Actualizar Noticias» para iniciar.
                  </td>
                </tr>
              ) : (
                data.items.map((item) => <NewsRow key={item.id} item={item} />)
              )}
            </tbody>
          </table>
          {data.total > data.items.length && (
            <div className="px-4 py-2 text-xs text-gray-500 border-t border-gray-800">
              Mostrando {data.items.length} de {data.total} registros
            </div>
          )}
        </div>
      )}
    </div>
  )
}
