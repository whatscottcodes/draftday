from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    DraftEvent,
    DraftSlot,
    Keeper,
    League,
    LeagueStatus,
    Pick,
    Player,
    Ranking,
)


def validate_draft_configuration(
    db: Session, league: League
) -> tuple[list[dict], list[dict]]:
    """Return (errors, warnings) for a league's draft configuration."""
    errors: list[dict] = []
    warnings: list[dict] = []

    teams = list(league.teams)
    slots: list[DraftSlot] = list(
        db.scalars(
            select(DraftSlot)
            .where(DraftSlot.league_id == league.id)
            .order_by(DraftSlot.pick_number)
        )
    )
    keepers = list(league.keepers)
    players: dict[int, Player] = {p.id: p for p in league.players}
    team_ids = {t.id for t in teams}

    # All teams configured.
    if len(teams) != league.num_teams:
        errors.append(
            {
                "severity": "error",
                "code": "team_count",
                "message": (
                    f"Expected {league.num_teams} teams but found {len(teams)}. "
                    "All teams must be configured before the draft can start."
                ),
            }
        )

    # Expected number of draft slots.
    expected_slots = league.num_teams * league.num_rounds
    if len(slots) != expected_slots:
        errors.append(
            {
                "severity": "error",
                "code": "slot_count",
                "message": (
                    f"Expected {expected_slots} draft slots but found {len(slots)}."
                ),
            }
        )

    # Every draft slot has exactly one drafting team.
    for slot in slots:
        if slot.drafting_team_id is None or slot.drafting_team_id not in team_ids:
            errors.append(
                {
                    "severity": "error",
                    "code": "slot_owner",
                    "message": (
                        f"Slot {slot.pick_number} (round {slot.round}) has no "
                        "valid drafting team."
                    ),
                }
            )

    # Keeper player uniqueness.
    seen_players: dict[int, Keeper] = {}
    for keeper in keepers:
        if keeper.player_id in seen_players:
            a, b = seen_players[keeper.player_id], keeper
            errors.append(
                {
                    "severity": "error",
                    "code": "keeper_duplicate_player",
                    "message": (
                        f"{a.team.name} and {b.team.name} both keep "
                        f"{a.player.name}. Each keeper player must be unique."
                    ),
                }
            )
        else:
            seen_players[keeper.player_id] = keeper

    # Keeper rounds valid and keeper team owns a slot in that round.
    slots_by_round_team: dict[tuple[int, int], DraftSlot] = {
        (s.round, s.drafting_team_id): s for s in slots
    }
    for keeper in keepers:
        if not (1 <= keeper.round <= league.num_rounds):
            errors.append(
                {
                    "severity": "error",
                    "code": "keeper_round",
                    "message": (
                        f"{keeper.team.name} keeper {keeper.player.name} has "
                        f"invalid round {keeper.round}."
                    ),
                }
            )
            continue
        if keeper.player_id not in players:
            errors.append(
                {
                    "severity": "error",
                    "code": "keeper_player",
                    "message": f"Keeper references an unknown player (id {keeper.player_id}).",
                }
            )
        if (keeper.round, keeper.team_id) not in slots_by_round_team:
            errors.append(
                {
                    "severity": "error",
                    "code": "keeper_no_slot",
                    "message": (
                        f"{keeper.team.name} keeps {keeper.player.name} in round "
                        f"{keeper.round} but owns no draft slot in that round "
                        "(pick was traded away or does not exist)."
                    ),
                }
            )

    # Draft slot distribution warnings.
    owning = Counter(s.drafting_team_id for s in slots)
    for team in teams:
        count = owning.get(team.id, 0)
        delta = count - league.num_rounds
        if abs(delta) >= 2:
            warnings.append(
                {
                    "severity": "warning",
                    "code": "slot_distribution",
                    "message": (
                        f"{team.name} owns {count} draft slots, "
                        f"{delta:+d} vs the expected {league.num_rounds}. "
                        "Verify traded picks are intended."
                    ),
                }
            )

    # Rankings sanity: every ranked player must exist in the player pool.
    ranked_ids = set(
        db.scalars(select(Ranking.player_id).where(Ranking.league_id == league.id))
    )
    for pid in ranked_ids:
        if pid not in players:
            errors.append(
                {
                    "severity": "error",
                    "code": "ranking_player",
                    "message": f"Ranking references an unknown player (id {pid}).",
                }
            )

    return errors, warnings


def league_is_valid(errors: list[dict]) -> bool:
    return not errors


def start_draft(db: Session, league: League) -> None:
    if league.status == LeagueStatus.LIVE:
        return
    if league.status == LeagueStatus.COMPLETED:
        raise ValueError("Draft already completed; reopen it instead of starting again.")
    errors, _ = validate_draft_configuration(db, league)
    if not league_is_valid(errors):
        msgs = "; ".join(e["message"] for e in errors)
        raise ValueError(f"Draft configuration is invalid: {msgs}")

    slots_by_round_team: dict[tuple[int, int], DraftSlot] = {
        (s.round, s.drafting_team_id): s
        for s in db.scalars(
            select(DraftSlot).where(DraftSlot.league_id == league.id)
        )
    }
    keepers = list(
        db.scalars(select(Keeper).where(Keeper.league_id == league.id))
    )
    for keeper in keepers:
        slot = slots_by_round_team[(keeper.round, keeper.team_id)]
        existing = db.scalar(
            select(Pick).where(
                Pick.draft_slot_id == slot.id,
            )
        )
        if existing is not None:
            raise ValueError(f"Slot {slot.pick_number} is already occupied by a pick.")
        db.add(
            Pick(
                league_id=league.id,
                draft_slot_id=slot.id,
                team_id=keeper.team_id,
                player_id=keeper.player_id,
                pick_type="keeper",
            )
        )
    league.status = LeagueStatus.LIVE
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="draft_started",
            payload={"keeper_count": len(league.keepers)},
        )
    )
    db.flush()


def reopen_draft(db: Session, league: League) -> None:
    if league.status != LeagueStatus.COMPLETED:
        raise ValueError("Only a completed draft can be reopened.")
    league.status = LeagueStatus.LIVE
    db.add(
        DraftEvent(
            league_id=league.id,
            event_type="draft_reopened",
            payload={},
        )
    )
    db.flush()