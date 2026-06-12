import { useState } from 'react'
import { useRunSimulation, useSimulations } from '../api/hooks'
import type { TeamResult } from '../types'

const MODELS = ['baseline', 'elo', 'poisson', 'poisson_context', 'ml_calibrated']

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

export default function Simulations() {
  const [model, setModel] = useState('poisson')
  const { data, isLoading, error } = useSimulations(model)
  const runSim = useRunSimulation()

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
        <div className="flex gap-3">
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200"
          >
            {MODELS.map((m) => (
              <option key={m} value={m}>
                {m}
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
      </div>

      {runSim.isSuccess && (
        <div className="rounded bg-green-900/40 border border-green-800 px-4 py-2 text-sm text-green-300">
          Simulación encolada — job_id: {runSim.data.job_id}
        </div>
      )}

      {isLoading && <p className="text-gray-400">Cargando resultados…</p>}
      {error && (
        <p className="text-yellow-400">
          Sin simulación completada para el modelo «{model}». Pulsa «Simular» para iniciar una.
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
    </div>
  )
}
