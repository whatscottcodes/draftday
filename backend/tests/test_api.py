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

    # Next-picks row lists the upcoming open slots with team names.
    assert team_state["next_picks"]
    assert all("drafting_team_name" in s for s in team_state["next_picks"])
    assert len(team_state["next_picks"]) <= 3
    assert "roster" in team_state["next_picks"][0]

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


def test_websocket_connect_sends_initial_state(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    with c.websocket_connect(f"/api/draft/{token}/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["data"]["league_id"] == data["id"]


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


FANTASYPROS_CSV = (
    'RK,TIERS,"PLAYER NAME",TEAM,"POS","BYE WEEK","UPSIDE ","BUST ",'
    '"SOS SEASON","ECR VS. ADP"\n'
    '1,1,"Christian McCaffrey",SF,RB,9,25,13,"NEUTRAL",+1\n'
    '2,1,"Bijan Robinson",ATL,RB,12,22,10,"EASY",0\n'
    '3,1,"Tyreek Hill",MIA,WR,6,24,11,"HARD",-2\n'
)


def test_fantasypros_csv_import(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    resp = c.post(
        f"/api/draft/{token}/admin/import/csv",
        files={"file": ("fp.csv", FANTASYPROS_CSV, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 3
    players = c.get(f"/api/draft/{token}/admin/config").json()["players"]
    by_name = {p["name"]: p for p in players}
    cmc = by_name["Christian McCaffrey"]
    assert cmc["rank"] == 1
    assert cmc["position"] == "RB"
    assert cmc["nfl_team"] == "SF"
    assert cmc["bye_week"] == "9"
    assert cmc["tier"] == "1"
    hill = by_name["Tyreek Hill"]
    assert hill["rank"] == 3
    assert hill["position"] == "WR"
    assert hill["bye_week"] == "6"


def test_fantasypros_text_import(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    resp = c.post(
        f"/api/draft/{token}/admin/import/text",
        json={"csv": FANTASYPROS_CSV},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 3
    players = c.get(f"/api/draft/{token}/admin/config").json()["players"]
    assert len(players) == 3
    assert all(p["position"] in ("RB", "WR") for p in players)


def test_fantasypros_rankings_used_by_state(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    resp = c.post(
        f"/api/draft/{token}/admin/import/text",
        json={"csv": FANTASYPROS_CSV},
    )
    assert resp.status_code == 200
    c.post(f"/api/draft/{token}/admin/start")
    display = c.get(f"/api/draft/{token}/display").json()
    top = display["top_available"]
    assert top[0]["name"] == "Christian McCaffrey"
    assert top[0]["rank"] == 1
    assert top[0]["bye_week"] == "9"


def test_fantasypros_position_rank_stripped(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    csv_text = (
        'RK,TIERS,"PLAYER NAME",TEAM,"POS","BYE WEEK","UPSIDE ","BUST ",'
        '"SOS SEASON","ECR VS. ADP"\n'
        '1,1,"Christian McCaffrey",SF,RB1,9,25,13,"NEUTRAL",+1\n'
        '2,1,"Bijan Robinson",ATL,RB2,12,22,10,"EASY",0\n'
        '3,1,"Tyreek Hill",MIA,WR3,6,24,11,"HARD",-2\n'
        '4,1,"Trey McBride",ARI,TE1,10,20,9,"EASY",+1\n'
        '5,1,"Josh Allen",BUF,QB1,12,26,8,"HARD",0\n'
    )
    resp = c.post(
        f"/api/draft/{token}/admin/import/text",
        json={"csv": csv_text},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 5
    players = c.get(f"/api/draft/{token}/admin/config").json()["players"]
    positions = {p["name"]: p["position"] for p in players}
    assert positions["Christian McCaffrey"] == "RB"
    assert positions["Bijan Robinson"] == "RB"
    assert positions["Tyreek Hill"] == "WR"
    assert positions["Trey McBride"] == "TE"
    assert positions["Josh Allen"] == "QB"


def test_league_list_and_default_roster_slots(client):
    c, _ = client
    data = _create_league(c)
    leagues = c.get("/api/leagues").json()
    assert any(l["id"] == data["id"] for l in leagues)
    cfg = c.get(f"/api/draft/{data['access_token']}/admin/config").json()
    assert cfg["league"]["roster_slots"] == [
        "QB1", "QB2", "RB1", "RB2", "WR1", "WR2", "TE", "Flex", "DST", "K",
    ]


def test_update_roster_slots(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    resp = c.put(
        f"/api/draft/{token}/admin/roster",
        json={"slots": ["QB", "RB", "RB", "WR", "WR", "TE", "K"]},
    )
    assert resp.status_code == 200
    cfg = c.get(f"/api/draft/{token}/admin/config").json()
    assert cfg["league"]["roster_slots"] == ["QB", "RB", "RB", "WR", "WR", "TE", "K"]
    c.post(f"/api/draft/{token}/admin/start")
    resp = c.put(f"/api/draft/{token}/admin/roster", json={"slots": ["QB"]})
    assert resp.status_code == 400


def test_roster_by_slot_and_bench(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    resp = c.post(
        f"/api/draft/{token}/admin/import/csv",
        files={
            "file": (
                "players.csv",
                "player_id,name,position,nfl_team,rank,adp\n"
                + "\n".join(
                    f"p{i},Player {i},{pos},NFL,{i},{i}.0"
                    for i, pos in enumerate(["QB", "RB", "WR", "RB", "WR", "TE"], 1)
                ),
                "text/csv",
            )
        },
    )
    assert resp.status_code == 200
    players = c.get(f"/api/draft/{token}/admin/config").json()["players"]
    by_name = {p["name"]: p for p in players}
    c.post(f"/api/draft/{token}/admin/start")

    state = c.get(f"/api/draft/{token}/team/{data['teams'][1]['access_token']}").json()
    assert state["roster_slots"] == [
        "QB1", "QB2", "RB1", "RB2", "WR1", "WR2", "TE", "Flex", "DST", "K",
    ]

    # Team 1 on the clock first; pick for them, then Team 2 picks an RB.
    tokens = {t["id"]: t["access_token"] for t in data["teams"]}
    display = c.get(f"/api/draft/{token}/display").json()
    t1 = tokens[display["current_slot"]["drafting_team_id"]]
    assert c.post(
        f"/api/draft/{token}/team/{t1}/picks",
        json={"player_id": by_name["Player 1"]["id"]},
    ).status_code == 200
    team2 = data["teams"][1]["access_token"]
    assert c.post(
        f"/api/draft/{token}/team/{team2}/picks",
        json={"player_id": by_name["Player 2"]["id"]},
    ).status_code == 200

    state = c.get(f"/api/draft/{token}/team/{team2}").json()
    roster = {r["slot"]: r["player"] for r in state["roster_by_slot"]}
    assert roster["RB1"]["player_name"] == "Player 2"
    assert roster["QB1"] is None
    assert roster["Flex"] is None
    assert state["bench"] == []


def test_rosters_endpoint(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    rosters = c.get(f"/api/draft/{token}/rosters").json()
    assert rosters["status"] == "SETUP"
    assert len(rosters["teams"]) == 4
    assert len(rosters["teams"][0]["roster"]) == 10
    assert rosters["teams"][0]["bench"] == []


def test_delete_league(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    assert c.delete(f"/api/draft/{token}/admin/delete").status_code == 200
    assert c.get(f"/api/draft/{token}/admin/config").status_code == 404
    leagues = c.get("/api/leagues").json()
    assert all(l["id"] != data["id"] for l in leagues)