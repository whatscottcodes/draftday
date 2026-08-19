from __future__ import annotations

import asyncio
import csv
import io
import re
import secrets

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..draft import engine, state as state_builder, validation
from ..draft.engine import DraftError
from ..draft.keepers import (
    candidate_dict,
    clear_candidates,
    import_candidate_rows,
    parse_candidate_csv,
)
from ..loop import main_loop
from ..models import (
    DEFAULT_ROSTER_SLOTS,
    DraftEvent,
    DraftSlot,
    Keeper,
    KeeperCandidate,
    League,
    LeagueStatus,
    Pick,
    Player,
    Ranking,
    Team,
)
from ..schemas import (
    CsvTextIn,
    DraftOrderIn,
    DraftState,
    KeeperIn,
    KeeperPickIn,
    LeagueCreate,
    LeagueCreated,
    PickIn,
    PlayerImport,
    PlayerImportRow,
    RosterUpdate,
    SlotUpdate,
    TeamPickIn,
    TeamState,
    ValidationReport,
)
from ..ws import manager

router = APIRouter(prefix="/api")


def _get_league(db: Session, token: str) -> League:
    league = engine.get_league_by_token(db, token)
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    return league


def _get_team(db: Session, league: League, team_token: str) -> Team:
    team = engine.get_team_by_token(db, team_token)
    if team is None or team.league_id != league.id:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------- setup


@router.get("/leagues")
def list_leagues(db: Session = Depends(get_db)):
    leagues = db.scalars(select(League).order_by(League.created_at.desc()))
    return [
        {
            "id": l.id,
            "name": l.name,
            "season": l.season,
            "status": l.status,
            "num_teams": l.num_teams,
            "num_rounds": l.num_rounds,
            "access_token": l.access_token,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in leagues
    ]


@router.delete("/draft/{token}/admin/delete")
def delete_league(
    token: str, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    engine.delete_league(db, league)
    _commit(db)
    return {"ok": True}


@router.post("/leagues", response_model=LeagueCreated)
def create_league(body: LeagueCreate, db: Session = Depends(get_db)):
    if len(body.teams) != body.num_teams:
        raise HTTPException(
            status_code=400,
            detail=f"num_teams must equal the number of teams provided ({len(body.teams)})",
        )
    league = League(
        name=body.name,
        season=body.season,
        num_teams=body.num_teams,
        num_rounds=body.num_rounds,
        status=LeagueStatus.SETUP,
        access_token=secrets.token_urlsafe(12),
        roster_slots=DEFAULT_ROSTER_SLOTS,
    )
    db.add(league)
    db.flush()
    teams: list[Team] = []
    for i, team_in in enumerate(body.teams, start=1):
        team = Team(
            league_id=league.id,
            name=team_in.name,
            draft_position=i,
            manager_name=team_in.manager_name,
            access_token=secrets.token_urlsafe(8),
        )
        db.add(team)
        teams.append(team)
    db.flush()
    engine.create_draft_slots(db, league)
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="league_created",
            payload={"name": body.name},
        )
    )
    _commit(db)
    return {
        "id": league.id,
        "name": league.name,
        "season": league.season,
        "num_teams": league.num_teams,
        "num_rounds": league.num_rounds,
        "status": league.status,
        "access_token": league.access_token,
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "draft_position": t.draft_position,
                "manager_name": t.manager_name,
                "access_token": t.access_token,
                "roster_count": 0,
                "keeper_count": 0,
            }
            for t in teams
        ],
    }


# ---------------------------------------------------------------- admin


@router.get("/draft/{token}/admin/config")
def admin_config(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    slots = list(
        db.scalars(
            select(DraftSlot)
            .where(DraftSlot.league_id == league.id)
            .order_by(DraftSlot.pick_number)
        )
    )
    teams = sorted(league.teams, key=lambda t: t.draft_position)
    players = list(
        db.scalars(select(Player).where(Player.league_id == league.id).order_by(Player.name))
    )
    ranks = {
        r.player_id: r
        for r in db.scalars(select(Ranking).where(Ranking.league_id == league.id))
    }
    keepers = list(
        db.scalars(select(Keeper).where(Keeper.league_id == league.id))
    )
    picked_player_ids = {
        p.player_id
        for p in db.scalars(select(Pick).where(Pick.league_id == league.id))
    }
    slot_statuses = engine.bulk_slot_statuses(db, slots)
    errors, warnings = validation.validate_draft_configuration(db, league)

    return {
        "league": {
            "id": league.id,
            "name": league.name,
            "season": league.season,
            "num_teams": league.num_teams,
            "num_rounds": league.num_rounds,
            "status": league.status,
            "roster_slots": league.roster_slots or DEFAULT_ROSTER_SLOTS,
        },
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "draft_position": t.draft_position,
                "manager_name": t.manager_name,
                "access_token": t.access_token,
            }
            for t in teams
        ],
        "slots": [
            {
                "slot_id": s.id,
                "pick_number": s.pick_number,
                "round": s.round,
                "original_team_id": s.original_team_id,
                "drafting_team_id": s.drafting_team_id,
                "status": slot_statuses[s.id],
            }
            for s in slots
        ],
        "keepers": [
            {
                "keeper_id": k.id,
                "team_id": k.team_id,
                "team_name": k.team.name,
                "player_id": k.player_id,
                "player_name": k.player.name,
                "position": k.player.position,
                "round": k.round,
            }
            for k in keepers
        ],
        "keeper_candidates": [
            {
                **candidate_dict(c, False),
                "team_id": c.team_id,
                "team_name": c.team.name,
            }
            for c in db.scalars(
                select(KeeperCandidate)
                .where(KeeperCandidate.league_id == league.id)
                .order_by(KeeperCandidate.cost_round, KeeperCandidate.player_name)
            )
        ],
        "players": [
            {
                "id": p.id,
                "player_id": p.player_id,
                "name": p.name,
                "position": p.position,
                "nfl_team": p.nfl_team,
                "status": p.status,
                "rank": ranks[p.id].rank if p.id in ranks else None,
                "adp": ranks[p.id].adp if p.id in ranks else None,
                "tier": (p.extra or {}).get("tier"),
                "bye_week": (p.extra or {}).get("bye_week"),
                "upside": (p.extra or {}).get("upside"),
                "bust": (p.extra or {}).get("bust"),
                "sos_season": (p.extra or {}).get("sos_season"),
                "ecr_vs_adp": (p.extra or {}).get("ecr_vs_adp"),
                "taken": p.id in picked_player_ids,
            }
            for p in players
        ],
        "validation": {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
        },
    }


@router.put("/draft/{token}/admin/slots/{slot_id}")
def update_slot(
    token: str, slot_id: int, body: SlotUpdate, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    try:
        engine.update_draft_slot_owner(db, league, slot_id, body.drafting_team_id)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True}


@router.post("/draft/{token}/admin/draft-order")
def set_draft_order(
    token: str, body: DraftOrderIn, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    try:
        engine.set_draft_order(
            db, league, [(item.position, item.team_id) for item in body.order]
        )
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True}


@router.put("/draft/{token}/admin/roster")
def update_roster(
    token: str, body: RosterUpdate, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise HTTPException(
            status_code=400,
            detail="Roster slots can only be changed before the draft starts",
        )
    slots = [s.strip() for s in body.slots if s.strip()]
    if not slots or len(slots) > 30:
        raise HTTPException(status_code=400, detail="Provide between 1 and 30 slots")
    league.roster_slots = slots
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "roster_slots": slots}


@router.post("/draft/{token}/admin/keepers")
def create_keeper(token: str, body: KeeperIn, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    try:
        engine.add_keeper(db, league, body.team_id, body.player_id, body.round)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True}


@router.delete("/draft/{token}/admin/keepers/candidates")
def clear_keeper_candidates(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise HTTPException(
            status_code=400,
            detail="Keepers can only be changed before the draft starts",
        )
    count = clear_candidates(db, league)
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "cleared": count}


@router.delete("/draft/{token}/admin/keepers/{keeper_id}")
def delete_keeper(token: str, keeper_id: int, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    try:
        engine.remove_keeper(db, league, keeper_id)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True}


@router.post("/draft/{token}/admin/import/keepers")
def import_keepers(
    token: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise HTTPException(
            status_code=400,
            detail="Keepers can only be imported before the draft starts",
        )
    rows: list[dict] = []
    warnings: list[str] = []
    for file in files:
        raw = file.file.read().decode("utf-8-sig")
        stem = (file.filename or "").rsplit(".", 1)[0].strip()
        file_rows, file_warnings = parse_candidate_csv(raw, stem)
        rows.extend(file_rows)
        warnings.extend(file_warnings)
    if not rows:
        raise HTTPException(status_code=400, detail="No keeper candidates found")
    stats = import_candidate_rows(db, league, rows, source="import")
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "stats": stats, "warnings": warnings}


@router.post("/draft/{token}/admin/import/json")
def import_players_json(
    token: str, body: PlayerImport, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    if league.status != LeagueStatus.SETUP:
        raise HTTPException(status_code=400, detail="Players can only be imported during setup")
    for row in body.players:
        _upsert_player(db, league, row)
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "imported": len(body.players)}


@router.post("/draft/{token}/admin/import/csv")
def import_players_csv(
    token: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    if league.status != LeagueStatus.SETUP:
        raise HTTPException(status_code=400, detail="Players can only be imported during setup")
    raw = file.file.read().decode("utf-8-sig")
    rows = parse_players_csv(raw)
    if not rows:
        raise HTTPException(status_code=400, detail="Empty CSV file")
    for row in rows:
        _upsert_player(db, league, row)
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "imported": len(rows)}


@router.post("/draft/{token}/admin/import/text")
def import_players_text(
    token: str, body: CsvTextIn, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    if league.status != LeagueStatus.SETUP:
        raise HTTPException(status_code=400, detail="Players can only be imported during setup")
    rows = parse_players_csv(body.csv)
    if not rows:
        raise HTTPException(status_code=400, detail="Empty CSV text")
    for row in rows:
        _upsert_player(db, league, row)
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "imported": len(rows)}


def _norm_key(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_position(value: str) -> str:
    """Strip a trailing rank/tier number from a position.

    FantasyPros exports positions like "RB1" or "WR12" (position plus
    in-position rank); position filters expect just "RB" or "WR".
    """
    return re.sub(r"\d+$", "", (value or "").strip().upper()).strip()


def parse_players_csv(raw: str) -> list[PlayerImportRow]:
    """Parse a player/ranking CSV.

    Auto-detects the FantasyPros export format
    (RK,TIERS,PLAYER NAME,TEAM,POS,BYE WEEK,UPSIDE,BUST,SOS SEASON,ECR VS. ADP)
    as well as the generic format
    (player_id,name,position,nfl_team,status,rank,adp).
    """
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []

    header_idx = 0
    for i, line in enumerate(lines[:8]):
        lowered = line.lower()
        if "player name" in lowered or lowered.startswith("rk"):
            header_idx = i
            break

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])), skipinitialspace=True)
    if reader.fieldnames is None:
        return []

    keys = {_norm_key(k): k for k in reader.fieldnames}
    is_fantasypros = "player_name" in keys or (
        "rk" in keys and "pos" in keys and "team" in keys
    )

    rows: list[PlayerImportRow] = []
    for row in reader:
        if is_fantasypros:
            name = (row.get(keys.get("player_name", "")) or "").strip()
            if not name:
                continue
            rk = _int_or_none(row.get(keys.get("rk", "")))
            rows.append(
                PlayerImportRow(
                    player_id=(row.get(keys.get("player_id", "")) or "").strip(),
                    name=name,
                    position=_normalize_position(row.get(keys.get("pos", ""))),
                    nfl_team=(row.get(keys.get("team", "")) or "").strip().upper(),
                    status="available",
                    rank=rk,
                    tier=(row.get(keys.get("tiers", "")) or "").strip(),
                    bye_week=(row.get(keys.get("bye_week", "")) or "").strip(),
                    upside=(row.get(keys.get("upside", "")) or "").strip(),
                    bust=(row.get(keys.get("bust", "")) or "").strip(),
                    sos_season=(row.get(keys.get("sos_season", "")) or "").strip(),
                    ecr_vs_adp=(row.get(keys.get("ecr_vs_adp", "")) or "").strip(),
                )
            )
        else:
            name = (row.get(keys.get("name", "")) or "").strip()
            if not name:
                continue
            rows.append(
                PlayerImportRow(
                    player_id=(row.get(keys.get("player_id", "")) or "").strip(),
                    name=name,
                    position=_normalize_position(row.get(keys.get("position", ""))),
                    nfl_team=(row.get(keys.get("nfl_team", "")) or "").strip().upper(),
                    status=(row.get(keys.get("status", "")) or "available").strip(),
                    rank=_int_or_none(row.get(keys.get("rank", ""))),
                    adp=_float_or_none(row.get(keys.get("adp", ""))),
                )
            )
    return rows


def _int_or_none(value: str | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(float(str(value).strip().replace(",", "")))
    except ValueError:
        return None


def _float_or_none(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except ValueError:
        return None


def _upsert_player(db: Session, league: League, row: PlayerImportRow) -> None:
    existing = None
    if row.player_id:
        existing = db.scalar(
            select(Player).where(
                Player.league_id == league.id, Player.player_id == row.player_id
            )
        )
    if existing is None:
        existing = db.scalar(
            select(Player).where(
                Player.league_id == league.id, Player.name == row.name
            )
        )
    if existing is None:
        existing = Player(
            league_id=league.id,
            player_id=row.player_id or f"auto-{secrets.token_hex(4)}",
            name=row.name,
            position=_normalize_position(row.position),
            nfl_team=row.nfl_team,
            status=row.status,
        )
        db.add(existing)
        db.flush()
    else:
        existing.name = row.name
        existing.position = _normalize_position(row.position) or existing.position
        existing.nfl_team = row.nfl_team or existing.nfl_team
        existing.status = row.status or existing.status
    extra = {
        key: value
        for key, value in {
            "tier": row.tier,
            "bye_week": row.bye_week,
            "upside": row.upside,
            "bust": row.bust,
            "sos_season": row.sos_season,
            "ecr_vs_adp": row.ecr_vs_adp,
        }.items()
        if value not in (None, "")
    }
    if extra:
        merged = dict(existing.extra or {})
        merged.update(extra)
        existing.extra = merged
    if row.rank is not None:
        ranking = db.scalar(
            select(Ranking).where(
                Ranking.league_id == league.id, Ranking.player_id == existing.id
            )
        )
        if ranking is None:
            db.add(
                Ranking(
                    league_id=league.id,
                    player_id=existing.id,
                    rank=row.rank,
                    adp=row.adp,
                )
            )
        else:
            ranking.rank = row.rank
            ranking.adp = row.adp if row.adp is not None else ranking.adp


@router.post("/draft/{token}/admin/validate", response_model=ValidationReport)
def validate_league(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    errors, warnings = validation.validate_draft_configuration(db, league)
    return {"valid": not errors, "errors": errors, "warnings": warnings}


@router.post("/draft/{token}/admin/start")
def start_league(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    try:
        validation.start_draft(db, league)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "status": league.status}


@router.post("/draft/{token}/admin/reopen")
def reopen_league(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    try:
        validation.reopen_draft(db, league)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "status": league.status}


@router.post("/draft/{token}/admin/picks")
def admin_pick(token: str, body: PickIn, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    current = engine.current_slot(db, league)
    slot_id = body.slot_id or (current.id if current else None)
    team_id = body.team_id
    if slot_id is None:
        raise HTTPException(status_code=400, detail="slot_id is required")
    if team_id is None:
        slot = db.get(DraftSlot, slot_id)
        team_id = slot.drafting_team_id if slot else None
    if team_id is None:
        raise HTTPException(status_code=400, detail="team_id is required")
    try:
        engine.make_pick(
            db,
            league,
            slot_id,
            team_id,
            body.player_id,
            pick_type="commissioner",
            override=body.override,
        )
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "status": league.status}


@router.post("/draft/{token}/admin/undo")
def admin_undo(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    try:
        engine.undo_last_pick(db, league)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "status": league.status}


@router.get("/draft/{token}/admin/export")
def export_league(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    return engine.export_results(db, league)


@router.get("/draft/{token}/admin/events")
def admin_events(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    events = list(
        db.scalars(
            select(DraftEvent)
            .where(DraftEvent.league_id == league.id)
            .order_by(DraftEvent.id)
        )
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "payload": e.payload,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in events
    ]


# ---------------------------------------------------------------- team / display


@router.get("/draft/{token}/display", response_model=DraftState)
def display_state(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    return state_builder.build_draft_state(db, league)


@router.get("/draft/{token}/team/{team_token}", response_model=TeamState)
def team_state(token: str, team_token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    team = _get_team(db, league, team_token)
    return state_builder.build_team_state(db, league, team)


@router.get("/draft/{token}/rosters")
def team_rosters(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    return state_builder.build_rosters(db, league)


@router.post("/draft/{token}/team/{team_token}/picks")
def team_pick(
    token: str, team_token: str, body: TeamPickIn, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    team = _get_team(db, league, team_token)
    current = engine.current_slot(db, league)
    if current is None:
        raise HTTPException(status_code=400, detail="No pick is currently available")
    if current.drafting_team_id != team.id:
        raise HTTPException(status_code=400, detail="Your team is not on the clock")
    try:
        engine.make_pick(
            db, league, current.id, team.id, body.player_id, pick_type="live"
        )
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True, "status": league.status}


@router.post("/draft/{token}/team/{team_token}/keepers")
def team_create_keeper(
    token: str, team_token: str, body: KeeperPickIn, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    team = _get_team(db, league, team_token)
    try:
        engine.team_add_keeper(db, league, team, body.player_id)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True}


@router.delete("/draft/{token}/team/{team_token}/keepers/{keeper_id}")
def team_delete_keeper(
    token: str, team_token: str, keeper_id: int, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    team = _get_team(db, league, team_token)
    keeper = db.get(Keeper, keeper_id)
    if keeper is None or keeper.league_id != league.id or keeper.team_id != team.id:
        raise HTTPException(status_code=404, detail="Keeper not found")
    try:
        engine.remove_keeper(db, league, keeper_id)
    except DraftError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _commit(db)
    _schedule_broadcast(league)
    return {"ok": True}


# ---------------------------------------------------------------- websocket


def _build_state(league: League) -> dict:
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        return state_builder.build_draft_state(db, league)
    finally:
        db.close()


async def _broadcast(league: League) -> None:
    data = await asyncio.to_thread(_build_state, league)
    await manager.broadcast(league.id, {"type": "state", "data": data})


def _schedule_broadcast(league: League) -> None:
    loop = main_loop
    if loop is not None and not loop.is_closed():
        asyncio.run_coroutine_threadsafe(_broadcast(league), loop)


@router.websocket("/draft/{token}/ws")
async def draft_ws(token: str, websocket: WebSocket, db: Session = Depends(get_db)):
    league = await asyncio.to_thread(engine.get_league_by_token, db, token)
    if league is None:
        await websocket.close(code=4404)
        return
    await manager.connect(league.id, websocket)
    try:
        state = await asyncio.to_thread(state_builder.build_draft_state, db, league)
        await websocket.send_json({"type": "state", "data": state})
    finally:
        # The receive loop below lives for the whole connection; end the
        # read transaction now so the pooled connection is released instead
        # of pinning one QueuePool slot (size 5 / overflow 10) per client.
        db.rollback()
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        manager.disconnect(league.id, websocket)