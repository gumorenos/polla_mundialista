import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import type {
  AppConfigEntry,
  CalibrationBin,
  ConsensusWeights,
  EloHistory,
  EnqueueResponse,
  EvaluationRadar,
  JobRecord,
  ModelMetrics,
  NarrativeResponse,
  NewsResponse,
  NewsSummaryResponse,
  OddsResponse,
  OddsValue,
  PlayerFormResponse,
  ShapGlobal,
  ShapMatch,
  Snapshot,
  SimulationComparison,
  FavoriteHistoryResponse,
  SimulationDiff,
  SimulationRequest,
  SimulationRunHistoryItem,
  SimulationSummary,
  SuspensionsResponse,
  TeamHistoryResponse,
} from '../../types'

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

export function useSimulations(model = 'poisson') {
  return useQuery<SimulationSummary>({
    queryKey: ['simulations', 'latest', model],
    queryFn: () => api.get<SimulationSummary>(`/api/simulations/latest?model=${encodeURIComponent(model)}`),
    retry: false,
  })
}

export function useSimulationRunsHistory(model = 'poisson') {
  return useQuery<{ model: string; runs: SimulationRunHistoryItem[] }>({
    queryKey: ['simulations', 'runs', model],
    queryFn: () => api.get(`/api/simulations/runs?model=${encodeURIComponent(model)}&limit=20`),
    retry: false,
  })
}

export function useSimulationComparison() {
  return useQuery<SimulationComparison>({
    queryKey: ['simulations', 'comparison'],
    queryFn: () => api.get<SimulationComparison>('/api/simulations/comparison'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useSimulationDiff(model: string) {
  return useQuery<SimulationDiff>({
    queryKey: ['simulation-diff', model],
    queryFn: () => api.get<SimulationDiff>(`/api/simulations/diff?model=${encodeURIComponent(model)}`),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useModelsComparison() {
  return useQuery<ModelMetrics[]>({
    queryKey: ['evaluations', 'summary'],
    queryFn: () => api.get<ModelMetrics[]>('/api/evaluations/summary'),
  })
}

export function useCalibration(model: string) {
  return useQuery<CalibrationBin[]>({
    queryKey: ['evaluations', 'calibration', model],
    queryFn: () => api.get<CalibrationBin[]>(`/api/evaluations/calibration?model=${encodeURIComponent(model)}`),
    enabled: !!model,
    retry: false,
  })
}

export function useJobs(limit = 50) {
  return useQuery<JobRecord[]>({
    queryKey: ['jobs', limit],
    queryFn: () => api.get<JobRecord[]>(`/api/jobs?limit=${limit}`),
    refetchInterval: 5_000,
  })
}

export function useJobStatus(jobId: string | null) {
  return useQuery<JobRecord>({
    queryKey: ['jobs', jobId],
    queryFn: () => api.get<JobRecord>(`/api/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // FIX 4: stop polling for all terminal states including cancelled
      if (status === 'completed' || status === 'failed' || status === 'cancelled') return false
      return 3_000
    },
  })
}

export function useSnapshots(limit = 50) {
  return useQuery<Snapshot[]>({
    queryKey: ['snapshots', limit],
    queryFn: () => api.get<Snapshot[]>(`/api/snapshots?limit=${limit}`),
  })
}

export function useTeamStats(model = 'poisson') {
  return useSimulations(model)
}

export interface BracketSimTeam {
  team_id: string
  team_name: string
  advance_prob: number
  opponent_id: string | null
  opponent_name: string | null
  match_win_prob: number | null
  is_eliminated: boolean
}

export interface BracketSimulationResponse {
  model: string
  rounds: Record<string, BracketSimTeam[]>
  computed_at: string | null
}

/** GET /api/simulations/bracket/latest — new contract with run_id/status/message/meta. */
export interface BracketLatestResponse {
  model: string
  run_id: string | null
  status: 'completed' | 'no_r32' | null
  rounds: Record<string, BracketSimTeam[]>
  computed_at: string | null
  message: string | null
  meta: {
    iterations?: number
    r32_source?: string | null
    r32_fetched_at?: string | null
  }
}

export interface BracketRun {
  id: string
  model_name: string
  status: string
  iterations: number
  source: string
  r32_source: string | null
  r32_fetched_at: string | null
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  created_at: string
}

export function useBracketSimulation(model = 'elo') {
  return useQuery<BracketSimulationResponse>({
    queryKey: ['bracket-simulation', model],
    queryFn: () => api.get<BracketSimulationResponse>(`/api/simulations/bracket?model=${encodeURIComponent(model)}`),
    retry: false,
  })
}

export function useBracketLatest(model = 'elo') {
  return useQuery<BracketLatestResponse>({
    queryKey: ['bracket-latest', model],
    queryFn: () => api.get<BracketLatestResponse>(`/api/simulations/bracket/latest?model=${encodeURIComponent(model)}`),
    retry: false,
  })
}

export function useBracketRuns(model = 'elo', limit = 20) {
  return useQuery<{ model: string; runs: BracketRun[] }>({
    queryKey: ['bracket-runs', model, limit],
    queryFn: () => api.get(`/api/simulations/bracket/runs?model=${encodeURIComponent(model)}&limit=${limit}`),
    retry: false,
  })
}

export function useRunBracketSimulation() {
  const qc = useQueryClient()
  return useMutation<EnqueueResponse, Error, string>({
    mutationFn: (model) => api.post<EnqueueResponse>(`/api/simulations/bracket/run?model=${encodeURIComponent(model)}`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['bracket-latest'] })
      qc.invalidateQueries({ queryKey: ['bracket-runs'] })
    },
  })
}

export function useAuthStatus() {
  return useQuery<{ authenticated: boolean; must_change_password: boolean }>({
    queryKey: ['auth-status'],
    queryFn: () => api.get<{ authenticated: boolean; must_change_password: boolean }>('/api/auth/status'),
    retry: false,
    staleTime: 60_000,
  })
}

export function usePasswordChanged() {
  return useQuery<{ password_changed: boolean }>({
    queryKey: ['password-changed'],
    queryFn: () => api.get<{ password_changed: boolean }>('/api/auth/password-changed'),
    retry: false,
    staleTime: 60_000,
  })
}

// ---------------------------------------------------------------------------
// Mutation hooks
// ---------------------------------------------------------------------------

export function useRunSimulation() {
  const qc = useQueryClient()
  return useMutation<EnqueueResponse, Error, SimulationRequest>({
    mutationFn: (body) => api.post<EnqueueResponse>('/api/simulations/run', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useTriggerFullRefresh() {
  const qc = useQueryClient()
  return useMutation<EnqueueResponse, Error, void>({
    mutationFn: () => api.post<EnqueueResponse>('/api/pipelines/full-refresh', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useTriggerDailyUpdate() {
  const qc = useQueryClient()
  return useMutation<EnqueueResponse, Error, void>({
    mutationFn: () => api.post<EnqueueResponse>('/api/pipelines/daily-update', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useCreateSnapshot(runId: string) {
  const qc = useQueryClient()
  return useMutation<EnqueueResponse, Error, { label: string; description?: string }>({
    mutationFn: (body) => api.post<EnqueueResponse>(`/api/snapshots/${runId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['snapshots'] }),
  })
}

export function useTrainML() {
  const qc = useQueryClient()
  return useMutation<EnqueueResponse, Error, { algorithm?: string; train_start_year?: number; validation_split?: number }>({
    mutationFn: (body) => api.post<EnqueueResponse>('/api/ml/train', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useCancelJob() {
  const qc = useQueryClient()
  return useMutation<{ cancelled: boolean; job_id: string }, Error, string>({
    mutationFn: (jobId) => api.delete(`/api/jobs/${jobId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function usePurgeJobs() {
  const qc = useQueryClient()
  return useMutation<{ deleted: number }, Error, void>({
    mutationFn: () => api.post('/api/jobs/purge', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useDeleteJobRecord() {
  const qc = useQueryClient()
  return useMutation<{ deleted: boolean; job_id: string }, Error, string>({
    mutationFn: (jobId) => api.delete(`/api/jobs/${jobId}/record`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useNews(params?: { team_id?: string; classification?: string; limit?: number }) {
  const qs = new URLSearchParams()
  if (params?.team_id) qs.set('team_id', params.team_id)
  if (params?.classification) qs.set('classification', params.classification)
  if (params?.limit) qs.set('limit', String(params.limit))
  const query = qs.toString() ? `?${qs}` : ''
  return useQuery<NewsResponse>({
    queryKey: ['news', params],
    queryFn: () => api.get<NewsResponse>(`/api/news${query}`),
    staleTime: 2 * 60 * 1000,
  })
}

export function useNewsSummary() {
  return useQuery<NewsSummaryResponse>({
    queryKey: ['news', 'summary'],
    queryFn: () => api.get<NewsSummaryResponse>('/api/news/summary'),
    staleTime: 2 * 60 * 1000,
  })
}

export function useTriggerNews() {
  const qc = useQueryClient()
  return useMutation<EnqueueResponse, Error, void>({
    mutationFn: () => api.post<EnqueueResponse>('/api/news/trigger', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function usePlayerForm() {
  return useQuery<PlayerFormResponse>({
    queryKey: ['news', 'player-form'],
    queryFn: () => api.get<PlayerFormResponse>('/api/news/player-form'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useSuspensions() {
  return useQuery<SuspensionsResponse>({
    queryKey: ['news', 'suspensions'],
    queryFn: () => api.get<SuspensionsResponse>('/api/news/suspensions'),
    staleTime: 5 * 60 * 1000,
  })
}

export function useTeamHistory(teamId: string | null, model: string) {
  return useQuery<TeamHistoryResponse>({
    queryKey: ['simulations', 'history', teamId, model],
    queryFn: () =>
      api.get<TeamHistoryResponse>(
        `/api/simulations/history/${encodeURIComponent(teamId!)}?model=${encodeURIComponent(model)}&limit=20`,
      ),
    enabled: !!teamId,
    staleTime: 2 * 60 * 1000,
    retry: false,
  })
}

export function useFavoriteHistory(model: string) {
  return useQuery<FavoriteHistoryResponse>({
    queryKey: ['simulations', 'favorite-history', model],
    queryFn: () =>
      api.get<FavoriteHistoryResponse>(
        `/api/simulations/favorite-history?model=${encodeURIComponent(model)}&limit=20`,
      ),
    staleTime: 2 * 60 * 1000,
    retry: false,
  })
}

export function useShapGlobal() {
  return useQuery<ShapGlobal>({
    queryKey: ['ml', 'shap', 'global'],
    queryFn: () => api.get<ShapGlobal>('/api/ml/shap/global'),
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
}

export function useShapMatch(home: string | null, away: string | null, isNeutral = true) {
  return useQuery<ShapMatch>({
    queryKey: ['ml', 'shap', 'match', home, away, isNeutral],
    queryFn: () =>
      api.get<ShapMatch>(
        `/api/ml/shap?home=${encodeURIComponent(home!)}&away=${encodeURIComponent(away!)}&is_neutral=${isNeutral}`,
      ),
    enabled: !!home && !!away,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useOdds() {
  return useQuery<OddsResponse>({
    queryKey: ['odds'],
    queryFn: () => api.get<OddsResponse>('/api/odds'),
    staleTime: 6 * 60 * 60 * 1000,
    retry: false,
  })
}

export function useOddsValue(model = 'ml_calibrated') {
  return useQuery<OddsValue>({
    queryKey: ['odds', 'value', model],
    queryFn: () =>
      api.get<OddsValue>(`/api/odds/value?model=${encodeURIComponent(model)}`),
    staleTime: 6 * 60 * 60 * 1000,
    retry: false,
  })
}

export function useTeamNarrative(runId: string | null, teamId: string | null) {
  return useQuery<NarrativeResponse>({
    queryKey: ['narrative', 'team', runId, teamId],
    queryFn: () =>
      api.get<NarrativeResponse>(
        `/api/simulations/${runId}/narrative/${encodeURIComponent(teamId!)}`,
      ),
    enabled: !!runId && !!teamId,
    staleTime: 6 * 60 * 60 * 1000,
    retry: false,
  })
}

export function useTournamentNarrative(runId: string | null) {
  return useQuery<NarrativeResponse>({
    queryKey: ['narrative', 'tournament', runId],
    queryFn: () =>
      api.get<NarrativeResponse>(`/api/simulations/${runId}/narrative/tournament`),
    enabled: !!runId,
    staleTime: 6 * 60 * 60 * 1000,
    retry: false,
  })
}

export function useEvaluationRadar() {
  return useQuery<EvaluationRadar>({
    queryKey: ['evaluations', 'radar'],
    queryFn: () => api.get<EvaluationRadar>('/api/evaluations/radar'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useConsensusWeights() {
  return useQuery<ConsensusWeights>({
    queryKey: ['consensus-weights'],
    queryFn: () => api.get<ConsensusWeights>('/api/ml/consensus/weights'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useEloHistory(teamId: string | null) {
  return useQuery<EloHistory>({
    queryKey: ['elo-history', teamId],
    queryFn: () => api.get<EloHistory>(`/api/teams/${teamId}/elo-history`),
    enabled: !!teamId,
    staleTime: 30 * 60 * 1000,
    retry: false,
  })
}

export interface TeamContext {
  team_id: string
  team_name: string
  injuries: { count: number; penalty_pct: number; players: string[] }
  suspensions: { count: number; penalty_pct: number }
  altitude_venues: { venue_id: string; venue_name: string; altitude_m: number; adjustment_pct: number }[]
  xg_available: boolean
}

export function useTeamContext(teamId: string | null) {
  return useQuery<TeamContext>({
    queryKey: ['team-context', teamId],
    queryFn: () => api.get<TeamContext>(`/api/teams/${teamId}/context`),
    enabled: !!teamId,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useAppConfig() {
  return useQuery<AppConfigEntry[]>({
    queryKey: ['app-config'],
    queryFn: () => api.get<AppConfigEntry[]>('/api/config'),
    staleTime: 30_000,
  })
}

export function useUpdateConfig() {
  const qc = useQueryClient()
  return useMutation<AppConfigEntry, Error, { key: string; value: string }>({
    mutationFn: ({ key, value }) =>
      api.put<AppConfigEntry>(`/api/config/${encodeURIComponent(key)}`, { value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['app-config'] }),
  })
}

export function useAdminReset() {
  const qc = useQueryClient()
  return useMutation<{ status: string; timestamp: string }, Error, void>({
    mutationFn: () => api.post('/api/admin/reset', { confirm: true }),
    onSuccess: () => {
      qc.invalidateQueries()
    },
  })
}

export function useDeleteNews() {
  const qc = useQueryClient()
  return useMutation<{ deleted: boolean; news_id: string }, Error, string>({
    mutationFn: (newsId: string) => api.delete(`/api/news/${newsId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['news'] }),
  })
}

export function useResetConfig() {
  const qc = useQueryClient()
  return useMutation<AppConfigEntry[], Error, void>({
    mutationFn: () => api.post<AppConfigEntry[]>('/api/config/reset', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['app-config'] }),
  })
}

// ---------------------------------------------------------------------------
// Public API key admin management
// ---------------------------------------------------------------------------

export interface ApiKeyRecord {
  id: string
  prefix: string
  label: string
  scopes: string
  rate_limit_per_minute: number
  notes: string | null
  created_at: string
  last_used_at: string | null
  revoked: number
}

export function useApiKeys() {
  return useQuery<{ keys: ApiKeyRecord[] }>({
    queryKey: ['api-keys'],
    queryFn: () => api.get('/api/admin/api-keys'),
  })
}

export interface CreateApiKeyRequest {
  label: string
  scopes?: string
  rate_limit_per_minute?: number
  notes?: string
}

export interface CreateApiKeyResponse {
  id: string
  key: string
  prefix: string
  label: string
}

export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation<CreateApiKeyResponse, Error, CreateApiKeyRequest>({
    mutationFn: (body) => api.post<CreateApiKeyResponse>('/api/admin/api-keys', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}

export function useRevokeApiKey() {
  const qc = useQueryClient()
  return useMutation<{ id: string; revoked: boolean }, Error, string>({
    mutationFn: (id) => api.post(`/api/admin/api-keys/${id}/revoke`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}
