// Typed fetch wrapper over the Django REST API.
// Base URL comes from VITE_API_BASE; in dev, Vite proxies /api to :8000.

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`
  let response: Response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' } })
  } catch {
    throw new ApiError(0, `Network error contacting ${url}`)
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Request to ${path} failed (${response.status})`)
  }
  return (await response.json()) as T
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_BASE}${path}`
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, `Network error contacting ${url}`)
  }
  if (!response.ok) {
    // Validation errors carry the reason in the body — surface it.
    let detail = ''
    try {
      detail = Object.values((await response.json()) as Record<string, string>).join('; ')
    } catch {
      detail = ''
    }
    throw new ApiError(response.status, detail || `Request to ${path} failed (${response.status})`)
  }
  return (await response.json()) as T
}

// --- Response types (mirror league/api/selectors.py) ---

export interface HealthResponse {
  status: string
  service: string
  version: string
  database: string
}

export interface ManagerRef {
  id: number
  label: string
}

export interface ChampionEntry {
  year: number
  champion: { team: string; manager: ManagerRef | null } | null
}

export interface LeagueOverview {
  league: { id: number; name: string }
  seasons: Array<{
    year: number
    team_count: number
    is_complete: boolean
    champion: { team: string; manager: ManagerRef | null } | null
  }>
  champions_timeline: ChampionEntry[]
  last_sync: { command: string; finished_at: string; row_counts: Record<string, number> } | null
}

export interface ManagerCareerRow {
  manager: ManagerRef
  seasons_played: number
  wins: number
  losses: number
  ties: number
  win_pct: number
  championships: number
  playoff_appearances: number
  sackos: number
  total_luck_delta: number
  longest_win_streak: number
  longest_lose_streak: number
}

export interface ChartSeries {
  name: string
  data: number[]
}

export interface ManagerProfile {
  manager: ManagerRef
  career: Omit<ManagerCareerRow, 'manager'> | null
  seasons: Array<{
    year: number
    wins: number
    losses: number
    ties: number
    points_for: number
    points_against: number
    expected_wins: number
    luck_delta: number
    lineup_efficiency: number
    bench_points_lost: number
    bench_losses: number
    final_standing: number
    made_playoffs: boolean
  }>
  luck_chart: { labels: number[]; series: ChartSeries[] }
}

export interface SeasonStanding {
  rank: number
  team: string
  manager: ManagerRef
  wins: number
  losses: number
  ties: number
  points_for: number
  points_against: number
  expected_wins: number
  luck_delta: number
  made_playoffs: boolean
}

export interface FingerprintWeek {
  week: number
  score: number
  won: boolean
}

export interface SeasonFingerprints {
  weeks: number[]
  league_median: number
  max_score: number
  teams: Array<{ manager: string; final_standing: number; weeks: FingerprintWeek[] }>
}

export interface SeasonDetail {
  year: number
  is_complete: boolean
  lineups_available: boolean
  champion: SeasonStanding | null
  standings: SeasonStanding[]
  fingerprints: SeasonFingerprints | null
}

export interface H2HCell {
  wins: number
  losses: number
  ties: number
  win_pct: number | null
}

export interface H2HMatrix {
  managers: ManagerRef[]
  matrix: Array<Array<H2HCell | null>>
}

// --- Endpoint helpers ---

export const getHealth = () => apiGet<HealthResponse>('/health/')
export const getLeagueOverview = () => apiGet<LeagueOverview>('/league/')
export const getManagers = () => apiGet<ManagerCareerRow[]>('/managers/')
export const getManager = (id: number | string) => apiGet<ManagerProfile>(`/managers/${id}/`)
export const getSeason = (year: number | string) => apiGet<SeasonDetail>(`/seasons/${year}/`)
export interface LeagueTrends {
  scoring_evolution: { labels: number[]; series: ChartSeries[] }
  weekly_distribution: { labels: number[]; boxes: number[][] }
  positional_share: { labels: number[]; series: ChartSeries[] }
}

export interface DraftPickRow {
  overall_pick: number
  round: number
  round_pick: number
  team: string
  manager: ManagerRef | null
  player_name: string
  position: string
  season_points: number
  points_over_replacement: number
  adp: number | null
  adp_delta: number | null
}

export interface SeasonDraft {
  year: number
  picks: DraftPickRow[]
  round_value_curve: { labels: number[]; series: ChartSeries[] }
  scatter: number[][]
}

export interface AwardEntry {
  slug: string
  title: string
  winner: ManagerRef | null
  value: number
  context: Record<string, unknown>
}

export interface LeagueAwards {
  seasons: Array<{ year: number; awards: AwardEntry[] }>
  all_time: AwardEntry[]
}

export interface RecordRow {
  manager: ManagerRef
  year: number
  value: number
}

export interface RecordBook {
  most_points_season: RecordRow[]
  luckiest_seasons: RecordRow[]
  biggest_bench_disasters: RecordRow[]
}

export interface H2HPair {
  manager_a: ManagerRef
  manager_b: ManagerRef
  record: {
    a_wins: number
    b_wins: number
    ties: number
    a_points?: number
    b_points?: number
    playoff_meetings?: number
    largest_margin?: number
  }
}

export const getH2HMatrix = () => apiGet<H2HMatrix>('/h2h/matrix/')
export const getH2HPair = (a: number | string, b: number | string) =>
  apiGet<H2HPair>(`/h2h/${a}/${b}/`)
export const getTrends = () => apiGet<LeagueTrends>('/trends/')
export const getAwards = () => apiGet<LeagueAwards>('/awards/')
export const getRecords = () => apiGet<RecordBook>('/records/')
export const getSeasonDraft = (year: number | string) =>
  apiGet<SeasonDraft>(`/seasons/${year}/draft/`)

export interface DraftPatternPick {
  round: number
  overall_pick: number
  position: string
  player_name: string
  is_keeper: boolean
  adp_delta: number | null
  points_over_replacement: number
  season_points: number
}

export interface DraftPatternDraft {
  year: number
  slot: number
  draft_por: number
  picks: DraftPatternPick[]
}

export interface DraftPatternProfile {
  opening: {
    signature: string
    count: number
    drafts: number
    all: Array<{ signature: string; count: number }>
  }
  position_shares: Record<string, Record<string, number>>
  avg_first_round: Record<string, number>
  avg_adp_delta: number | null
  reach_rate: number | null
  value_rate: number | null
  adp_picks: number
  total_picks: number
  avg_draft_por: number
  projection: { picks: number; beat_rate: number | null; avg_delta: number | null }
  runs: { started: number; joined: number; panic_joins: number }
}

export interface PositionRun {
  year: number
  position: string
  start_pick: number
  length: number
  picks: Array<{ overall_pick: number; player_name: string; manager: string; panic: boolean }>
}

export interface ProjectionEvent {
  year: number
  player_name: string
  position: string
  round: number
  manager: string
  projected: number
  actual: number
  delta: number
}

export interface DraftPatternManager {
  manager: ManagerRef
  profile: DraftPatternProfile
  drafts: DraftPatternDraft[]
}

export interface DraftPatterns {
  seasons: number[]
  rounds: number
  adp_swing_threshold: number
  managers: DraftPatternManager[]
  projection: {
    scale: string | null
    matched_picks: number
    steals: ProjectionEvent[]
    busts: ProjectionEvent[]
  }
  position_runs: { min_length: number; total: number; longest: PositionRun[] }
}

export const getDraftPatterns = () => apiGet<DraftPatterns>('/drafts/patterns/')

export interface SuggestValueBand {
  p10: number
  p25: number
  p50: number
  p75: number
  p90: number
  n: number
}

export interface SuggestPlayer {
  player_name: string
  position: string
  adp: number
  expected_pick: number
  ci80: [number, number]
  p_available_now: number
  p_available_next: number | null
  value_band: SuggestValueBand | null
  projected_points: number | null
  projected_range: [number, number] | null
  expert: {
    rank: number | null
    tier: string | null
    risk: number | null
    upside: number | null
    edge: number | null
  } | null
  league_history: { burned: string[]; loyal: string[] } | null
  last_season: { points_over_replacement: number; position_rank: number } | null
  monte_carlo: {
    points: number | null
    range: [number | null, number | null]
    vor: number | null
    vor_range: [number | null, number | null]
    p_position_1: number | null
    p_top_3: number | null
    p_starter: number | null
    contingent_gain: number | null
    behind: string | null
    ceiling_volume_ratio: number | null
    ceiling_td_dependence: number | null
    playoff_delta: number | null
    roster_fit: {
      average_correlation: number | null
      average_tail_lift: number | null
      pairs: Array<{
        player: string
        correlation: number | null
        tail_lift: number | null
        p_both_boom: number | null
      }>
    } | null
  } | null
}

export interface AdpCalibration {
  bias: number
  sigma: number
  n: number
}

export interface DraftSuggestions {
  adp_season: number
  value_season: number | null
  projection_season: number | null
  projection_scale: string | null
  expert_season: number | null
  gap_forecast: {
    expected_taken: Record<string, number>
    tier_survival: Record<string, { tier: string; p_any_next: number; players_left: number }>
  } | null
  pick: number
  round: number
  teams: number
  slot: number | null
  next_pick: number | null
  rounds: number
  calibration: { overall: AdpCalibration | null; by_position: Record<string, AdpCalibration> } | null
  simulation_model: {
    season: number
    simulations: number
    scoring: string
    generated_at: string
    weekly_capture: boolean
    snapshot_players: number
    board_matches: number
  } | null
  players: SuggestPlayer[]
}

export const getDraftSuggestions = (params: {
  pick: number
  teams?: number
  slot?: number
  position?: string
  roster?: string[]
}) => {
  const query = new URLSearchParams()
  query.set('pick', String(params.pick))
  if (params.teams) query.set('teams', String(params.teams))
  if (params.slot) query.set('slot', String(params.slot))
  if (params.position) query.set('position', params.position)
  for (const player of params.roster ?? []) query.append('roster', player)
  return apiGet<DraftSuggestions>(`/drafts/suggest/?${query.toString()}`)
}

export interface SetupManagerRow {
  id: number
  guid: string
  display_name: string
  real_name: string
  predicted_real_name: string
  email: string
  merged_into: ManagerRef | null
  seasons: Array<{ year: number; team: string }>
  merge_suggestion: { target: ManagerRef; reason: string } | null
}

export interface SetupManagers {
  managers: SetupManagerRow[]
}

export interface SetupManagerUpdate {
  id: number
  real_name?: string
  email?: string
  merged_into?: number | null
}

export interface SetupSaveResult {
  updated: number
  merges_changed: number
  analytics_recomputed: boolean
}

export const getSetupManagers = () => apiGet<SetupManagers>('/setup/managers/')
export const saveSetupManagers = (managers: SetupManagerUpdate[]) =>
  apiPost<SetupSaveResult>('/setup/managers/', { managers })

export interface PlayerRef {
  id: number
  name: string
  position: string
}

// One row of the player list. Career mode fills `seasons` + `best_position_rank`;
// season mode fills `season` + `position_rank`.
export interface PlayerListRow {
  player: PlayerRef
  seasons?: number
  best_position_rank?: number
  season?: number
  position_rank?: number
  total_points: number
  started_points: number
  bench_points: number
  weeks_rostered: number
  weeks_started: number
  points_over_replacement: number
}

export interface PlayersResponse {
  mode: 'career' | 'season'
  season: number | null
  available_seasons: number[]
  players: PlayerListRow[]
  note: string
}

export interface PlayerWeekEntry {
  week: number
  points: number
  started: boolean
  slot: string
  manager: ManagerRef | null
  team: string
}

export interface PlayerBestWeek extends PlayerWeekEntry {
  year: number
}

export interface PlayerDetail {
  player: PlayerRef
  career: {
    seasons: number
    total_points: number
    started_points: number
    bench_points: number
    weeks_rostered: number
    weeks_started: number
    points_over_replacement: number
    best_position_rank: number | null
    best_week: PlayerBestWeek | null
  }
  seasons: Array<{
    year: number
    position: string
    total_points: number
    started_points: number
    bench_points: number
    weeks_rostered: number
    weeks_started: number
    points_over_replacement: number
    position_rank: number
  }>
  managers: Array<{
    year: number
    manager: ManagerRef
    total_points: number
    started_points: number
    bench_points: number
    weeks_rostered: number
    weeks_started: number
  }>
  draft_picks: Array<{
    year: number
    round: number
    round_pick: number
    overall_pick: number
    is_keeper: boolean
    manager: ManagerRef | null
  }>
  weekly: Array<{ year: number; weeks: PlayerWeekEntry[] }>
}

export interface PlayersQuery {
  season?: number | null
  position?: string
  sort?: 'por' | 'points'
  q?: string
  limit?: number
}

export const getPlayers = (params: PlayersQuery = {}) => {
  const qs = new URLSearchParams()
  if (params.season != null) qs.set('season', String(params.season))
  if (params.position) qs.set('position', params.position)
  if (params.sort) qs.set('sort', params.sort)
  if (params.q) qs.set('q', params.q)
  if (params.limit != null) qs.set('limit', String(params.limit))
  const query = qs.toString()
  return apiGet<PlayersResponse>(`/players/${query ? `?${query}` : ''}`)
}
export const getPlayerDetail = (id: number | string) =>
  apiGet<PlayerDetail>(`/players/${id}/`)

export interface MuseumGame {
  year: number | null
  week: number | null
  manager: string
  opponent: string
  score: number | null
  opponent_score: number | null
  value: number
}

export interface MuseumExhibit {
  slug: string
  title: string
  formula: string
  entries: MuseumGame[]
}

export interface Museum {
  exhibits: MuseumExhibit[]
}

export const getMuseum = () => apiGet<Museum>('/museum/')

export interface ScoutingTrait {
  key: string
  label: string
  definition: string
  value: number
  percentile: number | null
}

export interface ScoutingReport {
  manager: ManagerRef
  qualified: boolean
  min_seasons: number
  seasons: number
  pool_size: number
  traits: ScoutingTrait[]
}

export const getManagerScouting = (id: number | string) =>
  apiGet<ScoutingReport>(`/managers/${id}/scouting/`)
