from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    DEFAULT_ROSTER_SLOTS,
    DraftSlot,
    Keeper,
    KeeperCandidate,
    League,
    LeagueStatus,
    Pick,
    Team,
)
from . import engine
from .keepers import MAX_KEEPERS_PER_TEAM, candidate_dict

FLEX_POSITIONS = {"RB", "WR", "TE"}
DEF_POSITIONS = {"DST", "DEF"}


def _slot_position(label: str) -> str:
    return re.sub(r"\d+$", "", (label or "").strip()).upper()


def _roster_player_dict(pick: Pick) -> dict:
    return {
        "player_id": pick.player_id,
        "player_name": pick.player.name,
        "position": pick.player.position,
        "nfl_team": pick.player.nfl_team,
        "pick_number": pick.slot.pick_number,
        "round": pick.slot.round,
        "pick_type": pick.pick_type,
    }


def _keeper_player_dict(keeper: Keeper, round_: int) -> dict:
    return {
        "player_id": keeper.player_id,
        "player_name": keeper.player.name,
        "position": keeper.player.position,
        "nfl_team": keeper.player.nfl_team,
        "pick_number": round_,
        "round": round_,
        "pick_type": "keeper",
    }


def assign_roster(
    slots: list[str], players: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Assign drafted players to the configured roster slots.

    Players are taken in pick order; a specific slot matches by position,
    a Flex slot takes the next RB/WR/TE, and everyone left over goes to
    the bench. Returns (roster_by_slot, bench).
    """
    roster: list[dict] = []
    remaining = list(players)
    for label in slots:
        base = _slot_position(label)
        entry: dict = {"slot": label, "position": base, "player": None}
        if base in ("FLEX", "F"):
            candidates = [p for p in remaining if p["position"] in FLEX_POSITIONS]
        elif base in DEF_POSITIONS:
            candidates = [p for p in remaining if p["position"] in DEF_POSITIONS]
        else:
            candidates = [p for p in remaining if p["position"] == base]
        if candidates:
            entry["player"] = candidates[0]
            remaining.remove(candidates[0])
        roster.append(entry)
    return roster, remaining


def _slot_dict(slot: DraftSlot, num_teams: int, pick: Pick | None, keeper: Keeper | None) -> dict:
    status = "FILLED" if pick is not None else ("KEEPER" if keeper is not None else "OPEN")
    return {
        "slot_id": slot.id,
        "pick_number": slot.pick_number,
        "round": slot.round,
        "round_pick": ((slot.pick_number - 1) % num_teams) + 1,
        "original_team_id": slot.original_team_id,
        "drafting_team_id": slot.drafting_team_id,
        "status": status,
        "keeper_round": slot.round if keeper else None,
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


def build_draft_state(
    db: Session,
    league: League,
    all_available: list[tuple[Player, int | None]] | None = None,
) -> dict:
    teams = sorted(
        db.scalars(select(Team).where(Team.league_id == league.id)),
        key=lambda t: t.draft_position,
    )
    picks = list(
        db.scalars(
            select(Pick)
            .where(Pick.league_id == league.id)
            .join(DraftSlot)
            .options(selectinload(Pick.team), selectinload(Pick.player), selectinload(Pick.slot))
            .order_by(DraftSlot.pick_number)
        )
    )
    pick_by_slot = {p.draft_slot_id: p for p in picks}
    roster_counts: dict[int, int] = {}
    for p in picks:
        roster_counts[p.team_id] = roster_counts.get(p.team_id, 0) + 1

    keepers = list(
        db.scalars(
            select(Keeper)
            .where(Keeper.league_id == league.id)
            .options(selectinload(Keeper.player))
        )
    )
    keeper_by_id = {k.id: k for k in keepers}
    keeper_slot_map = engine.keeper_slot_assignments(db, league) if keepers else {}
    slot_owner = {slot.id: keeper_id for keeper_id, slot in keeper_slot_map.items()}

    slots = list(
        db.scalars(
            select(DraftSlot)
            .where(DraftSlot.league_id == league.id)
            .order_by(DraftSlot.pick_number)
        )
    )
    board = []
    for slot in slots:
        pick = pick_by_slot.get(slot.id)
        keeper = None
        if pick is None:
            keeper = keeper_by_id.get(slot_owner.get(slot.id))
        entry = _slot_dict(slot, league.num_teams, pick, keeper)
        if pick is not None:
            entry["player_id"] = pick.player_id
            entry["player_name"] = pick.player.name
            entry["position"] = pick.player.position
            entry["nfl_team"] = pick.player.nfl_team
            entry["pick_type"] = pick.pick_type
        board.append(entry)

    current = None
    if league.status == LeagueStatus.LIVE:
        for slot in board:
            if slot["status"] == "OPEN":
                current = slot
                break
    recent = picks[-8:][::-1]

    if all_available is None:
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
                "bye_week": (player.extra or {}).get("bye_week"),
            }
        )

    return {
        "league_id": league.id,
        "league_name": league.name,
        "season": league.season,
        "num_teams": league.num_teams,
        "num_rounds": league.num_rounds,
        "status": league.status,
        "current_slot": current,
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
    avail = engine.available_players(db, league)
    state = build_draft_state(db, league, all_available=avail)
    picks = list(
        db.scalars(
            select(Pick)
            .where(Pick.league_id == league.id, Pick.team_id == team.id)
            .join(DraftSlot)
            .options(
                selectinload(Pick.player),
                selectinload(Pick.slot),
            )
            .order_by(DraftSlot.pick_number)
        )
    )
    roster = [_roster_player_dict(p) for p in picks]
    roster_slots = league.roster_slots or DEFAULT_ROSTER_SLOTS
    roster_by_slot, bench = assign_roster(roster_slots, roster)
    keeper_rounds = engine.effective_keeper_rounds(db, league)
    keepers = [
        {
            "keeper_id": k.id,
            "player_id": k.player_id,
            "player_name": k.player.name,
            "position": k.player.position,
            "nfl_team": k.player.nfl_team,
            "round": keeper_rounds.get(k.id, k.round),
        }
        for k in db.scalars(
            select(Keeper)
            .where(
                Keeper.league_id == league.id, Keeper.team_id == team.id
            )
            .options(selectinload(Keeper.player))
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

    team_name_by_id = {t["id"]: t["name"] for t in state["teams"]}
    roster_counts: dict[int, dict[str, int]] = {}
    for slot in state["board"]:
        if slot.get("status") in ("FILLED", "KEEPER") and slot.get("player_name"):
            team_id = slot["drafting_team_id"]
            counts = roster_counts.setdefault(team_id, {})
            pos = slot.get("position") or "?"
            counts[pos] = counts.get(pos, 0) + 1

    next_picks = []
    if league.status == "LIVE":
        start = current["pick_number"] if current else 1
        for slot in state["board"]:
            if slot["status"] == "OPEN" and slot["pick_number"] >= start:
                next_picks.append(
                    {
                        "pick_number": slot["pick_number"],
                        "round": slot["round"],
                        "drafting_team_id": slot["drafting_team_id"],
                        "drafting_team_name": team_name_by_id.get(
                            slot["drafting_team_id"], "?"
                        ),
                        "roster": dict(
                            sorted(
                                roster_counts.get(slot["drafting_team_id"], {}).items()
                            )
                        ),
                    }
                )
                if len(next_picks) == 3:
                    break

    players = [
        {
            "player_id": p.id,
            "player_id_external": p.player_id,
            "name": p.name,
            "position": p.position,
            "nfl_team": p.nfl_team,
            "rank": rank,
            "bye_week": (p.extra or {}).get("bye_week"),
        }
        for p, rank in avail
    ]

    keeper_candidates: list[dict] = []
    if league.status in ("SETUP", "READY"):
        selected = {
            k.player_id
            for k in db.scalars(
                select(Keeper).where(
                    Keeper.league_id == league.id, Keeper.team_id == team.id
                )
            )
        }
        keeper_candidates = [
            candidate_dict(c, c.player_id in selected)
            for c in db.scalars(
                select(KeeperCandidate)
                .where(
                    KeeperCandidate.league_id == league.id,
                    KeeperCandidate.team_id == team.id,
                )
                .order_by(KeeperCandidate.cost_round, KeeperCandidate.player_name)
            )
        ]

    return {
        "league_id": league.id,
        "league_name": league.name,
        "season": league.season,
        "status": league.status,
        "team_id": team.id,
        "team_name": team.name,
        "draft_position": team.draft_position,
        "on_the_clock": on_the_clock,
        "current_slot": current,
        "my_next_slot": my_next,
        "roster": roster,
        "roster_slots": roster_slots,
        "roster_by_slot": roster_by_slot,
        "bench": bench,
        "keepers": keepers,
        "keeper_candidates": keeper_candidates,
        "keeper_count": len(keepers),
        "max_keepers": MAX_KEEPERS_PER_TEAM,
        "recent_picks": state["recent_picks"],
        "upcoming_picks": upcoming,
        "next_picks": next_picks,
        "players": players,
        "available_count": state["available_count"],
    }


def build_rosters(db: Session, league: League) -> dict:
    """Per-team roster layout for every team in the league."""
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
    picks_by_team: dict[int, list[Pick]] = {}
    for p in picks:
        picks_by_team.setdefault(p.team_id, []).append(p)

    roster_slots = league.roster_slots or DEFAULT_ROSTER_SLOTS
    teams_out = []
    if league.status in ("SETUP", "READY"):
        # Draft hasn't started: show confirmed keepers as each team's roster.
        keeper_rounds = engine.effective_keeper_rounds(db, league)
        keepers = list(
            db.scalars(select(Keeper).where(Keeper.league_id == league.id))
        )
        keepers_by_team: dict[int, list[tuple[Keeper, int]]] = {}
        for k in keepers:
            keepers_by_team.setdefault(k.team_id, []).append(
                (k, keeper_rounds.get(k.id, k.round))
            )
        for team in teams:
            team_keepers = sorted(
                keepers_by_team.get(team.id, []), key=lambda kr: kr[1]
            )
            roster = [_keeper_player_dict(k, r) for k, r in team_keepers]
            roster_by_slot, bench = assign_roster(roster_slots, roster)
            teams_out.append(
                {
                    "team_id": team.id,
                    "team_name": team.name,
                    "draft_position": team.draft_position,
                    "roster": roster_by_slot,
                    "bench": bench,
                }
            )
    else:
        for team in teams:
            roster = [_roster_player_dict(p) for p in picks_by_team.get(team.id, [])]
            roster_by_slot, bench = assign_roster(roster_slots, roster)
            teams_out.append(
                {
                    "team_id": team.id,
                    "team_name": team.name,
                    "draft_position": team.draft_position,
                    "roster": roster_by_slot,
                    "bench": bench,
                }
            )

    return {
        "league_id": league.id,
        "league_name": league.name,
        "season": league.season,
        "status": league.status,
        "num_teams": league.num_teams,
        "num_rounds": league.num_rounds,
        "roster_slots": roster_slots,
        "teams": teams_out,
    }