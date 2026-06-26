import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useTeamHistory } from '../api/hooks'

interface Props {
  teamId: string
  teamName: string
  model: string
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('es-ES', { month: 'short', day: 'numeric' })
}

export function TeamEvolutionChart({ teamId, teamName, model }: Props) {
  const { data, isLoading, error } = useTeamHistory(teamId, model)

  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-800 px-4 py-6 text-center text-sm text-gray-500 animate-pulse">
        Cargando evolución…
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-gray-800 px-4 py-3 text-sm text-yellow-500">
        No se pudo cargar el historial de {teamName}.
      </div>
    )
  }

  if (!data || data.history.length === 0) {
    return (
      <div className="rounded-lg border border-gray-800 px-4 py-4 text-sm text-gray-500 text-center">
        Necesitas al menos 2 simulaciones para ver la evolución de {teamName}.
      </div>
    )
  }

  const chartData = data.history.map((p) => ({
    date: fmtDate(p.created_at),
    'Campeón %': parseFloat((p.champion_prob * 100).toFixed(2)),
    'Top 4 %': parseFloat((p.top4_prob * 100).toFixed(2)),
    'Clasifica %': parseFloat((p.top16_prob * 100).toFixed(2)),
  }))

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
        Evolución de probabilidades — {teamName}
      </p>
      <div className="rounded-lg border border-gray-800 overflow-hidden">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ top: 10, right: 16, bottom: 4, left: 4 }}>
            <XAxis
              dataKey="date"
              tick={{ fill: '#6b7280', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => v.toFixed(0) + '%'}
              tick={{ fill: '#6b7280', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={38}
            />
            <Tooltip
              contentStyle={{
                background: '#111827',
                border: '1px solid #374151',
                borderRadius: 6,
                fontSize: 11,
              }}
              formatter={(v: number, name: string) => [v.toFixed(1) + '%', name]}
            />
            <Legend
              wrapperStyle={{ fontSize: 10, color: '#9ca3af' }}
            />
            <Line
              type="monotone"
              dataKey="Campeón %"
              stroke="#facc15"
              strokeWidth={2}
              dot={{ r: 3, fill: '#facc15' }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="Top 4 %"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={{ r: 3, fill: '#3b82f6' }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="Clasifica %"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 3, fill: '#22c55e' }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-gray-600">
        {data.history.length} simulaciones · modelo: {data.model}
      </p>
    </div>
  )
}
