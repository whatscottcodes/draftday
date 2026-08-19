from datetime import datetime

from pydantic import BaseModel, Field


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    manager_name: str = ""


class LeagueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    season: str = Field(min_length=1, max_length=20)
    num_teams: int = Field(ge=2, le=32)
    num_rounds: int = Field(ge=1, le=40)
    teams: list[TeamIn] = Field(min_length=2)


class TeamOut(BaseModel):
    id: int
    name: str
    draft_position: int
    manager_name: str
    access_token: str
    roster_count: int = 0
    keeper_count: int = 0

    model_config = {"from_attributes": True}


class LeagueCreated(BaseModel):
    id: int
    name: str
    season: str
    num_teams: int
    num_rounds: int
    status: str
    access_token: str
    teams: list[TeamOut]


class SlotUpdate(BaseModel):
    drafting_team_id: int


class DraftOrderItem(BaseModel):
    position: int = Field(ge=1)
    team_id: int


class DraftOrderIn(BaseModel):
    order: list[DraftOrderItem]


class RosterUpdate(BaseModel):
    slots: list[str]


class KeeperIn(BaseModel):
    team_id: int
    player_id: int
    round: int = Field(ge=1)


class KeeperPickIn(BaseModel):
    player_id: int


class PickIn(BaseModel):
    slot_id: int | None = None
    team_id: int | None = None
    player_id: int
    override: bool = False


class TeamPickIn(BaseModel):
    player_id: int


class PlayerImportRow(BaseModel):
    player_id: str = ""
    name: str = Field(min_length=1)
    position: str = ""
    nfl_team: str = ""
    status: str = "available"
    rank: int | None = None
    adp: float | None = None
    bye_week: str | None = None
    upside: str | None = None
    bust: str | None = None
    sos_season: str | None = None
    ecr_vs_adp: str | None = None


class PlayerImport(BaseModel):
    players: list[PlayerImportRow]


class CsvTextIn(BaseModel):
    csv: str = Field(min_length=1)


class YahooConfigIn(BaseModel):
    league_id_external: str = ""
    game_id: int | None = None
    game_code: str = "nfl"
    season_id: str = ""
    week: int | None = None
    consumer_key: str = ""
    consumer_secret: str = ""


class YahooCodeIn(BaseModel):
    code: str = Field(min_length=1)


class KeeperMappingItem(BaseModel):
    team_id: int
    draft_name: str = ""
    yahoo_name: str = ""


class KeeperMappingsIn(BaseModel):
    mappings: list[KeeperMappingItem] = []


class KeeperCandidateAdjust(BaseModel):
    team_id: int
    player_name: str
    cost_round: int | None = None
    keepable: bool = True


class KeeperCandidateRow(BaseModel):
    player_name: str = Field(min_length=1)
    position: str = ""
    nfl_team: str = ""
    player_id_external: str = ""
    cost_round: int = Field(ge=1)
    years_kept: int = 0
    keepable_until_year: str = ""


class KeeperTeamSave(BaseModel):
    team_id: int
    candidates: list[KeeperCandidateRow] = []


class KeeperSaveIn(BaseModel):
    teams: list[KeeperTeamSave] = []


class UseDraftIn(BaseModel):
    draft_league_id: int
    role: str = "previous"


class ValidationIssue(BaseModel):
    severity: str  # "error" | "warning"
    code: str
    message: str


class ValidationReport(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []


class PickOut(BaseModel):
    id: int
    slot_id: int
    pick_number: int
    round: int
    team_id: int
    team_name: str
    player_id: int
    player_name: str
    position: str
    nfl_team: str
    pick_type: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class DraftState(BaseModel):
    league_id: int
    league_name: str
    season: str
    num_teams: int
    num_rounds: int
    status: str
    current_slot: dict | None = None
    teams: list[dict] = []
    board: list[dict] = []
    recent_picks: list[dict] = []
    top_available: list[dict] = []
    available_count: int = 0
    updated_at: str = ""


class TeamState(BaseModel):
    league_id: int
    league_name: str
    season: str
    status: str
    team_id: int
    team_name: str
    draft_position: int
    on_the_clock: bool
    current_slot: dict | None = None
    my_next_slot: dict | None = None
    roster: list[dict] = []
    keepers: list[dict] = []
    keeper_candidates: list[dict] = []
    keeper_count: int = 0
    max_keepers: int = 3
    recent_picks: list[dict] = []
    upcoming_picks: list[dict] = []
    next_picks: list[dict] = []
    roster_slots: list[str] = []
    roster_by_slot: list[dict] = []
    bench: list[dict] = []
    players: list[dict] = []
    available_count: int = 0