import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table'
import { useState } from 'react'
import {
  BarChart, Bar,
  LineChart, Line,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  XAxis, YAxis,
  Tooltip, Legend,
  ResponsiveContainer, Cell,
} from 'recharts'
import { useConsensusWeights, useEvaluationRadar, useFavoriteHistory, useModelsComparison, useShapGlobal } from '../api/hooks'
import type { ModelMetrics } from '../types'

const col = createColumnHelper<ModelMetrics>()

function fmtNum(n: number | null, digits = 4): string {
  return n == null ? '—' : n.toFixed(digits)
}

const columns = [
  col.accessor('model_name', {
    header: 'Modelo',
    cell: (i) => <span className="font-medium text-white">{i.getValue()}</span>,
  }),
  col.accessor('brier_score', {
    header: 'Brier ↓',
    cell: (i) => fmtNum(i.getValue()),
  }),
  col.accessor('log_loss', {
    header: 'Log-Loss ↓',
    cell: (i) => fmtNum(i.getValue()),
  }),
  col.accessor('rps', {
    header: 'RPS ↓',
    cell: (i) => fmtNum(i.getValue()),
  }),
  col.accessor('accuracy', {
    header: 'Accuracy ↑',
    cell: (i) => {
      const v = i.getValue()
      return v == null ? '—' : (v * 100).toFixed(1) + '%'
    },
  }),
  col.accessor('total_predictions', {
    header: 'Predicciones',
    cell: (i) => i.getValue().toLocaleString(),
  }),
]

// ---------------------------------------------------------------------------
// SHAP global importance chart
// ---------------------------------------------------------------------------

const SHAP_COLORS = [
  '#3b82f6', '#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd',
  '#ddd6fe', '#e0e7ff', '#c7d2fe', '#a5b4fc', '#818cf8',
]

function ShapGlobalChart() {
  const { data, isLoading, error } = useShapGlobal()

  if (isLoading) return <p className="text-sm text-gray-400">Cargando SHAP…</p>
  if (error) {
    return (
      <p className="text-sm text-yellow-500">
        SHAP no disponible — entrena el modelo ML para ver la importancia de features.
      </p>
    )
  }
  if (!data) return null

  // Recharts needs the longest label to determine left margin
  const chartData = data.features.map((f) => ({
    label: f.label,
    importance: parseFloat((f.importance * 100).toFixed(3)),
  }))

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
          Importancia global de features — ML Calibrado ({data.algorithm})
        </h3>
        <p className="mt-1 text-xs text-gray-500">
          Contribución media |SHAP| de cada variable al predecir victoria del equipo local.
        </p>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 0, right: 20, bottom: 0, left: 160 }}
          >
            <XAxis
              type="number"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(v) => `${v.toFixed(2)}`}
              axisLine={{ stroke: '#374151' }}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="label"
              tick={{ fill: '#d1d5db', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={155}
            />
            <Tooltip
              contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6 }}
              labelStyle={{ color: '#e5e7eb', fontWeight: 600, marginBottom: 4 }}
              formatter={(v: number) => [`${v.toFixed(3)}`, 'Importancia SHAP']}
            />
            <Bar dataKey="importance" radius={[0, 3, 3, 0]}>
              {chartData.map((_, i) => (
                <Cell key={i} fill={SHAP_COLORS[i % SHAP_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Consensus weights chart
// ---------------------------------------------------------------------------

const MODEL_DISPLAY: Record<string, string> = {
  baseline: 'Baseline',
  elo: 'ELO',
  poisson: 'Poisson',
  poisson_context: 'Poisson+Ctx',
  ml_calibrated: 'ML Calibrado',
}

function ConsensusWeightsChart() {
  const { data, isLoading, error } = useConsensusWeights()

  if (isLoading) return <p className="text-sm text-gray-400">Cargando pesos del ensemble…</p>
  if (error) return null
  if (!data) return null

  const chartData = Object.entries(data.weights)
    .map(([model, weight]) => ({
      model: MODEL_DISPLAY[model] ?? model,
      weight: parseFloat((weight * 100).toFixed(2)),
      brier: data.brier_scores[model] != null ? data.brier_scores[model].toFixed(4) : '—',
    }))
    .sort((a, b) => b.weight - a.weight)

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-indigo-400">
          ⚖️ Pesos del Ensemble Consenso
        </h3>
        <p className="mt-1 text-xs text-gray-500">
          {data.note}
        </p>
      </div>
      <div className="rounded-lg border border-indigo-900/50 bg-indigo-950/20 p-4">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 0, right: 60, bottom: 0, left: 100 }}
          >
            <XAxis
              type="number"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(v) => `${v.toFixed(1)}%`}
              axisLine={{ stroke: '#374151' }}
              tickLine={false}
              domain={[0, 'auto']}
            />
            <YAxis
              type="category"
              dataKey="model"
              tick={{ fill: '#d1d5db', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={95}
            />
            <Tooltip
              contentStyle={{ background: '#111827', border: '1px solid #4f46e5', borderRadius: 6 }}
              labelStyle={{ color: '#a5b4fc', fontWeight: 600, marginBottom: 4 }}
              formatter={(v: number, _name: string, props: { payload?: { brier: string } }) => [
                `${v.toFixed(2)}% (Brier: ${props.payload?.brier ?? '—'})`,
                'Peso ensemble',
              ]}
            />
            <Bar dataKey="weight" radius={[0, 3, 3, 0]} fill="#6366f1" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Favorite evolution chart (Parte 3)
// ---------------------------------------------------------------------------

const FAVORITE_MODELS = ['baseline', 'elo', 'poisson', 'poisson_context', 'ml_calibrated', 'consensus']

const FAVORITE_MODEL_COLORS: Record<string, string> = {
  baseline:        '#6b7280',
  elo:             '#3b82f6',
  poisson:         '#10b981',
  poisson_context: '#8b5cf6',
  ml_calibrated:   '#f59e0b',
  consensus:       '#6366f1',
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('es-ES', { month: 'short', day: 'numeric' })
}

function FavoriteModelChart({ model }: { model: string }) {
  const { data, isLoading } = useFavoriteHistory(model)

  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-800 px-4 py-4 animate-pulse text-xs text-gray-600 text-center">
        Cargando…
      </div>
    )
  }

  if (!data || data.history.length === 0) {
    return (
      <div className="rounded-lg border border-gray-800 px-4 py-3 text-xs text-gray-600 text-center">
        Necesitas ≥2 simulaciones para ver la evolución.
      </div>
    )
  }

  const chartData = data.history.map((p) => ({
    date: fmtDate(p.created_at),
    team: p.team_name,
    prob: parseFloat((p.champion_prob * 100).toFixed(2)),
  }))

  // Detect leader changes
  const leaderChanged = new Set(data.history.map((p) => p.team_id)).size > 1
  const currentLeader = data.history[data.history.length - 1]
  const color = FAVORITE_MODEL_COLORS[model] ?? '#3b82f6'

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold" style={{ color }}>
          {MODEL_DISPLAY[model] ?? model}
        </span>
        <span className="text-xs text-gray-500">
          Favorito actual: <span className="text-gray-300 font-medium">{currentLeader.team_name}</span>
          {leaderChanged && (
            <span className="ml-2 rounded px-1.5 py-0.5 bg-yellow-900/40 text-yellow-400 text-xs">
              ⚡ cambió
            </span>
          )}
        </span>
      </div>
      <div className="rounded-lg border border-gray-800 overflow-hidden">
        <ResponsiveContainer width="100%" height={150}>
          <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <XAxis
              dataKey="date"
              tick={{ fill: '#6b7280', fontSize: 9 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => v.toFixed(0) + '%'}
              tick={{ fill: '#6b7280', fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              width={34}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 10 }}
              formatter={(v: number, _: string, props: { payload?: { team: string } }) => [
                `${v.toFixed(1)}% (${props.payload?.team ?? ''})`,
                '% campeón',
              ]}
              labelFormatter={(l) => l}
            />
            <Line
              type="monotone"
              dataKey="prob"
              stroke={color}
              strokeWidth={2}
              dot={{ r: 3, fill: color }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function FavoriteEvolutionSection() {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
          Cómo ha cambiado el favorito
        </h3>
        <p className="mt-1 text-xs text-gray-500">
          Probabilidad del equipo líder en cada simulación completada, por modelo.
          Un ⚡ indica que el favorito cambió entre simulaciones.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {FAVORITE_MODELS.map((m) => (
          <FavoriteModelChart key={m} model={m} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Radar chart — visual model comparison
// ---------------------------------------------------------------------------

const RADAR_COLORS: Record<string, string> = {
  baseline:        '#6b7280',
  elo:             '#3b82f6',
  poisson:         '#22c55e',
  poisson_context: '#facc15',
  ml_calibrated:   '#a855f7',
}

function ModelRadarChart() {
  const { data, isLoading, error } = useEvaluationRadar()
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  if (isLoading) return <p className="text-sm text-gray-400">Cargando radar…</p>
  if (error) {
    return (
      <p className="text-sm text-yellow-500">
        Radar no disponible — ejecuta un full-refresh para generar evaluaciones.
      </p>
    )
  }
  if (!data || Object.keys(data.models).length === 0) {
    return (
      <p className="text-sm text-gray-500">
        Sin evaluaciones. Ejecuta un full-refresh para ver el radar.
      </p>
    )
  }

  // Build one data point per metric axis
  const chartData = data.metrics.map((metricLabel, mi) => {
    const point: Record<string, string | number> = { metric: metricLabel }
    for (const [model, vals] of Object.entries(data.models)) {
      point[model] = vals[mi]
    }
    return point
  })

  const modelList = Object.keys(data.models)

  function toggleModel(model: string) {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(model)) next.delete(model)
      else next.add(model)
      return next
    })
  }

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
          Comparación visual de rendimiento
        </h3>
        <p className="mt-1 text-xs text-gray-500">
          Valores normalizados: en todos los ejes, más lejos del centro es mejor.
          Haz clic en la leyenda para mostrar/ocultar modelos.
        </p>
      </div>

      {/* Clickable legend */}
      <div className="flex flex-wrap gap-3">
        {modelList.map((model) => {
          const color = RADAR_COLORS[model] ?? '#9ca3af'
          const isHidden = hidden.has(model)
          return (
            <button
              key={model}
              onClick={() => toggleModel(model)}
              className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-opacity ${
                isHidden ? 'opacity-30' : 'opacity-100'
              }`}
            >
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: color }}
              />
              <span className="text-gray-300">{MODEL_DISPLAY[model] ?? model}</span>
            </button>
          )
        })}
      </div>

      <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
        <ResponsiveContainer width="100%" height={320}>
          <RadarChart data={chartData} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
            <PolarGrid stroke="#374151" />
            <PolarAngleAxis
              dataKey="metric"
              tick={{ fill: '#d1d5db', fontSize: 12, fontWeight: 500 }}
            />
            <PolarRadiusAxis
              angle={90}
              domain={[0, 1]}
              tick={{ fill: '#6b7280', fontSize: 10 }}
              tickCount={4}
              axisLine={false}
            />
            {modelList.map((model) => {
              if (hidden.has(model)) return null
              const color = RADAR_COLORS[model] ?? '#9ca3af'
              return (
                <Radar
                  key={model}
                  name={MODEL_DISPLAY[model] ?? model}
                  dataKey={model}
                  stroke={color}
                  fill={color}
                  fillOpacity={0.08}
                  strokeWidth={2}
                  dot={{ r: 3, fill: color }}
                />
              )
            })}
            <Tooltip
              contentStyle={{
                background: '#111827',
                border: '1px solid #374151',
                borderRadius: 6,
                fontSize: 11,
              }}
              formatter={(value: number, name: string, props: { payload?: Record<string, number> }) => {
                // Find metric index from the current axis label
                const metricLabel = (props.payload as Record<string, string> | undefined)?.metric ?? ''
                const mi = data.metrics.indexOf(metricLabel)
                const rawVal = mi >= 0 ? (data.raw[name]?.[mi] ?? null) : null
                const rawStr = rawVal != null ? ` (raw: ${rawVal.toFixed(4)})` : ''
                return [`${value.toFixed(3)}${rawStr}`, MODEL_DISPLAY[name] ?? name]
              }}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Models() {
  const { data, isLoading, error } = useModelsComparison()
  const [sorting, setSorting] = useState<SortingState>([{ id: 'brier_score', desc: false }])

  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div className="p-4 sm:p-8 space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">Comparación de modelos</h2>
        <p className="mt-1 text-sm text-gray-400">
          Métricas de evaluación walk-forward por modelo
        </p>
      </div>

      {isLoading && <p className="text-gray-400">Cargando métricas…</p>}
      {error && (
        <p className="text-red-400">
          Error al cargar métricas. ¿Ejecutaste full-refresh?
        </p>
      )}

      {!isLoading && !error && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-gray-900">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => (
                    <th
                      key={h.id}
                      onClick={h.column.getToggleSortingHandler()}
                      className="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400 hover:text-gray-200 select-none"
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getIsSorted() === 'asc' && ' ▲'}
                      {h.column.getIsSorted() === 'desc' && ' ▼'}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-t border-gray-800 hover:bg-gray-900 transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3 text-gray-300">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
              {table.getRowModel().rows.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-6 text-center text-gray-500">
                    Sin datos. Ejecuta un full-refresh para generar evaluaciones.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Radar chart — visual comparison */}
      <ModelRadarChart />

      {/* SHAP global importance */}
      <ShapGlobalChart />

      {/* Consensus ensemble weights */}
      <ConsensusWeightsChart />

      {/* Favorite evolution over time */}
      <FavoriteEvolutionSection />
    </div>
  )
}
