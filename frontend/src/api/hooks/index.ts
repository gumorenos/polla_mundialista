import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import type {
  CalibrationBin,
  EnqueueResponse,
  JobRecord,
  ModelMetrics,
  Snapshot,
  SimulationRequest,
  SimulationSummary,
} from '../../types'

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

export function useSimulations(model = 'poisson') {
  return useQuery<SimulationSummary>({
    queryKey: ['simulations', 'latest', model],
    queryFn: () => api.get<SimulationSummary>(`/api/simulations/latest?model=${model}`),
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
    queryFn: () => api.get<CalibrationBin[]>(`/api/evaluations/calibration?model=${model}`),
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
      if (status === 'completed' || status === 'failed') return false
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
