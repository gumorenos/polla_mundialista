import {
  useModelsComparison,
  useSimulations,
  useTriggerDailyUpdate,
  useTriggerFullRefresh,
} from '../api/hooks'
import { useAuth } from '../hooks/useAuth'
import type { ModelMetrics, TeamResult } from '../types'

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className="mt-1 text-2xl font-bold text-white">{value}</p>
    </div>
  )
}

function fmt(n: number | null | undefined) {
  if (n == null) return '—'
  return (n * 100).toFixed(1) + '%'
}

export default function Dashboard() {
  const { data: metrics, isLoading: metricsLoading } = useModelsComparison()
  const { data: sim } = useSimulations('poisson')
  const fullRefresh = useTriggerFullRefresh()
  const dailyUpdate = useTriggerDailyUpdate()
  const { data: authData } = useAuth()

  const bestModel: ModelMetrics | undefined = [...(metrics ?? [])].sort(
    (a, b) => (a.brier_score ?? 1) - (b.brier_score ?? 1),
  )[0]

  const top5: TeamResult[] = [...(sim?.team_results ?? [])]
    .sort((a, b) => b.win_tournament - a.win_tournament)
    .slice(0, 5)

  const noToken = authData?.authenticated !== true

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Oráculo Mundial 2026</h2>
          <p className="mt-1 text-sm text-gray-400">Vista general de predicciones</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          {noToken && (
            <p className="text-xs text-yellow-500">
              Sesión no activa — acciones admin deshabilitadas
            </p>
          )}
          <div className="flex gap-3">
            <button
              onClick={() => dailyUpdate.mutate()}
              disabled={dailyUpdate.isPending || noToken}
              title={noToken ? 'Inicia sesión para acciones admin' : undefined}
              className="rounded bg-gray-700 px-4 py-2 text-sm text-gray-200 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {dailyUpdate.isPending ? 'Encolando…' : 'Daily Update'}
            </button>
            <button
              onClick={() => fullRefresh.mutate()}
              disabled={fullRefresh.isPending || noToken}
              title={noToken ? 'Inicia sesión para acciones admin' : undefined}
              className="rounded bg-blue-700 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {fullRefresh.isPending ? 'Encolando…' : 'Full Refresh'}
            </button>
          </div>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Modelos evaluados" value={metricsLoading ? '…' : (metrics?.length ?? 0)} />
        <MetricCard
          label="Mejor modelo (Brier)"
          value={bestModel ? bestModel.model_name : '—'}
        />
        <MetricCard
          label="Brier score"
          value={bestModel ? (bestModel.brier_score?.toFixed(4) ?? '—') : '—'}
        />
        <MetricCard
          label="Simulación base"
          value={sim ? `${(sim.run.iterations / 1000).toFixed(0)}k iter.` : '—'}
        />
      </div>

      {/* Top 5 champion probabilities */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Top 5 — Probabilidad de campeonato (Poisson)
        </h3>
        {top5.length === 0 ? (
          <p className="text-sm text-gray-500">
            Sin datos. Ejecuta una simulación primero.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
                <th className="pb-2 font-medium">#</th>
                <th className="pb-2 font-medium">Selección</th>
                <th className="pb-2 font-medium text-right">Campeón</th>
                <th className="pb-2 font-medium text-right">Final</th>
                <th className="pb-2 font-medium text-right">Semi</th>
              </tr>
            </thead>
            <tbody>
              {top5.map((t, i) => (
                <tr key={t.team_id} className="border-b border-gray-800/50 hover:bg-gray-900">
                  <td className="py-2 text-gray-500">{i + 1}</td>
                  <td className="py-2 font-medium text-white">{t.team_name}</td>
                  <td className="py-2 text-right text-blue-400">{fmt(t.win_tournament)}</td>
                  <td className="py-2 text-right text-gray-300">{fmt(t.reach_final)}</td>
                  <td className="py-2 text-right text-gray-400">{fmt(t.reach_semi_final)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
