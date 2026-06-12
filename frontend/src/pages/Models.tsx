import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table'
import { useState } from 'react'
import { useModelsComparison } from '../api/hooks'
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
    <div className="p-8 space-y-6">
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
    </div>
  )
}
