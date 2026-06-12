import { useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useCalibration, useModelsComparison } from '../api/hooks'

const MODELS = ['baseline', 'elo', 'poisson', 'poisson_context', 'ml_calibrated']

export default function Calibration() {
  const [model, setModel] = useState('poisson')
  const { data: bins, isLoading, error } = useCalibration(model)
  const { data: metrics } = useModelsComparison()

  const modelMetrics = metrics?.find((m) => m.model_name === model)

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Calibración</h2>
          <p className="mt-1 text-sm text-gray-400">
            Reliability diagram — probabilidades predichas vs. observadas
          </p>
        </div>
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
      </div>

      {/* Metrics summary */}
      {modelMetrics && (
        <div className="flex gap-6 rounded-lg border border-gray-800 bg-gray-900 px-5 py-3 text-sm">
          {[
            ['Brier', modelMetrics.brier_score?.toFixed(4)],
            ['Log-Loss', modelMetrics.log_loss?.toFixed(4)],
            ['RPS', modelMetrics.rps?.toFixed(4)],
            ['Accuracy', modelMetrics.accuracy != null ? (modelMetrics.accuracy * 100).toFixed(1) + '%' : '—'],
          ].map(([label, val]) => (
            <div key={label}>
              <span className="text-gray-500">{label}: </span>
              <span className="text-white">{val ?? '—'}</span>
            </div>
          ))}
        </div>
      )}

      {isLoading && <p className="text-gray-400">Cargando datos de calibración…</p>}
      {error && (
        <p className="text-yellow-400">
          Sin datos para el modelo «{model}». Ejecuta un full-refresh primero.
        </p>
      )}

      {bins && bins.length > 0 && (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={bins} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="bin_center"
                tickFormatter={(v) => (v * 100).toFixed(0) + '%'}
                stroke="#6b7280"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                label={{ value: 'Probabilidad predicha', position: 'insideBottom', offset: -2, fill: '#6b7280', fontSize: 11 }}
              />
              <YAxis
                tickFormatter={(v) => (v * 100).toFixed(0) + '%'}
                stroke="#6b7280"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                domain={[0, 1]}
              />
              <Tooltip
                formatter={(val: number) => (val * 100).toFixed(1) + '%'}
                contentStyle={{ background: '#1f2937', border: '1px solid #374151', color: '#f3f4f6' }}
              />
              <Legend wrapperStyle={{ color: '#9ca3af', fontSize: 12 }} />
              <ReferenceLine
                x={0}
                y={0}
                stroke="#4b5563"
                strokeDasharray="4 4"
                label=""
              />
              {/* Perfect calibration diagonal */}
              <Line
                type="linear"
                dataKey="bin_center"
                name="Perfecta"
                stroke="#4b5563"
                strokeDasharray="6 3"
                dot={false}
                activeDot={false}
              />
              <Line
                type="monotone"
                dataKey="observed_freq"
                name="Observada"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={{ r: 3, fill: '#3b82f6' }}
              />
              <Line
                type="monotone"
                dataKey="predicted_freq"
                name="Predicha"
                stroke="#10b981"
                strokeWidth={2}
                dot={{ r: 3, fill: '#10b981' }}
              />
            </LineChart>
          </ResponsiveContainer>
          <p className="mt-2 text-xs text-gray-500 text-right">
            {bins.length} bins · n total:{' '}
            {bins.reduce((s, b) => s + b.count, 0).toLocaleString()} partidos
          </p>
        </div>
      )}
    </div>
  )
}
