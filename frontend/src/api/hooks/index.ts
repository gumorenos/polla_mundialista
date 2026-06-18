import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import type {
  CalibrationBin,
  EnqueueResponse,
  JobRecord,
  ModelMetrics,
  NewsResponse,
  NewsSummaryResponse,
  Snapshot,
  SimulationComparison,
  SimulationDiff,
  SimulationRequest,
  SimulationSummary,
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
