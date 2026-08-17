import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    session = testing_session()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, session
    app.dependency_overrides.clear()
    session.close()


def _create_league(client):
    payload = {
        "name": "Test League",
        "season": "2026",
        "num_teams": 4,
        "num_rounds": 2,
        "teams": [{"name": f"Team {i}", "manager_name": f"Mgr {i}"} for i in range(1, 5)],
    }
    resp = client.post("/api/leagues", json=payload)
    assert resp.status_code == 200
    return resp.json()


def test_create_league_generates_slots(client):
    c, _ = client
    data = _create_league(c)
    assert data["status"] == "SETUP"
    assert len(data["teams"]) == 4
    assert data["access_token"]

    token = data["access_token"]
    config = c.get(f"/api/draft/{token}/admin/config").json()
    assert len(config["slots"]) == 8


def test_import_players_and_run_draft_end_to_end(client):
    c, session = client
    data = _create_league(c)
    token = data["access_token"]
    team_tokens = {t["draft_position"]: t["access_token"] for t in data["teams"]}

    # Import players with rankings via CSV.
    csv_data = (
        "player_id,name,position,nfl_team,rank,adp\n"
        + "\n".join(
            f"p{i},Player {i},{'QB' if i % 2 else 'RB'},NFL,{i},{i}.0"
            for i in range(1, 13)
        )
    )
    resp = c.post(
        f"/api/draft/{token}/admin/import/csv",
        files={"file": ("players.csv", csv_data, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 12

    # Add a keeper.
    players = c.get(f"/api/draft/{token}/admin/config").json()["players"]
    p1 = next(p for p in players if p["name"] == "Player 1")
    keeper = c.post(
        f"/api/draft/{token}/admin/keepers",
        json={"team_id": data["teams"][0]["id"], "player_id": p1["id"], "round": 1},
    )
    assert keeper.status_code == 200

    # Validate and start.
    assert c.post(f"/api/draft/{token}/admin/validate").json()["valid"] is True
    assert c.post(f"/api/draft/{token}/admin/start").json()["status"] == "LIVE"

    # Display view reflects keeper on the board.
    display = c.get(f"/api/draft/{token}/display").json()
    assert display["status"] == "LIVE"
    keeper_slot = display["board"][0]
    assert keeper_slot["status"] == "FILLED"
    assert keeper_slot["player_name"] == "Player 1"

    # Team 2 is on the clock (team 1's round-1 slot is keeper-filled).
    team2 = team_tokens[2]
    team_state = c.get(f"/api/draft/{token}/team/{team2}").json()
    assert team_state["on_the_clock"] is True

    # Team 2 makes a pick.
    p2 = next(p for p in players if p["name"] == "Player 2")
    pick = c.post(
        f"/api/draft/{token}/team/{team2}/picks", json={"player_id": p2["id"]}
    )
    assert pick.status_code == 200

    # Drafted player now unavailable; commissioner undo restores it.
    display = c.get(f"/api/draft/{token}/display").json()
    assert display["recent_picks"][0]["player_name"] == "Player 2"
    undone = c.post(f"/api/draft/{token}/admin/undo")
    assert undone.status_code == 200
    display = c.get(f"/api/draft/{token}/display").json()
    assert display["board"][1]["status"] == "OPEN"


def test_bad_league_token_404(client):
    c, _ = client
    assert c.get("/api/draft/nope/display").status_code == 404


def test_wrong_team_pick_rejected(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    for i in range(1, 5):
        resp = c.post(
            f"/api/draft/{token}/admin/import/csv",
            files={
                "file": (
                    "players.csv",
                    "player_id,name,position,nfl_team,rank\n"
                    + "\n".join(f"p{i},P{i},QB,NFL,{i}" for i in range(1, 9)),
                    "text/csv",
                )
            },
        )
        assert resp.status_code == 200
    c.post(f"/api/draft/{token}/admin/start")
    team2 = data["teams"][1]["access_token"]
    players = c.get(f"/api/draft/{token}/admin/config").json()["players"]
    p = players[0]
    # Team 2 is NOT on the clock in round 1 (team 1 is), so this fails.
    resp = c.post(f"/api/draft/{token}/team/{team2}/picks", json={"player_id": p["id"]})
    assert resp.status_code == 400
    assert "on the clock" in resp.json()["detail"]