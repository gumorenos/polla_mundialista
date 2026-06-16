// ---------------------------------------------------------------------------
// Core domain types
// ---------------------------------------------------------------------------

export interface Team {
  id: number
  name: string
  code: string
  confederation: string
  elo_rating: number | null
  fifa_ranking: number | null
  group_id: string | null
}

export interface JobRecord {
  id: string
  rq_job_id: string | null
  job_type: string
  status: 'enqueued' | 'started' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  error_message: string | null
  result_ref: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  last_heartbeat: string | null
}

export interface ModelMetrics {
  model_name: string
  brier_score: number | null
  log_loss: number | null
  rps: number | null
  accuracy: number | null
  total_predictions: number
}

export interface CalibrationBin {
  bin_center: number
  predicted_freq: number
  observed_freq: number
  count: number
}

export interface Snapshot {
  id: string
  label: string | null
  description: string | null
  trigger: string | null
  simulation_run_id: string | null
  created_at: string
}

export interface TeamResult {
  id: string
  simulation_run_id: string
  team_id: string
  team_name: string
  win_group: number
  qualify: number
  reach_round_of_32: number
  reach_round_of_16: number
  reach_quarter_final: number
  reach_semi_final: number
  reach_final: number
  win_tournament: number
  expected_group_points: number
}

export interface SimulationRun {
  id: string
  model_name: string
  status: string
  iterations: number
  seed: number
  data_version_hash: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

export interface SimulationSummary {
  run: SimulationRun
  team_results: TeamResult[]
}

export interface PredictionRun {
  id: string
  model_name: string
  model_version: string
  data_version_hash: string
  created_at: string
}

export interface MatchPrediction {
  id: number
  run_id: string
  fixture_id: number
  home_team: string
  away_team: string
  prob_home_win: number
  prob_draw: number
  prob_away_win: number
  expected_home_goals: number | null
  expected_away_goals: number | null
}

export interface SimulationRequest {
  model_name: string
  iterations?: number
}

export interface NewsClaim {
  id: string
  team_id: string
  team_name: string
  player_name: string
  status: 'injured' | 'doubtful' | 'available' | 'unknown'
  reason: string | null
  source_url: string | null
  source_name: string | null
  confidence: number | null
  evidence_level: string | null
  affects_prediction: number
  observed_at: string
  created_at: string
}

export interface NewsResponse {
  items: NewsClaim[]
  last_updated: string | null
  total: number
}

export interface NewsTeamSummary {
  team_id: string
  team_name: string
  injury_count: number
  players_affected: string[]
  attack_factor: number | null
  defense_factor: number | null
}

export interface NewsSummaryResponse {
  teams: NewsTeamSummary[]
}

export interface SimulationComparisonTeam {
  team_id: string
  team_name: string
  baseline: number | null
  elo: number | null
  poisson: number | null
  poisson_context: number | null
  ml_calibrated: number | null
}

export interface SimulationComparison {
  models: string[]
  teams: SimulationComparisonTeam[]
}

export interface EnqueueResponse {
  job_id: string
  rq_job_id: string
  status: string
}
