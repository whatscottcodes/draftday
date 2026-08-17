import pytest

from app.draft import engine
from app.draft.engine import (
    DraftError,
    add_keeper,
    current_slot,
    export_results,
    generate_draft_slots,
    make_pick,
    slot_status,
    team_roster,
    undo_last_pick,
    update_draft_slot_owner,
)
from app.draft.state import assign_roster
from app.draft.validation import start_draft
from app.models import DraftSlot, Pick, PickType


def test_assign_roster_flex_and_bench():
    slots = ["QB1", "QB2", "RB1", "RB2", "WR1", "WR2", "TE", "Flex", "DST", "K"]
    players = [
        {"player_id": 1, "player_name": "P1", "position": "QB"},
        {"player_id": 2, "player_name": "P2", "position": "RB"},
        {"player_id": 3, "player_name": "P3", "position": "WR"},
        {"player_id": 4, "player_name": "P4", "position": "RB"},
        {"player_id": 5, "player_name": "P5", "position": "WR"},
        {"player_id": 6, "player_name": "P6", "position": "TE"},
        {"player_id": 7, "player_name": "P7", "position": "RB"},
    ]
    roster, bench = assign_roster(slots, players)
    by_slot = {r["slot"]: (r["player"] or {}).get("player_name") for r in roster}
    assert by_slot["QB1"] == "P1"
    assert by_slot["QB2"] is None
    assert by_slot["RB1"] == "P2"
    assert by_slot["RB2"] == "P4"
    assert by_slot["WR1"] == "P3"
    assert by_slot["WR2"] == "P5"
    assert by_slot["Flex"] == "P7"
    assert by_slot["DST"] is None
    assert by_slot["K"] is None
    assert bench == []


def test_generate_draft_slots_snake_order():
    slots = generate_draft_slots(4, 4)
    assert len(slots) == 16
    rounds = [s["round"] for s in slots]
    assert rounds == [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4]
    # Round 1: A -> B -> C -> D ; Round 2: D -> C -> B -> A
    positions = [s["draft_position"] for s in slots[:4]]
    assert positions == [1, 2, 3, 4]
    assert [s["draft_position"] for s in slots[4:8]] == [4, 3, 2, 1]
    assert [s["draft_position"] for s in slots[8:12]] == [1, 2, 3, 4]
    assert [s["draft_position"] for s in slots[12:16]] == [4, 3, 2, 1]
    assert [s["pick_number"] for s in slots] == list(range(1, 17))


def test_pick_advances_and_completes_draft(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    start_draft(db, league)
    assert league.status == "LIVE"

    order = [
        (teams[0], players[0]),
        (teams[1], players[1]),
        (teams[1], players[2]),
        (teams[0], players[3]),
    ]
    for team, player in order:
        slot = current_slot(db, league)
        assert slot is not None
        assert slot.drafting_team_id == team.id
        make_pick(db, league, slot.id, team.id, player.id)

    assert league.status == "COMPLETED"
    assert current_slot(db, league) is None
    assert len(db.query(Pick).filter_by(league_id=league.id).all()) == 4


def test_player_cannot_be_picked_twice(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    start_draft(db, league)
    slot1 = current_slot(db, league)
    make_pick(db, league, slot1.id, teams[0].id, players[0].id)
    with pytest.raises(DraftError, match="already been drafted"):
        slot2 = current_slot(db, league)
        make_pick(db, league, slot2.id, teams[1].id, players[0].id)


def test_slot_cannot_be_picked_twice(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    start_draft(db, league)
    slot = current_slot(db, league)
    make_pick(db, league, slot.id, teams[0].id, players[0].id)
    with pytest.raises(DraftError, match="already filled"):
        make_pick(
            db, league, slot.id, teams[0].id, players[1].id, override=True
        )


def test_edited_slot_ownership_puts_team_on_clock(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    # Team A (team 1) trades its round 1 pick to Team B (team 2).
    round1_slot_a = (
        db.query(DraftSlot)
        .filter_by(league_id=league.id, round=1, original_team_id=teams[0].id)
        .one()
    )
    update_draft_slot_owner(db, league, round1_slot_a.id, teams[1].id)
    start_draft(db, league)
    first = current_slot(db, league)
    assert first.drafting_team_id == teams[1].id
    assert first.original_team_id == teams[0].id


def test_undo_restores_state(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    start_draft(db, league)
    slot = current_slot(db, league)
    make_pick(db, league, slot.id, teams[0].id, players[0].id)
    pick = undo_last_pick(db, league)
    assert pick.player_id == players[0].id
    assert slot_status(db, slot) == "OPEN"
    assert current_slot(db, league).id == slot.id
    # Player is available again.
    assert players[0].id in {p.id for p, _ in engine.available_players(db, league)}


def test_undo_after_completion_reopens(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=1, with_players=8)
    start_draft(db, league)
    slot = current_slot(db, league)
    make_pick(db, league, slot.id, teams[0].id, players[0].id)
    slot2 = current_slot(db, league)
    make_pick(db, league, slot2.id, teams[1].id, players[1].id)
    assert league.status == "COMPLETED"
    undo_last_pick(db, league)
    assert league.status == "LIVE"
    assert current_slot(db, league) is not None


def test_commissioner_override_skips_turn(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    start_draft(db, league)
    # Commissioner picks a later slot on behalf of team 3 via override.
    target = (
        db.query(DraftSlot)
        .filter_by(league_id=league.id, drafting_team_id=teams[2].id)
        .order_by(DraftSlot.pick_number)
        .first()
    )
    make_pick(
        db,
        league,
        target.id,
        teams[2].id,
        players[0].id,
        pick_type=PickType.COMMISSIONER,
        override=True,
    )
    assert slot_status(db, target) == "FILLED"
    pick = db.query(Pick).filter_by(draft_slot_id=target.id).one()
    assert pick.pick_type == PickType.COMMISSIONER


def test_non_current_slot_rejected_without_override(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    start_draft(db, league)
    later = (
        db.query(DraftSlot)
        .filter_by(league_id=league.id, drafting_team_id=teams[1].id)
        .order_by(DraftSlot.pick_number.desc())
        .first()
    )
    with pytest.raises(DraftError, match="not the current draft slot"):
        make_pick(db, league, later.id, teams[1].id, players[0].id)


def test_wrong_team_rejected(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    start_draft(db, league)
    slot = current_slot(db, league)
    with pytest.raises(DraftError, match="on the clock"):
        make_pick(db, league, slot.id, teams[1].id, players[0].id)


def test_team_roster(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    start_draft(db, league)
    s1 = current_slot(db, league)
    make_pick(db, league, s1.id, teams[0].id, players[0].id)
    s2 = current_slot(db, league)
    make_pick(db, league, s2.id, teams[1].id, players[1].id)
    roster = team_roster(db, league, teams[0].id)
    assert [p.player_id for p in roster] == [players[0].id]


def test_export_results(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    start_draft(db, league)
    for team, player in [(teams[0], players[0]), (teams[1], players[1])]:
        s = current_slot(db, league)
        make_pick(db, league, s.id, team.id, player.id)
    results = export_results(db, league)
    assert results["league"] == "Test League"
    assert len(results["teams"]) == 2
    assert len(results["picks"]) == 2


def test_concurrent_pick_attempts_only_one_succeeds(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    start_draft(db, league)
    slot = current_slot(db, league)
    make_pick(db, league, slot.id, teams[0].id, players[0].id)
    # Second identical attempt must fail: slot filled.
    with pytest.raises(DraftError, match="already filled"):
        make_pick(db, league, slot.id, teams[0].id, players[1].id, override=True)


def test_keeper_blocks_others_and_skips_slot(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    add_keeper(db, league, teams[0].id, players[0].id, 1)
    # Other team cannot keep the same player.
    with pytest.raises(DraftError, match="already kept"):
        add_keeper(db, league, teams[1].id, players[0].id, 2)
    start_draft(db, league)
    # Round 1, team A slot is now keeper-filled and skipped.
    slot_a_r1 = (
        db.query(DraftSlot)
        .filter_by(league_id=league.id, round=1, drafting_team_id=teams[0].id)
        .one()
    )
    assert slot_status(db, slot_a_r1) == "FILLED"
    assert db.query(Pick).filter_by(draft_slot_id=slot_a_r1.id).one().pick_type == "keeper"
    # First open slot is team B round 1, not team A.
    first = current_slot(db, league)
    assert first.drafting_team_id == teams[1].id
    # Keeper player cannot be drafted live.
    s2 = current_slot(db, league)
    with pytest.raises(DraftError, match="already been drafted|already kept"):
        make_pick(db, league, s2.id, teams[1].id, players[0].id)


def test_draft_cannot_start_invalid(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    # Delete a slot to corrupt the grid.
    slot = db.query(DraftSlot).filter_by(league_id=league.id).first()
    db.delete(slot)
    db.flush()
    with pytest.raises(ValueError, match="invalid"):
        start_draft(db, league)


def test_pick_before_start_rejected(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=2, with_players=8)
    slot = db.query(DraftSlot).filter_by(league_id=league.id).first()
    with pytest.raises(DraftError, match="not live"):
        make_pick(db, league, slot.id, teams[0].id, players[0].id)