import { useState } from 'react'
import { useRunSimulation, useSimulations, useSimulationComparison } from '../api/hooks'
import type { TeamResult, SimulationComparisonTeam } from '../types'

const MODELS = ['baseline', 'elo', 'poisson', 'poisson_context', 'ml_calibrated']

const MODEL_LABELS: Record<string, string> = {
  baseline: 'Baseline',
  elo: 'ELO',
  poisson: 'Poisson',
  poisson_context: 'Poisson+Ctx',
  ml_calibrated: 'ML Calibrado',
}

function fmt(n: number) {
  return (n * 100).toFixed(1) + '%'
}

function TeamTable({ rows }: { rows: TeamResult[] }) {
  const sorted = [...rows].sort((a, b) => b.win_tournament - a.win_tournament)
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm">
        <thead className="bg-gray-900">
          <tr>
            {['#', 'Selección', 'Campeón', 'Final', 'Semi', 'Cuartos', 'Octavos', 'Clasifica'].map(
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
          {sorted.map((t, i) => (
            <tr key={t.team_id} className="border-t border-gray-800 hover:bg-gray-900">
              <td className="px-4 py-2 text-gray-500">{i + 1}</td>
              <td className="px-4 py-2 font-medium text-white">{t.team_name}</td>
              <td className="px-4 py-2 text-blue-400">{fmt(t.win_tournament)}</td>
              <td className="px-4 py-2 text-gray-300">{fmt(t.reach_final)}</td>
              <td className="px-4 py-2 text-gray-300">{fmt(t.reach_semi_final)}</td>
              <td className="px-4 py-2 text-gray-400">{fmt(t.reach_quarter_final)}</td>
              <td className="px-4 py-2 text-gray-400">{fmt(t.reach_round_of_16)}</td>
              <td className="px-4 py-2 text-gray-400">{fmt(t.qualify)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ComparisonTable({ teams, models }: { teams: SimulationComparisonTeam[]; models: string[] }) {
  const [sortKey, setSortKey] = useState<string>('avg')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  function handleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  function arrow(key: string) {
    if (sortKey !== key) return <span className="text-gray-600 ml-1">↕</span>
    return <span className="ml-1">{sortDir === 'desc' ? '↓' : '↑'}</span>
  }

  const teamsWithAvg = teams.map((team) => {
    const vals = models.map((m) => team[m as keyof SimulationComparisonTeam] as number | null)
    const present = vals.filter((v): v is number => v !== null)
    const avg = present.length > 0 ? present.reduce((a, b) => a + b, 0) / present.length : null
    return { team, vals, avg }
  })

  const sorted = [...teamsWithAvg].sort((a, b) => {
    let va: number | string | null
    let vb: number | string | null
    if (sortKey === 'name') {
      va = a.team.team_name
      vb = b.team.team_name
      return sortDir === 'asc'
        ? String(va).localeCompare(String(vb))
        : String(vb).localeCompare(String(va))
    } else if (sortKey === 'avg') {
      va = a.avg
      vb = b.avg
    } else {
      va = a.team[sortKey as keyof SimulationComparisonTeam] as number | null
      vb = b.team[sortKey as keyof SimulationComparisonTeam] as number | null
    }
    if (va === null && vb === null) return 0
    if (va === null) return 1
    if (vb === null) return -1
    return sortDir === 'desc' ? (vb as number) - (va as number) : (va as number) - (vb as number)
  })

  const thClass = 'px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400 cursor-pointer select-none hover:text-gray-200'

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm">
        <thead className="bg-gray-900">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">#</th>
            <th className={thClass} onClick={() => handleSort('name')}>Selección{arrow('name')}</th>
            {models.map((m) => (
              <th key={m} className={thClass} onClick={() => handleSort(m)}>
                {MODEL_LABELS[m] ?? m}{arrow(m)}
              </th>
            ))}
            <th className={thClass} onClick={() => handleSort('avg')}>Promedio{arrow('avg')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(({ team, vals, avg }, i) => {
            const presentVals = vals.filter((v): v is number => v !== null)
            const max = presentVals.length > 0 ? Math.max(...presentVals) : null
            const min = presentVals.length > 0 ? Math.min(...presentVals) : null

            return (
              <tr key={team.team_id} className="border-t border-gray-800 hover:bg-gray-900">
                <td className="px-4 py-2 text-gray-500">{i + 1}</td>
                <td className="px-4 py-2 font-medium text-white">{team.team_name}</td>
                {vals.map((val, mi) => {
                  const isMax = val !== null && val === max
                  const isMin = val !== null && val === min && presentVals.length > 1
                  return (
                    <td
                      key={models[mi]}
                      className={`px-4 py-2 font-mono text-xs ${
                        val === null
                          ? 'text-gray-600'
                          : isMax
                          ? 'text-green-400 font-bold'
                          : isMin
                          ? 'text-red-400'
                          : 'text-gray-300'
                      }`}
                    >
                      {val === null ? '—' : fmt(val)}
                    </td>
                  )
                })}
                <td className="px-4 py-2 font-mono text-xs text-blue-300">
                  {avg === null ? '—' : fmt(avg)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function Simulations() {
  const [tab, setTab] = useState<'individual' | 'comparar'>('individual')
  const [model, setModel] = useState('poisson')
  const { data, isLoading, error } = useSimulations(model)
  const runSim = useRunSimulation()
  const comparison = useSimulationComparison()

  const modelsWithData = comparison.data
    ? comparison.data.models.filter((m) =>
        comparison.data!.teams.some((t) => t[m as keyof SimulationComparisonTeam] !== null),
      )
    : []

  function handleRun() {
    runSim.mutate({ model_name: model })
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Simulaciones Monte Carlo</h2>
          <p className="mt-1 text-sm text-gray-400">
            Últimos resultados por modelo — 30,000 iteraciones
          </p>
        </div>
        {tab === 'individual' && (
          <div className="flex gap-3">
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200"
            >
              {MODELS.map((m) => (
                <option key={m} value={m}>
                  {MODEL_LABELS[m] ?? m}
                </option>
              ))}
            </select>
            <button
              onClick={handleRun}
              disabled={runSim.isPending}
              className="rounded bg-blue-700 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
            >
              {runSim.isPending ? 'Encolando…' : 'Simular'}
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800">
        {(['individual', 'comparar'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? 'border-b-2 border-blue-500 text-blue-400'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {t === 'individual' ? 'Por modelo' : 'Comparar modelos'}
          </button>
        ))}
      </div>

      {/* Individual model view */}
      {tab === 'individual' && (
        <>
          {runSim.isSuccess && (
            <div className="rounded bg-green-900/40 border border-green-800 px-4 py-2 text-sm text-green-300">
              Simulación encolada — job_id: {runSim.data.job_id}
            </div>
          )}

          {isLoading && <p className="text-gray-400">Cargando resultados…</p>}
          {error && (
            <p className="text-yellow-400">
              Sin simulación completada para el modelo «{MODEL_LABELS[model] ?? model}». Pulsa «Simular» para iniciar una.
            </p>
          )}

          {data && (
            <>
              <div className="flex gap-6 text-sm text-gray-400">
                <span>
                  Iteraciones: <span className="text-white">{data.run.iterations.toLocaleString()}</span>
                </span>
                <span>
                  Estado: <span className="text-white">{data.run.status}</span>
                </span>
                <span>
                  Ejecutado:{' '}
                  <span className="text-white">
                    {data.run.finished_at
                      ? new Date(data.run.finished_at).toLocaleString()
                      : '—'}
                  </span>
                </span>
              </div>
              <TeamTable rows={data.team_results} />
            </>
          )}
        </>
      )}

      {/* Comparison view */}
      {tab === 'comparar' && (
        <>
          {comparison.isLoading && <p className="text-gray-400">Cargando comparación…</p>}
          {comparison.error && (
            <p className="text-yellow-400">Error al cargar la comparación.</p>
          )}
          {comparison.data && modelsWithData.length < 2 && (
            <p className="text-yellow-400">
              Se necesitan al menos 2 modelos con simulaciones completadas para comparar.
              Actualmente hay {modelsWithData.length}.
            </p>
          )}
          {comparison.data && modelsWithData.length >= 2 && (
            <>
              <div className="text-sm text-gray-400">
                Modelos disponibles:{' '}
                {modelsWithData.map((m) => (
                  <span key={m} className="inline-block mr-2 px-2 py-0.5 rounded bg-gray-800 text-gray-200 text-xs">
                    {MODEL_LABELS[m] ?? m}
                  </span>
                ))}
                <span className="ml-2">— % campeón por equipo. Verde = más alto, Rojo = más bajo.</span>
              </div>
              <ComparisonTable teams={comparison.data.teams} models={comparison.data.models} />
            </>
          )}
        </>
      )}
    </div>
  )
}
