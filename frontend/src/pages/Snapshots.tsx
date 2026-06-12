import { useSnapshots } from '../api/hooks'

function badge(trigger: string | null) {
  const map: Record<string, string> = {
    full_refresh: 'bg-blue-900 text-blue-300',
    daily_update: 'bg-teal-900 text-teal-300',
    manual: 'bg-purple-900 text-purple-300',
  }
  const cls = (trigger && map[trigger]) ?? 'bg-gray-800 text-gray-400'
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {trigger ?? 'unknown'}
    </span>
  )
}

export default function Snapshots() {
  const { data, isLoading, error } = useSnapshots()

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Snapshots</h2>
        <p className="mt-1 text-sm text-gray-400">
          Instantáneas trazables de simulaciones guardadas por el pipeline
        </p>
      </div>

      {isLoading && <p className="text-gray-400">Cargando snapshots…</p>}
      {error && <p className="text-red-400">Error al cargar snapshots.</p>}

      {data && data.length === 0 && (
        <p className="text-gray-500">
          Sin snapshots. Ejecuta un full-refresh para generar el primero.
        </p>
      )}

      {data && data.length > 0 && (
        <div className="space-y-3">
          {data.map((s) => (
            <div
              key={s.id}
              className="rounded-lg border border-gray-800 bg-gray-900 px-5 py-4 flex items-start justify-between gap-4"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-white truncate">
                    {s.label ?? s.id}
                  </span>
                  {badge(s.trigger)}
                </div>
                {s.description && (
                  <p className="mt-1 text-sm text-gray-400 truncate">{s.description}</p>
                )}
                {s.simulation_run_id && (
                  <p className="mt-1 text-xs text-gray-600 font-mono truncate">
                    run: {s.simulation_run_id}
                  </p>
                )}
              </div>
              <div className="shrink-0 text-xs text-gray-500 whitespace-nowrap">
                {new Date(s.created_at).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
