import { useEffect, useState } from 'react'
import { useJobs, useCancelJob, usePurgeJobs, useDeleteJobRecord } from '../api/hooks'
import { useAuth } from '../hooks/useAuth'
import type { JobRecord } from '../types'

const CANCELLABLE: JobRecord['status'][] = ['enqueued', 'started', 'running']

const MODEL_LABELS: Record<string, string> = {
  baseline: 'Baseline',
  elo: 'ELO',
  poisson: 'Poisson',
  poisson_context: 'Poisson+Ctx',
  ml_calibrated: 'ML Calibrado',
  consensus: 'Consenso',
}

const PIPELINE_LABELS: Record<string, string> = {
  full_refresh: 'Full Refresh',
  daily_update: 'Daily Update',
  nightly_update_and_simulations: 'Nightly (update + simulaciones)',
  news: 'Noticias',
  odds: 'Odds',
  ml_training: 'Entrenamiento ML',
}

export type JobOrigin = 'full_monte_carlo' | 'bracket' | 'pipeline' | 'other'

export interface ParsedJobType {
  origin: JobOrigin
  model: string | null
  label: string
}

/** Parse a job_type string into {origin, model, label} — covers both the
 * current naming convention (simulation_full_<model>, simulation_bracket_<model>)
 * and legacy values from before the Fase 1 normalization
 * (bare "simulation", "simulation_<model>", "bracket_<model>"). */
export function parseJobType(jobType: string): ParsedJobType {
  if (jobType in PIPELINE_LABELS) {
    return { origin: 'pipeline', model: null, label: PIPELINE_LABELS[jobType] }
  }

  if (jobType === 'simulation') {
    return { origin: 'full_monte_carlo', model: null, label: 'Simulación' }
  }

  let m = jobType.match(/^simulation_full_(.+)$/)
  if (m) {
    const model = m[1]
    return { origin: 'full_monte_carlo', model, label: `Monte Carlo — ${MODEL_LABELS[model] ?? model}` }
  }

  m = jobType.match(/^simulation_bracket_(.+)$/) || jobType.match(/^bracket_(.+)$/)
  if (m) {
    const model = m[1]
    return { origin: 'bracket', model, label: `Bracket vivo — ${MODEL_LABELS[model] ?? model}` }
  }

  // Legacy: simulation_<model> (pre Fase-1 naming, no full/bracket infix)
  m = jobType.match(/^simulation_(.+)$/)
  if (m) {
    const model = m[1]
    return { origin: 'full_monte_carlo', model, label: `Monte Carlo — ${MODEL_LABELS[model] ?? model}` }
  }

  return { origin: 'other', model: null, label: jobType }
}

function formatJobType(jobType: string): string {
  return parseJobType(jobType).label
}

const ORIGIN_BADGE: Record<JobOrigin, string> = {
  full_monte_carlo: 'bg-blue-900 text-blue-300',
  bracket: 'bg-purple-900 text-purple-300',
  pipeline: 'bg-gray-800 text-gray-300',
  other: 'bg-gray-800 text-gray-400',
}

const ORIGIN_LABEL: Record<JobOrigin, string> = {
  full_monte_carlo: 'Full MC',
  bracket: 'Bracket',
  pipeline: 'Pipeline',
  other: '—',
}

function JobOriginBadge({ jobType }: { jobType: string }) {
  const { origin, model } = parseJobType(jobType)
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${ORIGIN_BADGE[origin]}`}>
        {ORIGIN_LABEL[origin]}
      </span>
      {model && (
        <span className="rounded px-1.5 py-0.5 text-[10px] font-mono bg-indigo-950 text-indigo-300">
          {MODEL_LABELS[model] ?? model}
        </span>
      )}
    </span>
  )
}

// Thresholds for stuck detection
const STUCK_HEARTBEAT_STALE_MS = 60_000   // heartbeat older than 60 s → stuck
const STUCK_NO_HEARTBEAT_MS    = 30 * 60_000  // no heartbeat + running >30 min → stuck

function isActive(status: JobRecord['status']) {
  return status === 'running' || status === 'started'
}

function isStuck(job: JobRecord, now: number): boolean {
  if (!isActive(job.status)) return false

  const heartbeatStale = job.last_heartbeat
    ? now - new Date(job.last_heartbeat).getTime() > STUCK_HEARTBEAT_STALE_MS
    : false
  const runningTooLong = job.started_at
    ? now - new Date(job.started_at).getTime() > STUCK_NO_HEARTBEAT_MS
    : false

  return heartbeatStale || runningTooLong
}

function StatusIndicator({ job, now }: { job: JobRecord; now: number }) {
  const stuck = isStuck(job, now)
  const active = isActive(job.status)

  let dotClass = 'rounded-full bg-gray-500'
  let textClass = 'text-gray-400'
  let label: string = job.status
  let title: string | undefined

  if (active && stuck) {
    dotClass = 'rounded-full bg-amber-400 job-status-pulse-yellow'
    textClass = 'text-amber-300'
    label = 'posiblemente atascado'
    title = 'Sin heartbeat reciente o running por más de 30 minutos'
  } else if (active) {
    dotClass = 'rounded-full bg-green-400 job-status-pulse-green'
    textClass = 'text-green-300'
  } else if (job.status === 'failed') {
    dotClass = 'rounded-full bg-red-500'
    textClass = 'text-red-400'
  } else if (job.status === 'completed') {
    dotClass = 'rounded-full bg-green-500'
    textClass = 'text-green-300'
  } else if (job.status === 'enqueued') {
    dotClass = 'rounded-sm bg-gray-400'
    textClass = 'text-gray-300'
  } else if (job.status === 'cancelled') {
    dotClass = 'rounded-full bg-gray-600'
    textClass = 'text-gray-400'
  }

  return (
    <span
      title={title}
      className="inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium"
    >
      <span className={`h-2.5 w-2.5 ${dotClass}`} aria-hidden="true" />
      <span className={textClass}>{label}</span>
    </span>
  )
}

function fmtDate(d: string | null) {
  return d ? new Date(d).toLocaleString() : '—'
}

function duration(start: string | null, end: string | null): string {
  if (!start || !end) return '—'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60_000).toFixed(1)}min`
}

function elapsed(start: string | null, now: number): string {
  if (!start) return '—'
  const ms = now - new Date(start).getTime()
  if (ms < 0) return '—'
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function jobDuration(job: JobRecord, now: number): string {
  if (isActive(job.status)) return elapsed(job.started_at, now)
  return duration(job.started_at, job.finished_at)
}

export default function Jobs() {
  const { data, isLoading, error } = useJobs()
  const cancelJob = useCancelJob()
  const purgeJobs = usePurgeJobs()
  const deleteJobRecord = useDeleteJobRecord()
  const { data: authData } = useAuth()
  const isAdmin = authData?.authenticated === true
  const [now, setNow] = useState(() => Date.now())

  // Tick every second to update elapsed time and stuck detection
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1_000)
    return () => clearInterval(id)
  }, [])

  const finishedCount = data
    ? data.filter((j) => ['completed', 'failed', 'cancelled'].includes(j.status)).length
    : 0

  function handleCancel(job: JobRecord) {
    if (!window.confirm(`¿Cancelar el job "${job.job_type}" (${job.id.slice(0, 8)}…)?`)) return
    cancelJob.mutate(job.id)
  }

  function handleDelete(job: JobRecord) {
    if (!window.confirm(`¿Borrar este registro de job?`)) return
    deleteJobRecord.mutate(job.id)
  }

  return (
    <div className="p-4 sm:p-8 space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Background Jobs</h2>
          <p className="mt-1 text-sm text-gray-400">
            Estado de tareas RQ — lista cada 5 s, tiempo transcurrido cada 1 s
          </p>
        </div>
        {isAdmin && finishedCount > 0 && (
          <button
            onClick={() => {
              if (!window.confirm(`¿Borrar ${finishedCount} job(s) finalizado(s)? Esta acción no se puede deshacer.`)) return
              purgeJobs.mutate()
            }}
            disabled={purgeJobs.isPending}
            className="rounded px-3 py-1.5 text-xs font-medium bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors border border-gray-700 self-start"
          >
            {purgeJobs.isPending ? 'Borrando…' : `Limpiar finalizados (${finishedCount})`}
          </button>
        )}
      </div>

      {isLoading && <p className="text-gray-400">Cargando jobs…</p>}
      {error && <p className="text-red-400">Error al cargar jobs.</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-gray-900">
              <tr>
                {['Tipo', 'Origen', 'Estado', 'Progreso'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">{h}</th>
                ))}
                {['Creado', 'Iniciado', 'Duración', 'Error'].map((h) => (
                  <th key={h} className="hidden md:table-cell px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">{h}</th>
                ))}
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {data.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-gray-500">
                    Sin jobs registrados.
                  </td>
                </tr>
              )}
              {data.map((job) => (
                <tr key={job.id} className="border-t border-gray-800 hover:bg-gray-900">
                  <td className="px-4 py-2 text-gray-200">{formatJobType(job.job_type)}</td>
                  <td className="px-4 py-2">
                    <JobOriginBadge jobType={job.job_type} />
                  </td>
                  <td className="px-4 py-2">
                    <StatusIndicator job={job} now={now} />
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 rounded-full bg-gray-700 overflow-hidden">
                        <div
                          className="h-full bg-blue-500 rounded-full transition-all"
                          style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-400">
                        {Math.round((job.progress ?? 0) * 100)}%
                      </span>
                    </div>
                  </td>
                  <td className="hidden md:table-cell px-4 py-2 text-gray-400 whitespace-nowrap">
                    {fmtDate(job.created_at)}
                  </td>
                  <td className="hidden md:table-cell px-4 py-2 text-gray-400 whitespace-nowrap">
                    {fmtDate(job.started_at)}
                  </td>
                  <td className="hidden md:table-cell px-4 py-2 whitespace-nowrap font-mono text-xs">
                    <span className={isActive(job.status) ? (isStuck(job, now) ? 'text-amber-400' : 'text-green-300') : 'text-gray-400'}>
                      {jobDuration(job, now)}
                    </span>
                  </td>
                  <td className="hidden md:table-cell px-4 py-2 max-w-xs">
                    {job.error_message ? (
                      <span className="text-red-400 text-xs truncate block" title={job.error_message}>
                        {job.error_message}
                      </span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 whitespace-nowrap">
                    {isAdmin && CANCELLABLE.includes(job.status) && (
                      <button
                        onClick={() => handleCancel(job)}
                        disabled={cancelJob.isPending}
                        className="rounded px-2 py-1 text-xs font-medium bg-red-900 text-red-300 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        Cancelar
                      </button>
                    )}
                    {isAdmin && ['completed', 'failed', 'cancelled'].includes(job.status) && (
                      <button
                        onClick={() => handleDelete(job)}
                        disabled={deleteJobRecord.isPending}
                        className="rounded px-2 py-1 text-xs font-medium bg-gray-800 text-gray-500 hover:bg-gray-700 hover:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors ml-1"
                        title="Borrar registro"
                      >
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
