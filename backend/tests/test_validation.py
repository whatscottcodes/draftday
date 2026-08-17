import pytest

from app.draft import engine
from app.draft.validation import (
    league_is_valid,
    start_draft,
    validate_draft_configuration,
)
from app.models import DraftSlot, Keeper, League


def _codes(errors):
    return {e["code"] for e in errors}


def test_valid_config(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    errors, warnings = validate_draft_configuration(db, league)
    assert league_is_valid(errors)
    assert errors == []


def test_team_count_mismatch(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    league.num_teams = 5
    errors, _ = validate_draft_configuration(db, league)
    assert "team_count" in _codes(errors)


def test_missing_slots(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    slot = db.query(DraftSlot).filter_by(league_id=league.id).first()
    db.delete(slot)
    db.flush()
    errors, _ = validate_draft_configuration(db, league)
    assert "slot_count" in _codes(errors)


def test_traded_pick_distribution_warning(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    # Move all of team 1's slots to team 2.
    for slot in db.query(DraftSlot).filter_by(league_id=league.id):
        if slot.drafting_team_id == teams[0].id:
            slot.drafting_team_id = teams[1].id
    db.flush()
    errors, warnings = validate_draft_configuration(db, league)
    codes = {w["code"] for w in warnings}
    assert "slot_distribution" in codes
    assert league_is_valid(errors)  # still valid, just warned


def test_duplicate_keeper_player(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    engine.add_keeper(db, league, teams[0].id, players[0].id, 1)
    engine.add_keeper(db, league, teams[1].id, players[1].id, 1)
    # Force a duplicate player directly (bypassing engine guard).
    db.add(
        Keeper(
            league_id=league.id,
            team_id=teams[2].id,
            player_id=players[0].id,
            round=2,
        )
    )
    db.flush()
    errors, _ = validate_draft_configuration(db, league)
    assert "keeper_duplicate_player" in _codes(errors)


def test_keeper_invalid_round(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    engine.add_keeper(db, league, teams[0].id, players[0].id, 1)
    db.add(
        Keeper(
            league_id=league.id,
            team_id=teams[1].id,
            player_id=players[1].id,
            round=99,
        )
    )
    db.flush()
    errors, _ = validate_draft_configuration(db, league)
    assert "keeper_round" in _codes(errors)


def test_keeper_without_owned_slot(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    # Team 1 trades away ALL its round 1 slots... team has 1 slot/round.
    round1_team1 = (
        db.query(DraftSlot)
        .filter_by(league_id=league.id, round=1, drafting_team_id=teams[0].id)
        .one()
    )
    round1_team1.drafting_team_id = teams[1].id
    db.flush()
    db.add(
        Keeper(
            league_id=league.id,
            team_id=teams[0].id,
            player_id=players[0].id,
            round=1,
        )
    )
    db.flush()
    errors, _ = validate_draft_configuration(db, league)
    assert "keeper_no_slot" in _codes(errors)


def test_start_prefills_keepers(db, league_factory):
    league, teams, players = league_factory(num_teams=4, num_rounds=3, with_players=20)
    engine.add_keeper(db, league, teams[0].id, players[0].id, 1)
    engine.add_keeper(db, league, teams[1].id, players[1].id, 2)
    start_draft(db, league)
    assert league.status == "LIVE"
    keeper_picks = db.query(League).filter_by(id=league.id).one().picks
    assert len(keeper_picks) == 2
    assert all(p.pick_type == "keeper" for p in keeper_picks)


def test_start_rejects_after_completed(db, league_factory):
    league, teams, players = league_factory(num_teams=2, num_rounds=1, with_players=8)
    start_draft(db, league)
    s = engine.current_slot(db, league)
    engine.make_pick(db, league, s.id, teams[0].id, players[0].id)
    s = engine.current_slot(db, league)
    engine.make_pick(db, league, s.id, teams[1].id, players[1].id)
    assert league.status == "COMPLETED"
    with pytest.raises(ValueError, match="reopen"):
        start_draft(db, league)