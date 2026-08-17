import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    session = testing_session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def league_factory(db):
    def _make(num_teams=4, num_rounds=3, with_players=0, with_rankings=False):
        from app.draft.engine import create_draft_slots
        from app.models import League, Player, Ranking, Team

        league = League(
            name="Test League",
            season="2026",
            num_teams=num_teams,
            num_rounds=num_rounds,
            status="SETUP",
            access_token="tok-league",
        )
        db.add(league)
        db.flush()
        teams = []
        for i in range(1, num_teams + 1):
            team = Team(
                league_id=league.id,
                name=f"Team {i}",
                draft_position=i,
                access_token=f"tok-team-{i}",
            )
            db.add(team)
            teams.append(team)
        db.flush()
        create_draft_slots(db, league)
        players = []
        for j in range(1, with_players + 1):
            p = Player(
                league_id=league.id,
                player_id=f"p{j}",
                name=f"Player {j}",
                position=("QB" if j % 2 else "RB"),
                nfl_team="NFL",
            )
            db.add(p)
            players.append(p)
            if with_rankings:
                db.add(
                    Ranking(league_id=league.id, player_id=p.id, rank=j, adp=j * 1.0)
                )
        db.flush()
        return league, teams, players

    return _make