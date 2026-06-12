// ---------------------------------------------------------------------------
// Core domain types — extended as features are implemented
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

export interface Job {
  id: string
  queue: string
  status: 'enqueued' | 'started' | 'finished' | 'failed'
  func_name: string | null
  created_at: string
  started_at: string | null
  ended_at: string | null
  result: string | null
  error: string | null
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

export interface SimulationRun {
  id: string
  model_name: string
  iterations: number
  seed: number
  created_at: string
}

export interface SimulationTeamResult {
  team_name: string
  prob_group_stage: number
  prob_round_of_16: number
  prob_quarter_final: number
  prob_semi_final: number
  prob_final: number
  prob_champion: number
}
