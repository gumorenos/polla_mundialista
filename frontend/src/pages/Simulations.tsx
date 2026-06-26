import { useState } from 'react'
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts'
import { useRunSimulation, useSimulations, useSimulationComparison, useSimulationDiff, useShapGlobal, useShapMatch, useTeamNarrative, useOddsValue, useEloHistory } from '../api/hooks'
import type { TeamResult, SimulationComparisonTeam, SimulationDiffTeam, ShapFactor, OddsValueTeam } from '../types'
import { TeamEvolutionChart } from '../components/TeamEvolutionChart'

const MODELS = ['baseline', 'elo', 'poisson', 'poisson_context', 'ml_calibrated', 'consensus']

const MODEL_LABELS: Record<string, string> = {
  baseline: 'Baseline',
  elo: 'ELO',
  poisson: 'Poisson',
  poisson_context: 'Poisson+Ctx',
  ml_calibrated: 'ML Calibrado',
  consensus: '⚖️ Consenso (ensemble)',
}

function fmt(n: number) {
  return (n * 100).toFixed(1) + '%'
}

function TeamTable({ rows, onTeamClick }: { rows: TeamResult[]; onTeamClick: (t: TeamResult) => void }) {
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
            <tr
              key={t.team_id}
              className="border-t border-gray-800 hover:bg-gray-800/60 cursor-pointer transition-colors"
              onClick={() => onTeamClick(t)}
            >
              <td className="px-4 py-2 text-gray-500">{i + 1}</td>
              <td className="px-4 py-2 font-medium text-white">
                {t.team_name}
                <span className="ml-1 text-xs text-gray-600">›</span>
              </td>
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
              <th
                key={m}
                className={`${thClass} ${m === 'consensus' ? 'bg-indigo-950/40 border-l border-indigo-800/50 text-indigo-300' : ''}`}
                onClick={() => handleSort(m)}
              >
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
                  const isConsensus = models[mi] === 'consensus'
                  return (
                    <td
                      key={models[mi]}
                      className={`px-4 py-2 font-mono text-xs ${
                        isConsensus
                          ? 'bg-indigo-950/40 border-l border-indigo-800/50 font-semibold'
                          : ''
                      } ${
                        val === null
                          ? 'text-gray-600'
                          : isConsensus
                          ? 'text-indigo-300'
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

// ---------------------------------------------------------------------------
// Simulation diff components
// ---------------------------------------------------------------------------

function deltaColor(delta: number): string {
  const pct = delta * 100
  if (pct > 2) return 'text-green-400 font-bold'
  if (pct > 0.5) return 'text-green-300'
  if (pct >= -0.5) return 'text-gray-400'
  if (pct >= -2) return 'text-red-300'
  return 'text-red-400 font-bold'
}

function deltaBg(delta: number): string {
  const pct = delta * 100
  if (pct > 2) return 'bg-green-900/70 text-green-300'
  if (pct > 0.5) return 'bg-green-900/40 text-green-400'
  if (pct >= -0.5) return 'bg-gray-800 text-gray-400'
  if (pct >= -2) return 'bg-red-900/40 text-red-400'
  return 'bg-red-900/70 text-red-300'
}

function fmtDelta(delta: number) {
  const pct = delta * 100
  return (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%'
}

function MoverCard({ team }: { team: SimulationDiffTeam }) {
  const up = team.trend === 'up'
  const stable = team.trend === 'stable'
  return (
    <div className={`rounded-lg border px-4 py-3 flex items-center gap-3 ${
      stable
        ? 'border-gray-700 bg-gray-900/50'
        : up
        ? 'border-green-800/60 bg-green-950/30'
        : 'border-red-800/60 bg-red-950/30'
    }`}>
      <span className={`text-xl ${stable ? 'text-gray-500' : up ? 'text-green-400' : 'text-red-400'}`}>
        {stable ? '→' : up ? '↑' : '↓'}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-white truncate">{team.team_name}</div>
        <div className={`text-xs font-mono ${stable ? 'text-gray-500' : up ? 'text-green-400' : 'text-red-400'}`}>
          {fmtDelta(team.champion_delta)}
        </div>
      </div>
      <div className="text-right text-xs text-gray-500">
        <div>{fmt(team.previous_champion)}</div>
        <div className="text-white">{fmt(team.current_champion)}</div>
      </div>
    </div>
  )
}

function DiffExpandableTable({ teams }: { teams: SimulationDiffTeam[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2"
      >
        {open ? 'Ocultar tabla completa ↑' : 'Ver tabla completa de cambios ↓'}
      </button>
      {open && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-xs">
            <thead className="bg-gray-900">
              <tr>
                {['Equipo', 'Campeón antes', 'Campeón ahora', 'Cambio', 'Top 4 antes', 'Top 4 ahora', 'Cambio top4'].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-gray-400">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {teams.map((t) => (
                <tr key={t.team_id} className="border-t border-gray-800 hover:bg-gray-900/50">
                  <td className="px-3 py-2 font-medium text-white whitespace-nowrap">{t.team_name}</td>
                  <td className="px-3 py-2 font-mono text-gray-400">{fmt(t.previous_champion)}</td>
                  <td className="px-3 py-2 font-mono text-gray-200">{fmt(t.current_champion)}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-block rounded px-1.5 py-0.5 font-mono font-medium ${deltaBg(t.champion_delta)}`}>
                      {fmtDelta(t.champion_delta)}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-400">{fmt(t.previous_top4)}</td>
                  <td className="px-3 py-2 font-mono text-gray-200">{fmt(t.current_top4)}</td>
                  <td className={`px-3 py-2 font-mono ${deltaColor(t.top4_delta)}`}>
                    {fmtDelta(t.top4_delta)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SHAP drawer
// ---------------------------------------------------------------------------

function ShapBar({ factor }: { factor: ShapFactor }) {
  const pct = Math.abs(factor.shap_contribution) * 100
  const isPos = factor.direction === 'favors_home'
  const isNeg = factor.direction === 'favors_away'
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-300 truncate max-w-[160px]" title={factor.description}>
          {factor.label}
        </span>
        <span className={`font-mono ${isPos ? 'text-green-400' : isNeg ? 'text-red-400' : 'text-gray-500'}`}>
          {factor.shap_contribution >= 0 ? '+' : ''}{factor.shap_contribution.toFixed(3)}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-gray-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${isPos ? 'bg-green-500' : isNeg ? 'bg-red-500' : 'bg-gray-600'}`}
          style={{ width: `${Math.min(pct * 8, 100)}%` }}
        />
      </div>
    </div>
  )
}

function ShapMatchPanel({ homeId, awayId, homeName, awayName }: {
  homeId: string; awayId: string; homeName: string; awayName: string
}) {
  const { data, isLoading, error } = useShapMatch(homeId, awayId)

  if (isLoading) return <p className="text-xs text-gray-500">Calculando SHAP…</p>
  if (error) return <p className="text-xs text-yellow-500">SHAP no disponible para este partido.</p>
  if (!data) return null

  const { prediction, explanation } = data
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-1 text-center text-xs">
        {[
          { label: homeName, val: prediction.home_win, color: 'text-blue-400' },
          { label: 'Empate',  val: prediction.draw,     color: 'text-gray-400' },
          { label: awayName,  val: prediction.away_win, color: 'text-orange-400' },
        ].map(({ label, val, color }) => (
          <div key={label} className="rounded bg-gray-800 p-2">
            <div className={`text-base font-bold font-mono ${color}`}>{(val * 100).toFixed(1)}%</div>
            <div className="text-gray-500 truncate">{label}</div>
          </div>
        ))}
      </div>
      {explanation.summary && (
        <p className="text-xs text-gray-400 italic">{explanation.summary}</p>
      )}
      <div className="space-y-2">
        {explanation.top_factors.slice(0, 8).map((f) => (
          <ShapBar key={f.feature} factor={f} />
        ))}
      </div>
    </div>
  )
}

function TeamDrawer({
  team,
  allTeams,
  runId,
  model,
  onClose,
}: {
  team: TeamResult
  allTeams: TeamResult[]
  runId: string
  model: string
  onClose: () => void
}) {
  const [opponent, setOpponent] = useState<string>('')
  const shapGlobal = useShapGlobal()
  const narrative = useTeamNarrative(runId, team.team_id)
  const eloHistory = useEloHistory(team.team_id)

  const opponents = allTeams.filter((t) => t.team_id !== team.team_id)
  const oppTeam = opponents.find((t) => t.team_id === opponent)

  const globalChartData = (shapGlobal.data?.features ?? []).map((f) => ({
    label: f.label,
    importance: parseFloat((f.importance * 100).toFixed(3)),
  }))

  const COLORS = ['#3b82f6','#6366f1','#8b5cf6','#a78bfa','#c4b5fd','#ddd6fe','#e0e7ff','#c7d2fe','#a5b4fc','#818cf8']

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-sm overflow-y-auto shadow-2xl flex flex-col"
        style={{ background: 'var(--color-surface)', borderLeft: '1px solid var(--color-border)' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-4 border-b sticky top-0 z-10"
          style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <div>
            <h3 className="text-base font-bold" style={{ color: 'var(--color-text)' }}>
              {team.team_name}
            </h3>
            <p className="text-xs" style={{ color: 'var(--color-muted)' }}>Análisis ML</p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-700 text-gray-400">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="p-4 space-y-5 flex-1">
          {/* Simulation stats */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-muted)' }}>
              Probabilidades (simulación)
            </p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[
                { label: 'Campeón', val: team.win_tournament, color: 'text-yellow-400' },
                { label: 'Final',   val: team.reach_final,    color: 'text-blue-400' },
                { label: 'Semi',    val: team.reach_semi_final, color: 'text-green-400' },
                { label: 'Cuartos', val: team.reach_quarter_final, color: 'text-gray-300' },
              ].map(({ label, val, color }) => (
                <div key={label} className="rounded p-2" style={{ background: 'var(--color-surface2)' }}>
                  <div className={`text-sm font-bold font-mono ${color}`}>{fmt(val)}</div>
                  <div style={{ color: 'var(--color-muted)' }}>{label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Evolution chart */}
          <TeamEvolutionChart teamId={team.team_id} teamName={team.team_name} model={model} />

          {/* LLM narrative */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-muted)' }}>
              Análisis narrativo
            </p>
            {narrative.isLoading && (
              <div className="space-y-1.5 animate-pulse">
                {[0.9, 0.75, 0.6].map((w) => (
                  <div key={w} className="h-3 rounded" style={{ background: 'var(--color-surface2)', width: `${w * 100}%` }} />
                ))}
              </div>
            )}
            {!narrative.isLoading && narrative.data?.narrative && (
              <p className="text-xs leading-relaxed" style={{ color: 'var(--color-muted)' }}>
                {narrative.data.narrative}
              </p>
            )}
          </div>

          {/* Per-match SHAP */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-muted)' }}>
              ¿Por qué este pronóstico? — partido vs.
            </p>
            <select
              value={opponent}
              onChange={(e) => setOpponent(e.target.value)}
              className="w-full rounded border px-2 py-1.5 text-xs mb-3"
              style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface2)', color: 'var(--color-text)' }}
            >
              <option value="">Selecciona rival…</option>
              {opponents.map((t) => (
                <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
              ))}
            </select>
            {opponent && oppTeam && (
              <ShapMatchPanel
                homeId={team.team_id}
                awayId={opponent}
                homeName={team.team_name}
                awayName={oppTeam.team_name}
              />
            )}
          </div>

          {/* Global SHAP */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--color-muted)' }}>
              Importancia global de features (modelo ML)
            </p>
            {shapGlobal.isLoading && <p className="text-xs text-gray-500">Cargando…</p>}
            {shapGlobal.error && (
              <p className="text-xs text-yellow-500">
                Sin modelo ML entrenado — entrena para ver SHAP.
              </p>
            )}
            {globalChartData.length > 0 && (
              <div className="rounded border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart
                    data={globalChartData}
                    layout="vertical"
                    margin={{ top: 4, right: 12, bottom: 4, left: 130 }}
                  >
                    <XAxis type="number" tick={{ fill: '#6b7280', fontSize: 10 }} tickFormatter={(v) => v.toFixed(2)} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="label" tick={{ fill: '#d1d5db', fontSize: 10 }} axisLine={false} tickLine={false} width={125} />
                    <Tooltip
                      contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 11 }}
                      formatter={(v: number) => [v.toFixed(3), 'Importancia SHAP']}
                    />
                    <Bar dataKey="importance" radius={[0, 3, 3, 0]}>
                      {globalChartData.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* ELO history chart */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--color-muted)' }}>
              Histórico ELO propio
            </p>
            {eloHistory.isLoading && <p className="text-xs text-gray-500">Cargando…</p>}
            {eloHistory.error && (
              <p className="text-xs text-yellow-500">Sin datos ELO para este equipo.</p>
            )}
            {eloHistory.data && eloHistory.data.length > 0 && (
              <div className="rounded border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart
                    data={eloHistory.data.map((e) => ({
                      date: e.match_date.slice(0, 10),
                      elo: e.elo_rating,
                      change: e.elo_change,
                      opponent: e.opponent_name ?? e.opponent_id ?? '',
                      result: e.goals_for != null && e.goals_against != null
                        ? `${e.goals_for}–${e.goals_against}`
                        : '',
                    }))}
                    margin={{ top: 6, right: 8, bottom: 4, left: 10 }}
                  >
                    <XAxis
                      dataKey="date"
                      tick={{ fill: '#6b7280', fontSize: 9 }}
                      axisLine={false}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      domain={['auto', 'auto']}
                      tick={{ fill: '#6b7280', fontSize: 9 }}
                      axisLine={false}
                      tickLine={false}
                      width={40}
                    />
                    <ReferenceLine y={1500} stroke="#374151" strokeDasharray="3 3" />
                    <Tooltip
                      contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 10 }}
                      formatter={(v: number, _: string, props: { payload?: { opponent: string; result: string; change: number } }) => {
                        const p = props.payload
                        const detail = p ? ` vs ${p.opponent} (${p.result}) Δ${p.change >= 0 ? '+' : ''}${p.change}` : ''
                        return [`${v.toFixed(0)}${detail}`, 'ELO']
                      }}
                      labelFormatter={(l) => l}
                    />
                    <Line
                      type="monotone"
                      dataKey="elo"
                      stroke="#3b82f6"
                      strokeWidth={1.5}
                      dot={false}
                      activeDot={{ r: 3 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Odds vs. Mercado
// ---------------------------------------------------------------------------

function signalBadge(signal: OddsValueTeam['signal']) {
  if (signal === 'value') return <span className="rounded-full px-2 py-0.5 text-xs font-semibold bg-green-900/60 text-green-300">💎 Valor</span>
  if (signal === 'overpriced') return <span className="rounded-full px-2 py-0.5 text-xs font-semibold bg-red-900/60 text-red-300">⚠ Sobrecomprado</span>
  return <span className="rounded-full px-2 py-0.5 text-xs bg-gray-800 text-gray-500">=</span>
}

function OddsValueTable({ teams, updatedAt }: { teams: OddsValueTeam[]; updatedAt: string | null }) {
  const sorted = [...teams].sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
  return (
    <div className="space-y-3">
      {updatedAt && (
        <p className="text-xs text-gray-500">
          Odds actualizadas: {new Date(updatedAt).toLocaleString()}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead className="bg-gray-900">
            <tr>
              {['Equipo', 'Oráculo', 'Mercado', 'Diferencia', 'Mejor odd', 'Casa', 'Señal'].map((h) => (
                <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => {
              const pos = t.value > 0
              const neg = t.value < 0
              return (
                <tr key={t.team_id} className="border-t border-gray-800 hover:bg-gray-900/50">
                  <td className="px-3 py-2 font-medium text-white whitespace-nowrap">{t.team_name}</td>
                  <td className="px-3 py-2 font-mono text-blue-300">{fmt(t.oraculo_prob)}</td>
                  <td className="px-3 py-2 font-mono text-gray-400">{fmt(t.market_prob)}</td>
                  <td className={`px-3 py-2 font-mono font-semibold ${pos ? 'text-green-400' : neg ? 'text-red-400' : 'text-gray-500'}`}>
                    {t.value >= 0 ? '+' : ''}{fmt(t.value)}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-300">{t.best_odd.toFixed(2)}</td>
                  <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{t.bookmaker}</td>
                  <td className="px-3 py-2">{signalBadge(t.signal)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-600">
        Las probabilidades del mercado son informativas. Esta aplicación no promueve ni facilita apuestas.
      </p>
    </div>
  )
}

export default function Simulations() {
  const [tab, setTab] = useState<'individual' | 'comparar' | 'mercado'>('individual')
  const [model, setModel] = useState('poisson')
  const [drawerTeam, setDrawerTeam] = useState<TeamResult | null>(null)
  const { data, isLoading, error } = useSimulations(model)
  const runSim = useRunSimulation()
  const comparison = useSimulationComparison()
  const diff = useSimulationDiff(model)
  const oddsValue = useOddsValue(model)

  const modelsWithData = comparison.data
    ? comparison.data.models.filter((m) =>
        comparison.data!.teams.some((t) => t[m as keyof SimulationComparisonTeam] !== null),
      )
    : []

  function handleRun() {
    runSim.mutate({ model_name: model })
  }

  return (
    <div className="p-4 sm:p-8 space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Simulaciones Monte Carlo</h2>
          <p className="mt-1 text-sm text-gray-400">
            Últimos resultados por modelo — 30,000 iteraciones
          </p>
        </div>
        {tab === 'individual' && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 w-full sm:w-auto min-h-[44px]"
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
              className="rounded bg-blue-700 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50 min-h-[44px]"
            >
              {runSim.isPending ? 'Encolando…' : 'Simular'}
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800">
        {([
          ['individual', 'Por modelo'],
          ['comparar',   'Comparar modelos'],
          ['mercado',    'vs. Mercado'],
        ] as const).map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? 'border-b-2 border-blue-500 text-blue-400'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {label}
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
              <TeamTable rows={data.team_results} onTeamClick={setDrawerTeam} />

              {/* Diff section */}
              {diff.data && !('error' in diff.data) && (
                <div className="space-y-4 pt-2">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
                      Cambios desde la simulación anterior
                    </h3>
                    <p className="mt-1 text-xs text-gray-500">
                      Comparando simulación de{' '}
                      {new Date(diff.data.current_created_at).toLocaleString()} vs.{' '}
                      simulación de hace {diff.data.hours_between}h
                    </p>
                    <p className="mt-1 text-xs text-gray-400 italic">{diff.data.summary}</p>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                    {diff.data.biggest_movers.map((team) => (
                      <MoverCard key={team.team_id} team={team} />
                    ))}
                  </div>

                  <DiffExpandableTable teams={diff.data.teams} />
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* Team detail drawer */}
      {drawerTeam && data && (
        <TeamDrawer
          team={drawerTeam}
          allTeams={data.team_results}
          runId={data.run.id}
          model={model}
          onClose={() => setDrawerTeam(null)}
        />
      )}

      {/* Odds vs. Market view */}
      {tab === 'mercado' && (
        <>
          {oddsValue.isLoading && <p className="text-gray-400">Cargando odds…</p>}
          {oddsValue.error && (
            <div className="rounded-lg border border-yellow-800/40 bg-yellow-950/20 px-4 py-3 text-sm text-yellow-400">
              Sin datos de odds — configura <code className="text-yellow-300">ODDS_API_KEY</code> para activar la comparación con el mercado.
            </div>
          )}
          {oddsValue.data && oddsValue.data.teams.length === 0 && (
            <p className="text-yellow-400 text-sm">
              No hay datos de odds disponibles aún. Configura{' '}
              <code>ODDS_API_KEY</code> y espera la próxima actualización automática (cada 6h).
            </p>
          )}
          {oddsValue.data && oddsValue.data.teams.length > 0 && (
            <OddsValueTable teams={oddsValue.data.teams} updatedAt={oddsValue.data.updated_at} />
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
