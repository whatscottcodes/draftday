export type LeagueStatus = "SETUP" | "READY" | "LIVE" | "COMPLETED";
export type SlotStatus = "OPEN" | "FILLED" | "KEEPER";
export type PickType = "live" | "keeper" | "commissioner";

export interface TeamSummary {
  id: number;
  name: string;
  draft_position: number;
  manager_name: string;
  roster_count: number;
}

export interface BoardSlot {
  slot_id: number;
  pick_number: number;
  round: number;
  round_pick: number;
  original_team_id: number;
  drafting_team_id: number;
  status: SlotStatus;
  keeper_round: number | null;
  player_id?: number;
  player_name?: string;
  position?: string;
  nfl_team?: string;
  pick_type?: string;
}

export interface RecentPick {
  id: number;
  slot_id: number;
  pick_number: number;
  round: number;
  team_id: number;
  team_name: string;
  player_id: number;
  player_name: string;
  position: string;
  nfl_team: string;
  pick_type: PickType;
  timestamp: string | null;
}

export interface AvailablePlayer {
  player_id: number;
  player_id_external: string;
  name: string;
  position: string;
  nfl_team: string;
  rank: number | null;
  bye_week?: string;
  tier?: string;
}

export interface DraftState {
  league_id: number;
  league_name: string;
  season: string;
  num_teams: number;
  num_rounds: number;
  status: LeagueStatus;
  current_slot: BoardSlot | null;
  teams: TeamSummary[];
  board: BoardSlot[];
  recent_picks: RecentPick[];
  top_available: AvailablePlayer[];
  available_count: number;
}

export interface TeamRosterPlayer {
  player_id: number;
  player_name: string;
  position: string;
  nfl_team: string;
  pick_number: number;
  round: number;
  pick_type: PickType;
}

export interface RosterSlotEntry {
  slot: string;
  position: string;
  player: TeamRosterPlayer | null;
}

export interface NextPick {
  pick_number: number;
  round: number;
  drafting_team_id: number;
  drafting_team_name: string;
  roster?: Record<string, number>;
}

export interface TeamState {
  league_id: number;
  league_name: string;
  season: string;
  status: LeagueStatus;
  team_id: number;
  team_name: string;
  on_the_clock: boolean;
  current_slot: BoardSlot | null;
  my_next_slot: BoardSlot | null;
  roster: TeamRosterPlayer[];
  roster_slots: string[];
  roster_by_slot: RosterSlotEntry[];
  bench: TeamRosterPlayer[];
  keepers: {
    keeper_id: number;
    player_id: number;
    player_name: string;
    position: string;
    nfl_team: string;
    round: number;
  }[];
  keeper_candidates: {
    candidate_id: number;
    player_id: number;
    player_name: string;
    position: string;
    nfl_team: string;
    cost_round: number;
    years_kept: number;
    keepable_until_year: number;
    selected: boolean;
  }[];
  keeper_count: number;
  max_keepers: number;
  recent_picks: RecentPick[];
  upcoming_picks: BoardSlot[];
  next_picks: NextPick[];
  players: AvailablePlayer[];
  available_count: number;
}

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
}

export interface AdminConfig {
  league: {
    id: number;
    name: string;
    season: string;
    num_teams: number;
    num_rounds: number;
    status: LeagueStatus;
    roster_slots: string[];
  };
  teams: {
    id: number;
    name: string;
    draft_position: number;
    manager_name: string;
    access_token: string;
  }[];
  slots: {
    slot_id: number;
    pick_number: number;
    round: number;
    original_team_id: number;
    drafting_team_id: number;
    status: SlotStatus;
  }[];
  keepers: {
    keeper_id: number;
    team_id: number;
    team_name: string;
    player_id: number;
    player_name: string;
    position: string;
    round: number;
  }[];
  keeper_candidates: {
    candidate_id: number;
    team_id: number;
    team_name: string;
    player_id: number;
    player_name: string;
    position: string;
    nfl_team: string;
    cost_round: number;
    years_kept: number;
    keepable_until_year: number;
    selected: boolean;
  }[];
  players: {
    id: number;
    player_id: string;
    name: string;
    position: string;
    nfl_team: string;
    status: string;
    rank: number | null;
    adp: number | null;
    tier?: string;
    bye_week?: string;
    upside?: string;
    bust?: string;
    sos_season?: string;
    ecr_vs_adp?: string;
    taken: boolean;
  }[];
  validation: {
    valid: boolean;
    errors: ValidationIssue[];
    warnings: ValidationIssue[];
  };
}

export interface TeamRosterView {
  team_id: number;
  team_name: string;
  draft_position: number;
  roster: RosterSlotEntry[];
  bench: TeamRosterPlayer[];
}

export interface RostersState {
  league_id: number;
  league_name: string;
  season: string;
  status: LeagueStatus;
  num_teams: number;
  num_rounds: number;
  roster_slots: string[];
  teams: TeamRosterView[];
}

export interface LeagueSummary {
  id: number;
  name: string;
  season: string;
  status: LeagueStatus;
  num_teams: number;
  num_rounds: number;
  access_token: string;
  created_at: string | null;
}

export interface KeeperPreviewCandidate {
  player_name: string;
  position: string;
  nfl_team: string;
  player_id_external: string;
  cost_round: number;
  years_kept: number;
  keepable_until_year: string;
}

export interface KeeperPreviewTeam {
  team_id: number;
  team_name: string;
  candidates: KeeperPreviewCandidate[];
}

export interface KeeperSetup {
  league: {
    id: number;
    name: string;
    season: string;
    status: LeagueStatus;
    editable: boolean;
  };
  teams: { id: number; name: string; manager_name: string }[];
  draft: {
    previous_year: string;
    prior_year: string;
    draft_teams: string[];
    has_draft: boolean;
    draft_counts: Record<string, Record<string, number>>;
  };
  mappings: { team_id: number; draft_name: string; yahoo_name: string }[];
  suggested_mappings: {
    team_id: number;
    team_name: string;
    draft_name: string;
    yahoo_name: string;
  }[];
  rosters: {
    has_rosters: boolean;
    teams: string[];
    week: number | null;
    source: string;
    player_count: number;
  };
  transactions: {
    loaded: boolean;
    trade_count: number;
  };
  preview: {
    teams: KeeperPreviewTeam[];
    warnings: string[];
    saved_at: string | null;
    reviewed_team_ids: number[];
    team_saved_at: Record<string, string>;
  };
  yahoo: {
    configured: boolean;
    league_id_external: string;
    game_id: number | null;
    season_id: string;
    week: number | null;
    consumer_key: string;
    has_token: boolean;
  };
  previous_drafts: { id: number; name: string; season: string; picks: number }[];
}
