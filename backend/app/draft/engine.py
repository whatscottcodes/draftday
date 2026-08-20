from __future__ import annotations

from collections import Counter

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    DraftEvent,
    DraftSlot,
    Keeper,
    KeeperCandidate,
    League,
    LeagueStatus,
    Pick,
    PickType,
    Player,
    Ranking,
    Team,
    YahooConfig,
)


class DraftError(Exception):
    pass


def generate_draft_slots(num_teams: int, num_rounds: int) -> list[dict]:
    """Generate the standard snake-order draft slot sequence.

    For round r (1-indexed): odd rounds run draft positions 1..N,
    even rounds run N..1.
    """
    slots: list[dict] = []
    pick_number = 1
    for round_num in range(1, num_rounds + 1):
        positions = range(1, num_teams + 1) if round_num % 2 == 1 else range(
            num_teams, 0, -1
        )
        for position in positions:
            slots.append(
                {
                    "round": round_num,
                    "pick_number": pick_number,
                    "draft_position": position,
                }
            )
            pick_number += 1
    return slots


def create_draft_slots(db: Session, league: League) -> list[DraftSlot]:
    teams = {t.draft_position: t for t in league.teams}
    slots: list[DraftSlot] = []
    for spec in generate_draft_slots(league.num_teams, league.num_rounds):
        team = teams[spec["draft_position"]]
        slot = DraftSlot(
            league_id=league.id,
            round=spec["round"],
            pick_number=spec["pick_number"],
            original_team_id=team.id,
            drafting_team_id=team.id,
        )
        db.add(slot)
        slots.append(slot)
    db.flush()
    return slots


def set_draft_order(
    db: Session, league: League, order: list[tuple[int, int]]
) -> None:
    """Reassign every team's draft position and rebuild the slot grid.

    ``order`` is a list of (position, team_id) pairs covering positions
    1..num_teams and every team exactly once. All existing slots are
    discarded and regenerated from the new order, so any traded-pick
    assignments are reset and must be re-entered.
    """
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise DraftError("Draft order can only be changed before the draft starts")
    teams = {t.id: t for t in league.teams}
    if len(order) != league.num_teams:
        raise DraftError(
            f"Draft order must assign all {league.num_teams} positions"
        )
    positions = sorted(p for p, _ in order)
    if positions != list(range(1, league.num_teams + 1)):
        raise DraftError("Draft order must cover every position exactly once")
    if sorted(t for _, t in order) != sorted(teams.keys()):
        raise DraftError("Draft order must include every team exactly once")
    # Two-phase update so the (league_id, draft_position) unique constraint
    # never sees an intermediate collision while positions are swapped.
    n = league.num_teams
    for i, (_, team_id) in enumerate(order):
        teams[team_id].draft_position = n + 1 + i
    db.flush()
    for position, team_id in order:
        teams[team_id].draft_position = position
    db.flush()
    db.execute(delete(DraftSlot).where(DraftSlot.league_id == league.id))
    create_draft_slots(db, league)
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="draft_order_reset",
            payload={"order": order},
        )
    )


def slot_status(db: Session, slot: DraftSlot) -> str:
    pick = db.scalar(select(Pick).where(Pick.draft_slot_id == slot.id))
    if pick is not None:
        return "FILLED"
    league = db.get(League, slot.league_id)
    if league is not None:
        keeper_slots = keeper_slot_assignments(db, league)
        if slot.id in {s.id for s in keeper_slots.values()}:
            return "KEEPER"
    return "OPEN"


def bulk_slot_statuses(db: Session, slots: list[DraftSlot]) -> dict[int, str]:
    """Status for many slots using a bounded number of queries.

    Equivalent to calling slot_status() per slot, but avoids the N+1 query
    pattern that dominates board/admin rendering on remote databases.
    """
    if not slots:
        return {}
    slot_ids = [s.id for s in slots]
    picked = {
        p.draft_slot_id
        for p in db.scalars(select(Pick).where(Pick.draft_slot_id.in_(slot_ids)))
    }
    keeper_slot_ids: set[int] = set()
    league = db.get(League, slots[0].league_id)
    if league is not None:
        keeper_slot_ids = {
            s.id for s in keeper_slot_assignments(db, league).values()
        }
    statuses: dict[int, str] = {}
    for s in slots:
        if s.id in picked:
            statuses[s.id] = "FILLED"
        elif s.id in keeper_slot_ids:
            statuses[s.id] = "KEEPER"
        else:
            statuses[s.id] = "OPEN"
    return statuses


def get_league_by_token(db: Session, token: str) -> League | None:
    return db.scalar(select(League).where(League.access_token == token))


def get_team_by_token(db: Session, token: str) -> Team | None:
    return db.scalar(select(Team).where(Team.access_token == token))


def update_draft_slot_owner(
    db: Session, league: League, slot_id: int, drafting_team_id: int
) -> DraftSlot:
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise DraftError("Draft slots can only be edited before the draft starts")
    slot = db.get(DraftSlot, slot_id)
    if slot is None or slot.league_id != league.id:
        raise DraftError("Unknown draft slot")
    team = db.get(Team, drafting_team_id)
    if team is None or team.league_id != league.id:
        raise DraftError("Unknown drafting team")
    old = slot.drafting_team_id
    slot.drafting_team_id = drafting_team_id
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="slot_owner_changed",
            payload={"slot_id": slot_id, "from_team": old, "to_team": drafting_team_id},
        )
    )
    db.flush()
    return slot


MAX_KEEPERS_PER_TEAM = 3


def add_keeper(
    db: Session, league: League, team_id: int, player_id: int, round_: int
) -> Keeper:
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise DraftError("Keepers can only be configured before the draft starts")
    team = db.get(Team, team_id)
    if team is None or team.league_id != league.id:
        raise DraftError("Unknown team")
    player = db.get(Player, player_id)
    if player is None or player.league_id != league.id:
        raise DraftError("Unknown player")
    if not (1 <= round_ <= league.num_rounds):
        raise DraftError(f"Keeper round must be between 1 and {league.num_rounds}")
    existing = db.scalar(
        select(Keeper).where(
            Keeper.league_id == league.id, Keeper.player_id == player_id
        )
    )
    if existing is not None:
        raise DraftError("That player is already kept")
    taken = db.scalar(
        select(Pick).where(Pick.league_id == league.id, Pick.player_id == player_id)
    )
    if taken is not None:
        raise DraftError("That player is already drafted")
    count = db.scalar(
        select(func.count())
        .select_from(Keeper)
        .where(Keeper.league_id == league.id, Keeper.team_id == team_id)
    )
    if count >= MAX_KEEPERS_PER_TEAM:
        raise DraftError(
            f"Teams can keep at most {MAX_KEEPERS_PER_TEAM} players"
        )
    keeper = Keeper(
        league_id=league.id, team_id=team_id, player_id=player_id, round=round_
    )
    db.add(keeper)
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="keeper_added",
            payload={
                "team_id": team_id,
                "player_id": player_id,
                "round": round_,
            },
        )
    )
    db.flush()
    return keeper


def remove_keeper(db: Session, league: League, keeper_id: int) -> None:
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise DraftError("Keepers can only be configured before the draft starts")
    keeper = db.get(Keeper, keeper_id)
    if keeper is None or keeper.league_id != league.id:
        raise DraftError("Unknown keeper")
    db.delete(keeper)
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="keeper_removed",
            payload={"keeper_id": keeper_id},
        )
    )
    db.flush()


def effective_keeper_rounds(db: Session, league: League) -> dict[int, int]:
    """Distinct keeper cost rounds per team, computed from nominal rounds and
    the draft picks the team actually owns.

    A keeper keeps its nominal round as long as the team owns enough picks in
    that round (e.g. two round-5 keepers stay at round 5 when the team owns two
    round-5 picks). Only when more keepers collide than the team has picks in a
    round do the overflow keepers spread to earlier rounds the team owns picks
    in (e.g. three round-11 keepers with one round-11 pick become 9, 10, 11).
    Within a collision the better-ranked player keeps the original (cheaper)
    round, tiebroken by name. Returns a map of keeper_id -> effective round.
    Deterministic and independent of the order the keepers were selected.
    """
    keepers = list(
        db.scalars(select(Keeper).where(Keeper.league_id == league.id))
    )
    if not keepers:
        return {}
    ranks: dict[int, int] = {}
    for rid, pid in db.execute(
        select(Ranking.rank, Ranking.player_id).where(
            Ranking.league_id == league.id,
            Ranking.player_id.in_([k.player_id for k in keepers]),
        )
    ):
        ranks[pid] = rid
    capacity: Counter = Counter()
    for s in db.scalars(
        select(DraftSlot).where(DraftSlot.league_id == league.id)
    ):
        capacity[(s.drafting_team_id, s.round)] += 1
    by_team: dict[int, list[Keeper]] = {}
    for k in keepers:
        by_team.setdefault(k.team_id, []).append(k)
    result: dict[int, int] = {}
    for team_id, team_keepers in by_team.items():
        ordered = sorted(
            team_keepers,
            key=lambda k: (
                -k.round,
                ranks.get(k.player_id, 10**9),
                (k.player.name or "").casefold(),
            ),
        )
        used: Counter = Counter()
        for k in ordered:
            nominal = k.round
            if not (1 <= nominal <= league.num_rounds):
                result[k.id] = nominal
                continue
            if used[nominal] < capacity.get((team_id, nominal), 0):
                result[k.id] = nominal
                used[nominal] += 1
                continue
            placed = False
            for r2 in range(nominal - 1, 0, -1):
                if used[r2] < capacity.get((team_id, r2), 0):
                    result[k.id] = r2
                    used[r2] += 1
                    placed = True
                    break
            if not placed:
                result[k.id] = nominal
                used[nominal] += 1
    return result


def keeper_slot_assignments(
    db: Session, league: League
) -> dict[int, DraftSlot]:
    """Map each keeper to the specific draft slot it consumes.

    A keeper uses one of its team's picks in the keeper's effective round,
    taking the latest (highest pick number) available slot first. Only these
    slots are shown as KEEPER on the board, so a team with two round-5 picks
    and one round-5 keeper has exactly one slot marked.
    """
    keepers = list(
        db.scalars(select(Keeper).where(Keeper.league_id == league.id))
    )
    if not keepers:
        return {}
    keeper_eff = effective_keeper_rounds(db, league)
    slots = list(
        db.scalars(
            select(DraftSlot)
            .where(DraftSlot.league_id == league.id)
            .order_by(DraftSlot.pick_number.desc())
        )
    )
    slots_by_key: dict[tuple[int, int], list[DraftSlot]] = {}
    for s in slots:
        slots_by_key.setdefault((s.round, s.drafting_team_id), []).append(s)
    result: dict[int, DraftSlot] = {}
    used: Counter = Counter()
    for k in sorted(
        keepers,
        key=lambda k: (
            keeper_eff.get(k.id, k.round),
            (k.player.name or "").casefold(),
        ),
    ):
        kround = keeper_eff.get(k.id, k.round)
        pool = slots_by_key.get((kround, k.team_id), [])
        idx = used[(kround, k.team_id)]
        if idx < len(pool):
            result[k.id] = pool[idx]
            used[(kround, k.team_id)] += 1
    return result


def team_add_keeper(
    db: Session, league: League, team: Team, player_id: int
) -> Keeper:
    """Allow a team to select one of its own keeper candidates."""
    if league.status not in (LeagueStatus.SETUP, LeagueStatus.READY):
        raise DraftError("Keepers can only be selected before the draft starts")
    candidate = db.scalar(
        select(KeeperCandidate).where(
            KeeperCandidate.league_id == league.id,
            KeeperCandidate.team_id == team.id,
            KeeperCandidate.player_id == player_id,
        )
    )
    if candidate is None:
        raise DraftError("That player is not an available keeper for your team")
    return add_keeper(db, league, team.id, player_id, candidate.cost_round)


def current_slot(db: Session, league: League) -> DraftSlot | None:
    if league.status != LeagueStatus.LIVE:
        return None
    slots = db.scalars(
        select(DraftSlot)
        .where(DraftSlot.league_id == league.id)
        .order_by(DraftSlot.pick_number)
    )
    for slot in slots:
        if slot_status(db, slot) == "OPEN":
            return slot
    return None


def available_players(
    db: Session, league: League, limit: int | None = None
) -> list[tuple[Player, int | None]]:
    picked_ids = {
        p.player_id for p in db.scalars(select(Pick).where(Pick.league_id == league.id))
    }
    kept_ids = {
        k.player_id
        for k in db.scalars(select(Keeper).where(Keeper.league_id == league.id))
    }
    taken = picked_ids | kept_ids
    ranked: dict[int, int] = {}
    for r in db.scalars(select(Ranking).where(Ranking.league_id == league.id)):
        ranked[r.player_id] = r.rank
    results: list[tuple[Player, int | None]] = []
    for p in db.scalars(select(Player).where(Player.league_id == league.id)):
        if p.id in taken:
            continue
        results.append((p, ranked.get(p.id)))
    results.sort(key=lambda item: (item[1] is None, item[1] or 1 << 30, item[0].name))
    if limit is not None:
        results = results[:limit]
    return results


def _ensure_live(db: Session, league: League) -> None:
    if league.status != LeagueStatus.LIVE:
        raise DraftError(f"Draft is not live (status={league.status})")


def _validate_pick_target(
    db: Session, league: League, slot: DraftSlot, team_id: int, player_id: int
) -> Player:
    if slot.league_id != league.id:
        raise DraftError("Unknown draft slot")
    if slot_status(db, slot) != "OPEN":
        raise DraftError("That draft slot is already filled")
    team = db.get(Team, team_id)
    if team is None or team.league_id != league.id:
        raise DraftError("Unknown team")
    player = db.get(Player, player_id)
    if player is None or player.league_id != league.id:
        raise DraftError("Unknown player")
    taken_pick = db.scalar(
        select(Pick).where(Pick.league_id == league.id, Pick.player_id == player_id)
    )
    if taken_pick is not None:
        raise DraftError(f"{player.name} has already been drafted")
    kept = db.scalar(
        select(Keeper).where(Keeper.league_id == league.id, Keeper.player_id == player_id)
    )
    if kept is not None:
        raise DraftError(f"{player.name} is already kept")
    return player


def make_pick(
    db: Session,
    league: League,
    slot_id: int,
    team_id: int,
    player_id: int,
    pick_type: str = PickType.LIVE,
    override: bool = False,
) -> Pick:
    _ensure_live(db, league)
    slot = db.get(DraftSlot, slot_id)
    if slot is None:
        raise DraftError("Unknown draft slot")
    player = _validate_pick_target(db, league, slot, team_id, player_id)

    current = current_slot(db, league)
    if not override:
        if current is None or slot.id != current.id:
            raise DraftError("That is not the current draft slot")
        if team_id != slot.drafting_team_id:
            raise DraftError(
                "You can only pick for the team on the clock"
            )

    pick = Pick(
        league_id=league.id,
        draft_slot_id=slot.id,
        team_id=team_id,
        player_id=player.id,
        pick_type=pick_type,
    )
    db.add(pick)
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="pick_made",
            payload={
                "slot_id": slot.id,
                "team_id": team_id,
                "player_id": player.id,
                "pick_type": pick_type,
            },
        )
    )
    db.flush()

    next_slot = current_slot(db, league)
    if next_slot is None:
        league.status = LeagueStatus.COMPLETED
        db.add(
            DraftEvent(
                league_id=league.id,
                event_type="draft_completed",
                payload={},
            )
        )
    return pick


def undo_last_pick(db: Session, league: League) -> Pick:
    if league.status not in (LeagueStatus.LIVE, LeagueStatus.COMPLETED):
        raise DraftError(f"Draft is not live (status={league.status})")
    pick = db.scalar(
        select(Pick)
        .where(
            Pick.league_id == league.id,
            Pick.pick_type != PickType.KEEPER,
        )
        .order_by(Pick.id.desc())
    )
    if pick is None:
        raise DraftError("Nothing to undo")
    player = pick.player
    slot = pick.slot
    db.delete(pick)
    if league.status == LeagueStatus.COMPLETED:
        league.status = LeagueStatus.LIVE
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="pick_undone",
            payload={
                "slot_id": slot.id,
                "team_id": pick.team_id,
                "player_id": pick.player_id,
                "player_name": player.name,
            },
        )
    )
    db.flush()
    return pick


def team_roster(db: Session, league: League, team_id: int) -> list[Pick]:
    return list(
        db.scalars(
            select(Pick)
            .where(Pick.league_id == league.id, Pick.team_id == team_id)
            .order_by(Pick.timestamp)
        )
    )


def draft_history(db: Session, league: League) -> list[Pick]:
    return list(
        db.scalars(
            select(Pick)
            .where(Pick.league_id == league.id)
            .join(DraftSlot)
            .order_by(DraftSlot.pick_number)
        )
    )


def export_results(db: Session, league: League) -> dict:
    picks = draft_history(db, league)
    teams = sorted(
        db.scalars(select(Team).where(Team.league_id == league.id)),
        key=lambda t: t.draft_position,
    )
    return {
        "league": league.name,
        "season": league.season,
        "num_teams": league.num_teams,
        "num_rounds": league.num_rounds,
        "status": league.status,
        "teams": [
            {
                "team_id": t.id,
                "name": t.name,
                "manager_name": t.manager_name,
                "draft_position": t.draft_position,
                "roster": [
                    {
                        "pick_number": p.slot.pick_number,
                        "round": p.slot.round,
                        "player_name": p.player.name,
                        "position": p.player.position,
                        "nfl_team": p.player.nfl_team,
                        "pick_type": p.pick_type,
                    }
                    for p in picks
                    if p.team_id == t.id
                ],
            }
            for t in teams
        ],
        "picks": [
            {
                "pick_number": p.slot.pick_number,
                "round": p.slot.round,
                "team": p.team.name,
                "player": p.player.name,
                "position": p.player.position,
                "pick_type": p.pick_type,
            }
            for p in picks
        ],
    }


def delete_league(db: Session, league: League) -> None:
    """Delete a league and everything under it, children first."""
    league_id = league.id
    db.execute(delete(DraftEvent).where(DraftEvent.league_id == league_id))
    db.execute(delete(Pick).where(Pick.league_id == league_id))
    db.execute(delete(Keeper).where(Keeper.league_id == league_id))
    db.execute(delete(KeeperCandidate).where(KeeperCandidate.league_id == league_id))
    db.execute(delete(Ranking).where(Ranking.league_id == league_id))
    db.execute(delete(DraftSlot).where(DraftSlot.league_id == league_id))
    db.execute(delete(YahooConfig).where(YahooConfig.league_id == league_id))
    db.execute(delete(Player).where(Player.league_id == league_id))
    db.execute(delete(Team).where(Team.league_id == league_id))
    db.delete(league)