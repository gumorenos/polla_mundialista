import { useState } from 'react'
import {
  useAdminReset,
  useModelsComparison,
  useOddsValue,
  useRunSimulation,
  useSimulations,
  useTournamentNarrative,
  useTriggerDailyUpdate,
  useTriggerFullRefresh,
} from '../api/hooks'
import { useAuth } from '../hooks/useAuth'
import type { ModelMetrics, OddsValueTeam, TeamResult } from '../types'

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
  const adminReset = useAdminReset()
  const { data: authData } = useAuth()
  const runSim = useRunSimulation()

  const { data: oddsData } = useOddsValue()
  const top3Value: OddsValueTeam[] = [...(oddsData?.teams ?? [])]
    .filter((t) => t.signal !== 'fair')
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .slice(0, 3)

  const [showAnalysis, setShowAnalysis] = useState(false)
  const [showResetModal, setShowResetModal] = useState(false)
  const [resetMsg, setResetMsg] = useState<string | null>(null)
  const [simMsg, setSimMsg] = useState<string | null>(null)
  const [pendingSim, setPendingSim] = useState<string | null>(null)
  const runId = sim?.run.id ?? null
  const tournamentNarrative = useTournamentNarrative(showAnalysis ? runId : null)

  const bestModel: ModelMetrics | undefined = [...(metrics ?? [])].sort(
    (a, b) => (a.brier_score ?? 1) - (b.brier_score ?? 1),
  )[0]

  const top5: TeamResult[] = [...(sim?.team_results ?? [])]
    .sort((a, b) => b.win_tournament - a.win_tournament)
    .slice(0, 5)

  const noToken = authData?.authenticated !== true
  const isAdmin = !noToken

  function handleRunSim(modelName: string) {
    setPendingSim(modelName)
    setSimMsg(null)
    runSim.mutate({ model_name: modelName }, {
      onSuccess: () => {
        setSimMsg(`Simulación "${modelName}" encolada correctamente.`)
        setPendingSim(null)
      },
      onError: (err) => {
        setSimMsg(`Error: ${err.message}`)
        setPendingSim(null)
      },
    })
  }

  function handleReset() {
    setResetMsg('Reseteando base de datos…')
    adminReset.mutate(undefined, {
      onSuccess: () => {
        setShowResetModal(false)
        setResetMsg(null)
        setTimeout(() => window.location.reload(), 500)
      },
      onError: (err) => {
        setResetMsg(`Error: ${err.message}`)
      },
    })
  }

  return (
    <div className="p-4 sm:p-8 space-y-8">
      {/* Reset confirmation modal */}
      {showResetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-xl border border-red-800 bg-gray-900 p-6 space-y-4 shadow-2xl">
            <h3 className="text-lg font-bold text-red-400">⚠️ ADVERTENCIA</h3>
            <p className="text-sm text-gray-300">
              Esto eliminará todas las simulaciones, predicciones, evaluaciones y noticias.
              Los datos históricos de StatsBomb (Mundiales 2018/2022) se preservan.
            </p>
            <p className="text-sm font-semibold text-red-300">¿Continuar con el reset definitivo?</p>
            {resetMsg && (
              <p className={`text-sm ${resetMsg.startsWith('Error') ? 'text-red-400' : 'text-yellow-400'}`}>
                {resetMsg}
              </p>
            )}
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setShowResetModal(false); setResetMsg(null) }}
                disabled={adminReset.isPending}
                className="rounded px-4 py-2 text-sm bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                onClick={handleReset}
                disabled={adminReset.isPending}
                className="rounded px-4 py-2 text-sm bg-red-700 text-white hover:bg-red-600 disabled:opacity-50 font-semibold"
              >
                {adminReset.isPending ? 'Reseteando…' : 'Reset definitivo'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Oráculo Mundial 2026</h2>
          <p className="mt-1 text-sm text-gray-400">Vista general de predicciones</p>
        </div>
        <div className="flex flex-col gap-2 sm:items-end">
          {noToken && (
            <p className="text-xs text-yellow-500">
              Sesión no activa — acciones admin deshabilitadas
            </p>
          )}
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              onClick={() => dailyUpdate.mutate()}
              disabled={dailyUpdate.isPending || noToken}
              title={noToken ? 'Inicia sesión para acciones admin' : 'Actualiza resultados recientes, ELO, noticias y sanciones (sin simulaciones)'}
              className="rounded bg-gray-700 px-4 py-2 text-sm text-gray-200 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
            >
              {dailyUpdate.isPending ? 'Encolando…' : 'Daily Update'}
            </button>
            <button
              onClick={() => fullRefresh.mutate()}
              disabled={fullRefresh.isPending || noToken}
              title={noToken ? 'Inicia sesión para acciones admin' : 'Actualiza todos los datos históricos, ELO y modelos ML (sin simulaciones)'}
              className="rounded bg-blue-700 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
            >
              {fullRefresh.isPending ? 'Encolando…' : 'Full Refresh'}
            </button>
            {isAdmin && (
              <button
                onClick={() => setShowResetModal(true)}
                title="Resetear toda la base de datos (excepto StatsBomb)"
                className="rounded bg-red-800 px-4 py-2 text-sm text-white hover:bg-red-700 min-h-[44px]"
              >
                🗑️ Reset
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Simulations section */}
      {isAdmin && (
        <div className="rounded-lg border border-gray-700 bg-gray-900/50 p-4 space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">
              Simulaciones Monte Carlo
            </h3>
            <p className="mt-1 text-xs text-gray-500">
              Corre las simulaciones después de actualizar los datos con Full Refresh o Daily Update.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(['baseline', 'elo', 'poisson', 'poisson_context', 'ml_calibrated', 'consensus'] as const).map((model) => (
              <button
                key={model}
                onClick={() => handleRunSim(model)}
                disabled={pendingSim !== null}
                className="rounded bg-indigo-800 px-3 py-1.5 text-xs text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed font-mono"
              >
                {pendingSim === model ? 'Encolando…' : model}
              </button>
            ))}
          </div>
          {simMsg && (
            <p className={`text-xs ${simMsg.startsWith('Error') ? 'text-red-400' : 'text-green-400'}`}>
              {simMsg}
            </p>
          )}
        </div>
      )}

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
          <div className="overflow-x-auto"><table className="w-full text-sm">
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
          </table></div>
        )}
      </div>

      {/* Top value vs. market */}
      {top3Value.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-gray-300 uppercase tracking-wider">
            Mayor diferencia vs. mercado
          </h3>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {top3Value.map((t) => {
              const isValue = t.signal === 'value'
              return (
                <div
                  key={t.team_id}
                  className={`rounded-lg border px-4 py-3 ${
                    isValue
                      ? 'border-green-800/50 bg-green-950/30'
                      : 'border-red-800/50 bg-red-950/30'
                  }`}
                >
                  <p className="text-sm font-semibold text-white">{t.team_name}</p>
                  <p className={`text-xs font-mono font-bold mt-0.5 ${isValue ? 'text-green-400' : 'text-red-400'}`}>
                    {t.value >= 0 ? '+' : ''}{(t.value * 100).toFixed(1)}pp
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    Oráculo {(t.oraculo_prob * 100).toFixed(1)}% · Mercado {(t.market_prob * 100).toFixed(1)}%
                  </p>
                  <p className="text-xs text-gray-600">{t.bookmaker} · {t.best_odd.toFixed(2)}</p>
                </div>
              )
            })}
          </div>
          <p className="mt-2 text-xs text-gray-600">
            Las probabilidades del mercado son informativas. Esta aplicación no promueve ni facilita apuestas.
          </p>
        </div>
      )}

      {/* Tournament analysis (LLM) */}
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
              Análisis del Torneo
            </h3>
            {tournamentNarrative.data?.generated_at && (
              <p className="mt-0.5 text-xs text-gray-600">
                Generado: {new Date(tournamentNarrative.data.generated_at).toLocaleString()}
              </p>
            )}
          </div>
          <button
            onClick={() => setShowAnalysis(true)}
            disabled={noToken || !runId || showAnalysis}
            title={noToken ? 'Inicia sesión para generar análisis' : undefined}
            className="rounded bg-indigo-700 px-3 py-1.5 text-xs text-white hover:bg-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {tournamentNarrative.isLoading ? 'Generando…' : 'Generar análisis'}
          </button>
        </div>
        {tournamentNarrative.isLoading && (
          <div className="space-y-2 animate-pulse">
            {[1, 0.85, 0.7, 0.9, 0.6].map((w, i) => (
              <div key={i} className="h-3 rounded bg-gray-800" style={{ width: `${w * 100}%` }} />
            ))}
          </div>
        )}
        {!tournamentNarrative.isLoading && tournamentNarrative.data?.narrative && (
          <p className="text-sm leading-relaxed text-gray-300 whitespace-pre-wrap">
            {tournamentNarrative.data.narrative}
          </p>
        )}
        {!tournamentNarrative.isLoading && showAnalysis && tournamentNarrative.data?.narrative === null && (
          <p className="text-xs text-yellow-500">
            Análisis no disponible — configura OPENROUTER_API_KEY para activar.
          </p>
        )}
        {!showAnalysis && (
          <p className="text-xs text-gray-600">
            {noToken ? 'Inicia sesión para generar el análisis narrativo del torneo.' : 'Pulsa «Generar análisis» para obtener un resumen narrativo de los favoritos.'}
          </p>
        )}
      </div>
    </div>
  )
}
