import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNews, useNewsSummary, usePlayerForm, useSuspensions, useTriggerNews, useJobStatus } from '../api/hooks'
import type { NewsClaim, NewsTeamSummary, PlayerFormTeam, SuspensionTeamSummary } from '../types'

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

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[status] ?? 'bg-gray-800 text-gray-400'}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

function AgeBadge({ dateStr }: { dateStr: string | null }) {
  if (!dateStr) {
    return <span className="text-xs text-gray-600">Fecha desconocida</span>
  }
  const diffMs = Date.now() - new Date(dateStr).getTime()
  const diffDays = diffMs / 86_400_000
  const diffHours = Math.floor(diffMs / 3_600_000)

  if (diffDays < 2) {
    return (
      <span className="inline-block rounded px-1.5 py-0.5 text-xs bg-green-900/60 text-green-300">
        {diffHours}h
      </span>
    )
  }
  if (diffDays < 7) {
    return (
      <span className="inline-block rounded px-1.5 py-0.5 text-xs bg-yellow-900/60 text-yellow-300">
        {Math.floor(diffDays)}d
      </span>
    )
  }
  return (
    <span className="inline-flex gap-1 items-center flex-wrap">
      <span className="inline-block rounded px-1.5 py-0.5 text-xs bg-red-900/60 text-red-300">
        {Math.floor(diffDays)}d
      </span>
      <span className="inline-block rounded px-1.5 py-0.5 text-xs bg-red-900/60 text-red-300 font-medium">
        Antigua
      </span>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Team summary card
// ---------------------------------------------------------------------------

function TeamSummaryCard({ team }: { team: NewsTeamSummary }) {
  const attackImpact = team.attack_factor != null ? ((1 - team.attack_factor) * 100).toFixed(0) : null
  const defenseImpact = team.defense_factor != null ? ((team.defense_factor - 1) * 100).toFixed(0) : null

  return (
    <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-white text-sm">{team.team_name}</span>
        <span className="text-xs text-red-400 font-medium">
          {team.injury_count} afectado{team.injury_count !== 1 ? 's' : ''}
        </span>
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

// ---------------------------------------------------------------------------
// Suspension card
// ---------------------------------------------------------------------------

function SuspensionCard({ team }: { team: SuspensionTeamSummary }) {
  const attackImpact = team.attack_factor != null ? ((1 - team.attack_factor) * 100).toFixed(0) : null
  const defenseImpact = team.defense_factor != null ? ((team.defense_factor - 1) * 100).toFixed(0) : null

  return (
    <div className="rounded-lg border border-yellow-900/50 bg-yellow-950/20 p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-white text-sm">{team.team_name}</span>
        <span className="text-xs text-yellow-400 font-medium">
          {team.suspended_count} suspendido{team.suspended_count !== 1 ? 's' : ''}
        </span>
      </div>
      <div className="flex flex-wrap gap-1">
        {team.players_suspended.map((p) => (
          <span key={p} className="inline-flex items-center gap-1 rounded bg-yellow-900/40 px-1.5 py-0.5 text-xs text-yellow-300">
            🟨 {p}
          </span>
        ))}
      </div>
      {(attackImpact || defenseImpact) && (
        <div className="flex gap-3 text-xs text-gray-400">
          {attackImpact && <span>Ataque: <span className="text-yellow-400">−{attackImpact}%</span></span>}
          {defenseImpact && <span>Defensa: <span className="text-yellow-400">+{defenseImpact}%</span></span>}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Player form card
// ---------------------------------------------------------------------------

function PlayerFormCard({ team }: { team: PlayerFormTeam }) {
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900/60 p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-white text-sm">{team.team_name}</span>
        {team.in_form && (
          <span className="inline-block rounded px-2 py-0.5 text-xs font-medium bg-green-900/60 text-green-300">
            🔥 En racha
          </span>
        )}
        {team.out_of_form && (
          <span className="inline-block rounded px-2 py-0.5 text-xs font-medium bg-orange-900/60 text-orange-300">
            📉 Irregular
          </span>
        )}
        {!team.in_form && !team.out_of_form && (
          <span className="inline-block rounded px-2 py-0.5 text-xs font-medium bg-gray-800 text-gray-400">
            Regular
          </span>
        )}
      </div>
      <p className="text-xs text-gray-400">
        Jugador clave: <span className="text-gray-200 font-medium">{team.key_player}</span>
      </p>
      <p className="text-xs text-gray-500">
        Últimos {team.matches_used} partidos disponibles:{' '}
        <span className="text-gray-300">{team.avg_xg.toFixed(2)} xG promedio</span>
        {' · '}forma {team.form_rating.toFixed(2)}x
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Table row
// ---------------------------------------------------------------------------

function NewsRow({ item }: { item: NewsClaim }) {
  return (
    <tr className="border-t border-gray-800 hover:bg-gray-900/50">
      {/* Jugador — always visible */}
      <td className="px-3 py-2 text-sm font-medium text-white whitespace-nowrap">
        {item.player_name}
      </td>

      {/* Equipo — always visible */}
      <td className="px-3 py-2 text-sm text-gray-300 whitespace-nowrap">
        {item.team_name}
      </td>

      {/* Estado — always visible */}
      <td className="px-3 py-2">
        <StatusBadge status={item.status} />
      </td>

      {/* Razón (titular noticia) — hidden on mobile */}
      <td className="hidden md:table-cell px-3 py-2 text-xs text-gray-400 max-w-0">
        <div
          className="line-clamp-2 leading-snug"
          title={item.reason ?? ''}
        >
          {item.reason ?? '—'}
        </div>
      </td>

      {/* Fecha publicación — always visible */}
      <td className="px-3 py-2 whitespace-nowrap">
        <AgeBadge dateStr={item.published_at} />
      </td>

      {/* Fuente — hidden on mobile */}
      <td className="hidden md:table-cell px-3 py-2 text-xs text-gray-400 whitespace-nowrap">
        {item.source_url ? (
          <a
            href={item.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:underline"
            title={item.source_url}
          >
            {item.source_name ?? new URL(item.source_url).hostname}
          </a>
        ) : (
          <span>{item.source_name ?? '—'}</span>
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function News() {
  const [classificationFilter, setClassificationFilter] = useState('')
  const [teamFilter, setTeamFilter] = useState('')
  // FIX 6: track the job enqueued by "Actualizar Noticias" to invalidate on complete
  const [trackedJobId, setTrackedJobId] = useState<string | null>(null)

  const qc = useQueryClient()
  const triggerNews = useTriggerNews()
  const jobStatus = useJobStatus(trackedJobId)
  const summary = useNewsSummary()
  const suspensions = useSuspensions()
  const playerForm = usePlayerForm()
  const { data, isLoading, error } = useNews({
    classification: classificationFilter || undefined,
    team_id: teamFilter || undefined,
    limit: 100,
  })

  // Start tracking job right after trigger succeeds
  useEffect(() => {
    if (triggerNews.isSuccess && triggerNews.data?.job_id) {
      setTrackedJobId(triggerNews.data.job_id)
    }
  }, [triggerNews.isSuccess, triggerNews.data])

  // Invalidate news queries on job completion; clear tracking on terminal state
  useEffect(() => {
    if (!trackedJobId || !jobStatus.data) return
    const s = jobStatus.data.status
    if (s === 'completed') {
      qc.invalidateQueries({ queryKey: ['news'] })
      setTrackedJobId(null)
    } else if (s === 'failed' || s === 'cancelled') {
      setTrackedJobId(null)
    }
  }, [jobStatus.data?.status, trackedJobId, qc])

  const isJobRunning = !!trackedJobId && (
    jobStatus.data?.status === 'enqueued' ||
    jobStatus.data?.status === 'started' ||
    jobStatus.data?.status === 'running'
  )
  const jobFailed = !trackedJobId && triggerNews.isSuccess && (
    jobStatus.data?.status === 'failed' || jobStatus.data?.status === 'cancelled'
  )

  return (
    <div className="p-4 sm:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
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
          disabled={triggerNews.isPending || isJobRunning}
          className="rounded bg-blue-700 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50 min-h-[44px] sm:w-auto"
        >
          {triggerNews.isPending ? 'Encolando…' : isJobRunning ? 'Actualizando…' : 'Actualizar Noticias'}
        </button>
      </div>

      {isJobRunning && (
        <div className="rounded bg-blue-900/40 border border-blue-800 px-4 py-2 text-sm text-blue-300">
          Análisis de noticias en progreso — job: {trackedJobId}
        </div>
      )}
      {jobFailed && (
        <div className="rounded bg-red-900/40 border border-red-800 px-4 py-2 text-sm text-red-300">
          La actualización de noticias falló o fue cancelada.
        </div>
      )}
      {triggerNews.isSuccess && !trackedJobId && !jobFailed && (
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

      {/* Suspended players */}
      {suspensions.data && suspensions.data.teams.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3">
            Jugadores suspendidos — WC 2026 ({suspensions.data.teams.length} equipos)
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {suspensions.data.teams.map((team) => (
              <SuspensionCard key={team.team_id} team={team} />
            ))}
          </div>
        </div>
      )}

      {/* Player form — StatsBomb xG */}
      {playerForm.data && playerForm.data.teams.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3">
            Forma individual — jugador clave ({playerForm.data.teams.length} equipos con datos StatsBomb)
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {playerForm.data.teams.map((team) => (
              <PlayerFormCard key={team.team_id} team={team} />
            ))}
          </div>
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
          <table className="w-full table-fixed text-sm">
            <colgroup>
              <col className="w-[18%]" />   {/* Jugador */}
              <col className="w-[13%]" />   {/* Equipo */}
              <col className="w-[10%]" />   {/* Estado */}
              <col className="hidden md:table-column w-[34%]" />  {/* Razón */}
              <col className="w-[10%]" />   {/* Fecha */}
              <col className="hidden md:table-column w-[15%]" />  {/* Fuente */}
            </colgroup>
            <thead className="bg-gray-900">
              <tr>
                <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Jugador
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Equipo
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Estado
                </th>
                <th className="hidden md:table-cell px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Razón
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Publicado
                </th>
                <th className="hidden md:table-cell px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Fuente
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-500">
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
