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
  published_at: string | null
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

export interface SimulationDiffTeam {
  team_id: string
  team_name: string
  current_champion: number
  previous_champion: number
  champion_delta: number
  current_top4: number
  previous_top4: number
  top4_delta: number
  current_top16: number
  previous_top16: number
  top16_delta: number
  trend: 'up' | 'down' | 'stable'
}

export interface SimulationDiff {
  model: string
  current_run_id: string
  previous_run_id: string
  current_created_at: string
  previous_created_at: string
  hours_between: number
  teams: SimulationDiffTeam[]
  biggest_movers: SimulationDiffTeam[]
  summary: string
}

export interface SimulationDiffError {
  error: string
  message: string
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

export interface AppConfigEntry {
  key: string
  value: string
  description: string | null
  updated_at: string
}

export interface ShapFeature {
  feature: string
  label: string
  importance: number
}

export interface ShapGlobal {
  model_id: string
  algorithm: string
  features: ShapFeature[]
}

export interface ShapFactor {
  feature: string
  label: string
  value: number
  shap_contribution: number
  direction: 'favors_home' | 'favors_away' | 'neutral'
  description: string
}

export interface MarketOdd {
  team_id: string
  team_name: string
  bookmaker: string
  decimal_odd: number
  implied_prob: number
  fetched_at: string | null
}

export interface OddsResponse {
  updated_at: string | null
  teams: MarketOdd[]
}

export interface OddsValueTeam {
  team_id: string
  team_name: string
  oraculo_prob: number
  market_prob: number
  value: number
  best_odd: number
  bookmaker: string
  signal: 'value' | 'overpriced' | 'fair'
}

export interface OddsValue {
  model: string
  updated_at: string | null
  teams: OddsValueTeam[]
}

export interface NarrativeResponse {
  narrative: string | null
  generated_at: string | null
}

export interface ShapMatch {
  home_team: string
  away_team: string
  is_neutral: boolean
  features_missing: string[]
  prediction: { home_win: number; draw: number; away_win: number }
  explanation: {
    top_factors: ShapFactor[]
    summary: string
  }
}
