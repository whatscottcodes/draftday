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

export interface NextPick {
  pick_number: number;
  round: number;
  drafting_team_id: number;
  drafting_team_name: string;
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
  keepers: {
    keeper_id: number;
    player_id: number;
    player_name: string;
    position: string;
    nfl_team: string;
    round: number;
  }[];
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