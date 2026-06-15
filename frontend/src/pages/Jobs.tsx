import { useJobs, useCancelJob } from '../api/hooks'
import { hasAdminToken } from '../api/client'
import type { JobRecord } from '../types'

const CANCELLABLE: JobRecord['status'][] = ['enqueued', 'started']

function statusBadge(status: JobRecord['status']) {
  const map: Record<string, string> = {
    enqueued:  'bg-yellow-900 text-yellow-300',
    started:   'bg-blue-900 text-blue-300',
    completed: 'bg-green-900 text-green-300',
    failed:    'bg-red-900 text-red-400',
    cancelled: 'bg-gray-700 text-gray-400',
  }
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${map[status] ?? 'bg-gray-800 text-gray-400'}`}>
      {status}
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

export default function Jobs() {
  const { data, isLoading, error } = useJobs()
  const cancelJob = useCancelJob()

  function handleCancel(job: JobRecord) {
    if (!window.confirm(`¿Cancelar el job "${job.job_type}" (${job.id.slice(0, 8)}…)?`)) return
    cancelJob.mutate(job.id)
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Background Jobs</h2>
        <p className="mt-1 text-sm text-gray-400">
          Estado de tareas RQ — se actualiza cada 5 segundos
        </p>
      </div>

      {isLoading && <p className="text-gray-400">Cargando jobs…</p>}
      {error && <p className="text-red-400">Error al cargar jobs.</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-gray-900">
              <tr>
                {['Tipo', 'Estado', 'Progreso', 'Creado', 'Iniciado', 'Duración', 'Error', 'Acciones'].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {data.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-gray-500">
                    Sin jobs registrados.
                  </td>
                </tr>
              )}
              {data.map((job) => (
                <tr key={job.id} className="border-t border-gray-800 hover:bg-gray-900">
                  <td className="px-4 py-2 text-gray-200">{job.job_type}</td>
                  <td className="px-4 py-2">{statusBadge(job.status)}</td>
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
                  <td className="px-4 py-2 text-gray-400 whitespace-nowrap">
                    {fmtDate(job.created_at)}
                  </td>
                  <td className="px-4 py-2 text-gray-400 whitespace-nowrap">
                    {fmtDate(job.started_at)}
                  </td>
                  <td className="px-4 py-2 text-gray-400 whitespace-nowrap">
                    {duration(job.started_at, job.finished_at)}
                  </td>
                  <td className="px-4 py-2 max-w-xs">
                    {job.error_message ? (
                      <span className="text-red-400 text-xs truncate block" title={job.error_message}>
                        {job.error_message}
                      </span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {hasAdminToken && CANCELLABLE.includes(job.status) && (
                      <button
                        onClick={() => handleCancel(job)}
                        disabled={cancelJob.isPending}
                        className="rounded px-2 py-1 text-xs font-medium bg-red-900 text-red-300 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        Cancelar
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
