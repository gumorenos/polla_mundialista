import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table'
import { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { useModelsComparison, useShapGlobal } from '../api/hooks'
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

      {/* SHAP global importance */}
      <ShapGlobalChart />
    </div>
  )
}
