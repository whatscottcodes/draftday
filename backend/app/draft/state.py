from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DraftSlot, Keeper, League, Pick, Team
from . import engine


def _slot_dict(db: Session, slot: DraftSlot, num_teams: int) -> dict:
    pick = db.scalar(select(Pick).where(Pick.draft_slot_id == slot.id))
    keeper = None
    if pick is None:
        keeper = db.scalar(
            select(Keeper).where(
                Keeper.league_id == slot.league_id,
                Keeper.round == slot.round,
                Keeper.team_id == slot.drafting_team_id,
            )
        )
    return {
        "slot_id": slot.id,
        "pick_number": slot.pick_number,
        "round": slot.round,
        "round_pick": ((slot.pick_number - 1) % num_teams) + 1,
        "original_team_id": slot.original_team_id,
        "drafting_team_id": slot.drafting_team_id,
        "status": engine.slot_status(db, slot),
        "keeper_round": keeper.round if keeper else None,
    }


def _pick_dict(db: Session, pick: Pick) -> dict:
    return {
        "id": pick.id,
        "slot_id": pick.draft_slot_id,
        "pick_number": pick.slot.pick_number,
        "round": pick.slot.round,
        "team_id": pick.team_id,
        "team_name": pick.team.name,
        "player_id": pick.player_id,
        "player_name": pick.player.name,
        "position": pick.player.position,
        "nfl_team": pick.player.nfl_team,
        "pick_type": pick.pick_type,
        "timestamp": pick.timestamp.isoformat() if pick.timestamp else None,
    }


def build_draft_state(db: Session, league: League) -> dict:
    teams = sorted(
        db.scalars(select(Team).where(Team.league_id == league.id)),
        key=lambda t: t.draft_position,
    )
    picks = list(
        db.scalars(
            select(Pick)
            .where(Pick.league_id == league.id)
            .join(DraftSlot)
            .order_by(DraftSlot.pick_number)
        )
    )
    pick_by_slot = {p.draft_slot_id: p for p in picks}
    roster_counts: dict[int, int] = {}
    for p in picks:
        roster_counts[p.team_id] = roster_counts.get(p.team_id, 0) + 1

    slots = db.scalars(
        select(DraftSlot)
        .where(DraftSlot.league_id == league.id)
        .order_by(DraftSlot.pick_number)
    )
    board = []
    for slot in slots:
        entry = _slot_dict(db, slot, league.num_teams)
        pick = pick_by_slot.get(slot.id)
        if pick is not None:
            entry["player_id"] = pick.player_id
            entry["player_name"] = pick.player.name
            entry["position"] = pick.player.position
            entry["nfl_team"] = pick.player.nfl_team
            entry["pick_type"] = pick.pick_type
        board.append(entry)

    current = engine.current_slot(db, league)
    recent = picks[-8:][::-1]

    all_available = engine.available_players(db, league)
    top_available = []
    for player, rank in all_available[:20]:
        top_available.append(
            {
                "player_id": player.id,
                "player_id_external": player.player_id,
                "name": player.name,
                "position": player.position,
                "nfl_team": player.nfl_team,
                "rank": rank,
            }
        )

    return {
        "league_id": league.id,
        "league_name": league.name,
        "season": league.season,
        "num_teams": league.num_teams,
        "num_rounds": league.num_rounds,
        "status": league.status,
        "current_slot": _slot_dict(db, current, league.num_teams) if current else None,
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "draft_position": t.draft_position,
                "manager_name": t.manager_name,
                "roster_count": roster_counts.get(t.id, 0),
            }
            for t in teams
        ],
        "board": board,
        "recent_picks": [_pick_dict(db, p) for p in recent],
        "top_available": top_available,
        "available_count": len(all_available),
    }


def build_team_state(db: Session, league: League, team: Team) -> dict:
    state = build_draft_state(db, league)
    picks = list(
        db.scalars(
            select(Pick)
            .where(Pick.league_id == league.id, Pick.team_id == team.id)
            .join(DraftSlot)
            .order_by(DraftSlot.pick_number)
        )
    )
    roster = [
        {
            "player_id": p.player_id,
            "player_name": p.player.name,
            "position": p.player.position,
            "nfl_team": p.player.nfl_team,
            "pick_number": p.slot.pick_number,
            "round": p.slot.round,
            "pick_type": p.pick_type,
        }
        for p in picks
    ]
    keepers = [
        {
            "keeper_id": k.id,
            "player_id": k.player_id,
            "player_name": k.player.name,
            "position": k.player.position,
            "nfl_team": k.player.nfl_team,
            "round": k.round,
        }
        for k in db.scalars(
            select(Keeper).where(
                Keeper.league_id == league.id, Keeper.team_id == team.id
            )
        )
    ]

    current = state["current_slot"]
    on_the_clock = bool(
        current
        and league.status == "LIVE"
        and current["drafting_team_id"] == team.id
    )

    my_next = None
    if league.status in ("LIVE", "COMPLETED"):
        for slot in state["board"]:
            if slot["drafting_team_id"] == team.id and slot["status"] == "OPEN":
                my_next = slot
                break

    upcoming = []
    if current:
        current_pick = current["pick_number"]
        for slot in state["board"]:
            if (
                slot["drafting_team_id"] == team.id
                and slot["status"] == "OPEN"
                and slot["pick_number"] > current_pick
            ):
                upcoming.append(slot)

    avail = engine.available_players(db, league, limit=200)
    players = [
        {
            "player_id": p.id,
            "player_id_external": p.player_id,
            "name": p.name,
            "position": p.position,
            "nfl_team": p.nfl_team,
            "rank": rank,
        }
        for p, rank in avail
    ]

    return {
        "league_id": league.id,
        "league_name": league.name,
        "season": league.season,
        "status": league.status,
        "team_id": team.id,
        "team_name": team.name,
        "on_the_clock": on_the_clock,
        "current_slot": current,
        "my_next_slot": my_next,
        "roster": roster,
        "keepers": keepers,
        "recent_picks": state["recent_picks"],
        "upcoming_picks": upcoming,
        "players": players,
        "available_count": state["available_count"],
    }