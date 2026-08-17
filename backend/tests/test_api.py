import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import League, LeagueStatus, Pick, PickType


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


def test_import_keeper_candidates_keepers_format(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    csv_text = (
        "Team,Player,Keeper_2024,Keeper_2023,Round_2024,Round_2023,"
        "Keeper_Eligible_2025,2025_Cost\n"
        "Team 1,RB NYJ 9 Breece Hall,True,False,2,,True,1\n"
        "Team 2,QB TEN 10 Will Levis,False,False,11,,True,10\n"
    )
    resp = c.post(
        f"/api/draft/{token}/admin/import/keepers",
        files={"files": ("keepers.csv", csv_text, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["stats"]["created"] == 2

    cfg = c.get(f"/api/draft/{token}/admin/config").json()
    candidates = cfg["keeper_candidates"]
    assert len(candidates) == 2
    by_team = {k["team_name"]: k for k in candidates}
    brece = by_team["Team 1"]
    assert brece["player_name"] == "Breece Hall"
    assert brece["position"] == "RB"
    assert brece["cost_round"] == 1
    assert brece["years_kept"] == 1
    assert by_team["Team 2"]["cost_round"] == 10
    assert by_team["Team 2"]["years_kept"] == 0
    assert len(cfg["players"]) == 2


def test_team_self_select_keepers_and_lock(client):
    c, _ = client
    payload = {
        "name": "Test League",
        "season": "2026",
        "num_teams": 4,
        "num_rounds": 3,
        "teams": [{"name": f"Team {i}", "manager_name": f"Mgr {i}"} for i in range(1, 5)],
    }
    data = c.post("/api/leagues", json=payload).json()
    token = data["access_token"]
    roster_csv = (
        "name,player_id,position_type,team,selected_position,was_added,2025_Cost\n"
        "Player 1,p1,O,NFL,QB,False,1.0\n"
        "Player 2,p2,O,NFL,RB,False,2.0\n"
        "Player 3,p3,O,NFL,WR,False,3.0\n"
        "Player 4,p4,O,NFL,RB,False,2.0\n"
        "Player 5,p5,O,NFL,TE,False,2.0\n"
    )
    resp = c.post(
        f"/api/draft/{token}/admin/import/keepers",
        files={"files": ("Team 1.csv", roster_csv, "text/csv")},
    )
    assert resp.status_code == 200
    team2_csv = (
        "name,player_id,position_type,team,selected_position,was_added,2025_Cost\n"
        "Player 6,p6,O,NFL,QB,False,1.0\n"
    )
    c.post(
        f"/api/draft/{token}/admin/import/keepers",
        files={"files": ("Team 2.csv", team2_csv, "text/csv")},
    )

    team1 = data["teams"][0]["access_token"]
    state = c.get(f"/api/draft/{token}/team/{team1}").json()
    assert state["status"] == "SETUP"
    assert len(state["keeper_candidates"]) == 5
    assert state["max_keepers"] == 3
    assert state["keeper_count"] == 0

    # Select up to 3 keepers (rounds 1, 2, 3 — distinct slots).
    state = c.get(f"/api/draft/{token}/team/{team1}").json()
    by_name = {k["player_name"]: k["player_id"] for k in state["keeper_candidates"]}
    for name in ["Player 1", "Player 2", "Player 3"]:
        assert (
            c.post(
                f"/api/draft/{token}/team/{team1}/keepers",
                json={"player_id": by_name[name]},
            ).status_code
            == 200
        )
    # A 4th keeper is rejected.
    assert (
        c.post(
            f"/api/draft/{token}/team/{team1}/keepers",
            json={"player_id": by_name["Player 5"]},
        ).status_code
        == 400
    )
    # Teams cannot keep another team's candidate.
    p6 = c.get(f"/api/draft/{token}/admin/config").json()["players"]
    p6 = next(p for p in p6 if p["name"] == "Player 6")
    assert (
        c.post(
            f"/api/draft/{token}/team/{team1}/keepers",
            json={"player_id": p6["id"]},
        ).status_code
        == 400
    )

    state = c.get(f"/api/draft/{token}/team/{team1}").json()
    assert state["keeper_count"] == 3
    assert len(state["keepers"]) == 3

    # Candidates reflect selections.
    assert sum(1 for k in state["keeper_candidates"] if k["selected"]) == 3

    # Selections lock once the draft starts.
    assert c.post(f"/api/draft/{token}/admin/start").status_code == 200
    state = c.get(f"/api/draft/{token}/team/{team1}").json()
    assert state["keeper_candidates"] == []
    assert (
        c.post(
            f"/api/draft/{token}/team/{team1}/keepers",
            json={"player_id": by_name["Player 4"]},
        ).status_code
        == 400
    )


def test_clear_keeper_candidates(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    csv_text = (
        "name,player_id,position_type,team,selected_position,was_added,2025_Cost\n"
        "Player 1,p1,O,NFL,RB,False,2.0\n"
    )
    c.post(
        f"/api/draft/{token}/admin/import/keepers",
        files={"files": ("Team 1.csv", csv_text, "text/csv")},
    )
    resp = c.delete(f"/api/draft/{token}/admin/keepers/candidates")
    assert resp.status_code == 200
    assert resp.json()["cleared"] == 1
    cfg = c.get(f"/api/draft/{token}/admin/config").json()
    assert cfg["keeper_candidates"] == []


def _upload_draft_csv(c, token, year, role, csv_text):
    return c.post(
        f"/api/draft/{token}/admin/keepers/draft-csv",
        files={"file": ("draft.csv", csv_text, "text/csv")},
        data={"year": year, "role": role},
    )


def test_keeper_admin_full_flow(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    team1 = data["teams"][0]["id"]

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["league"]["editable"] is True
    assert len(setup["teams"]) == 4

    previous = (
        "ROUND,Team 1,Team 2\n"
        '1,"RB\nSF\n1\nBreece\nHall"\n'
        '2,"WR\nNYJ\n2\nTyreek\nHill(K)"\n'
        '3,"RB\nDET\n3\nJahmyr\nGibbs"\n'
        '1,"QB\nBUF\n1\nJosh\nAllen"\n'
    )
    r = _upload_draft_csv(c, token, "2025", "previous", previous)
    assert r.status_code == 200
    assert r.json()["total_picks"] == 4

    prior = (
        "ROUND,Team 1,Team 2\n"
        '1,"WR\nNYJ\n2\nTyreek\nHill(K)"\n'
    )
    r = _upload_draft_csv(c, token, "2024", "prior", prior)
    assert r.status_code == 200

    roster1 = (
        "name,player_id,team,selected_position,was_added\n"
        "Breece Hall,p1,SF,RB,False\n"
        "Tyreek Hill,p2,NYJ,WR,False\n"
        "Jahmyr Gibbs,p3,DET,RB,True\n"
    )
    r = c.post(
        f"/api/draft/{token}/admin/keepers/rosters-csv",
        files=[("files", ("Team 1.csv", roster1, "text/csv"))],
    )
    assert r.status_code == 200
    assert r.json()["teams"] == {"Team 1": 3}

    mappings = {"mappings": [{"team_id": team1, "draft_name": "Team 1", "yahoo_name": "Team 1"}]}
    assert c.post(f"/api/draft/{token}/admin/keepers/mappings", json=mappings).status_code == 200

    r = c.post(f"/api/draft/{token}/admin/keepers/identify")
    assert r.status_code == 200
    body = r.json()
    preview = body["preview"]
    assert len(preview) == 1
    candidates = preview[0]["candidates"]
    by_name = {x["player_name"]: x for x in candidates}
    # Kept 2 consecutive years -> ineligible.
    assert "Tyreek Hill" not in by_name
    # Round-1 drafted, not keeper -> cost 1 (floored).
    assert by_name["Breece Hall"]["cost_round"] == 1
    assert by_name["Breece Hall"]["years_kept"] == 0
    # Waiver add -> round 11.
    assert by_name["Jahmyr Gibbs"]["cost_round"] == 11
    assert by_name["Jahmyr Gibbs"]["years_kept"] == 0
    assert "kept 2 consecutive" in "\n".join(body["warnings"])

    r = c.post(f"/api/draft/{token}/admin/keepers/save", json={})
    assert r.status_code == 200
    assert r.json()["stats"]["created"] == 2

    cfg = c.get(f"/api/draft/{token}/admin/config").json()
    assert len(cfg["keeper_candidates"]) == 2

    r = c.get(f"/api/draft/{token}/admin/keepers/export")
    assert r.status_code == 200
    export = r.json()
    assert len(export["teams"]) == 1
    assert "Breece Hall" in export["teams"][0]["csv"]
    assert "Jahmyr Gibbs" in export["teams"][0]["csv"]


def test_keeper_admin_requires_draft_and_rosters(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    assert c.post(f"/api/draft/{token}/admin/keepers/identify").status_code == 400
    assert c.post(f"/api/draft/{token}/admin/keepers/save", json={}).status_code == 400


def test_keeper_admin_yahoo_config_and_authorize(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    r = c.post(
        f"/api/draft/{token}/admin/keepers/yahoo-config",
        json={
            "league_id_external": "735068",
            "game_id": 449,
            "season_id": "2025",
            "consumer_key": "abc123secret",
            "consumer_secret": "shhhhh",
        },
    )
    assert r.status_code == 200
    yahoo = r.json()["yahoo"]
    assert yahoo["configured"] is True
    assert yahoo["consumer_key"] != "abc123secret"  # masked
    assert yahoo["has_token"] is False

    r = c.post(f"/api/draft/{token}/admin/keepers/yahoo/authorize")
    assert r.status_code == 200
    assert "api.login.yahoo.com" in r.json()["authorization_url"]

    r = c.post(f"/api/draft/{token}/admin/keepers/fetch")
    assert r.status_code == 400  # not authorized


def test_keeper_admin_yahoo_test_and_teams(client, monkeypatch):
    c, session = client
    data = _create_league(c)
    token = data["access_token"]

    # No config -> 400.
    r = c.post(f"/api/draft/{token}/admin/keepers/yahoo/teams")
    assert r.status_code == 400

    c.post(
        f"/api/draft/{token}/admin/keepers/yahoo-config",
        json={
            "league_id_external": "735068",
            "game_id": 449,
            "consumer_key": "consumer_key_x",
            "consumer_secret": "shhhhh",
        },
    )
    # Config set but no token -> 400.
    assert c.post(f"/api/draft/{token}/admin/keepers/yahoo/teams").status_code == 400

    from app.draft import yahoo as yahoo_mod
    from app.models import YahooConfig

    cfg = session.query(YahooConfig).one()
    cfg.access_token_json = {
        "access_token": "fake-token",
        "consumer_key": "consumer_key_x",
        "consumer_secret": "shhhhh",
        "guid": "g",
        "refresh_token": "",
        "token_time": 0,
        "token_type": "bearer",
    }
    session.commit()

    monkeypatch.setattr(
        yahoo_mod,
        "fetch_league_teams",
        lambda **kwargs: ["Team A", "Team B"],
    )
    r = c.post(f"/api/draft/{token}/admin/keepers/yahoo/teams")
    assert r.status_code == 200
    body = r.json()
    assert body["teams"] == ["Team A", "Team B"]
    assert body["count"] == 2

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["rosters"]["teams"] == ["Team A", "Team B"]
    assert setup["rosters"]["player_count"] == 0

    # Test saving Yahoo config when already authorized automatically refreshes team names
    monkeypatch.setattr(
        yahoo_mod,
        "fetch_league_teams",
        lambda **kwargs: ["Team Alpha", "Team Beta"],
    )
    r = c.post(
        f"/api/draft/{token}/admin/keepers/yahoo-config",
        json={
            "league_id_external": "735068",
            "game_id": 449,
            "season_id": "2025",
        },
    )
    assert r.status_code == 200
    assert r.json()["teams_fetched"] is True
    assert r.json()["teams"] == ["Team Alpha", "Team Beta"]

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["rosters"]["teams"] == ["Team Alpha", "Team Beta"]

    # Test OAuth callback automatically pulls team names upon connection
    monkeypatch.setattr(
        yahoo_mod,
        "exchange_code",
        lambda *args, **kwargs: {"access_token": "new-token", "refresh_token": "rf", "token_type": "bearer"},
    )
    monkeypatch.setattr(
        yahoo_mod,
        "fetch_league_teams",
        lambda **kwargs: ["Team X", "Team Y"],
    )
    r = c.post(
        f"/api/draft/{token}/admin/keepers/yahoo/callback",
        json={"code": "valid-oauth-code"},
    )
    assert r.status_code == 200
    assert r.json()["teams_fetched"] is True
    assert r.json()["teams"] == ["Team X", "Team Y"]

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["rosters"]["teams"] == ["Team X", "Team Y"]


def _complete_league_with_picks(c, session, data, picks):
    """Drive `data` (from _create_league) to COMPLETED with direct Pick rows.

    picks: list of (slot_index, team_index, player_name, pick_type).
    """
    token = data["access_token"]
    csv_data = "player_id,name,position,nfl_team,rank\n" + "\n".join(
        f"p{i},Player {i},{'RB' if i % 2 else 'QB'},NFL,{i}"
        for i in range(1, 9)
    )
    c.post(
        f"/api/draft/{token}/admin/import/csv",
        files={"file": ("players.csv", csv_data, "text/csv")},
    )
    league = session.get(League, data["id"])
    teams = sorted(league.teams, key=lambda t: t.draft_position)
    players = {p.name: p for p in league.players}
    slots = sorted(league.slots, key=lambda s: s.pick_number)
    for slot_index, team_index, player_name, pick_type in picks:
        slot = slots[slot_index]
        session.add(
            Pick(
                league_id=league.id,
                draft_slot_id=slot.id,
                team_id=teams[team_index].id,
                player_id=players[player_name].id,
                pick_type=pick_type,
            )
        )
    league.status = LeagueStatus.COMPLETED
    session.commit()
    return league


def test_keeper_admin_use_completed_draft(client):
    c, session = client
    src = _create_league(c)
    src_league = _complete_league_with_picks(
        c,
        session,
        src,
        [
            (0, 0, "Player 1", PickType.LIVE),  # r1 Team 1
            (1, 1, "Player 2", PickType.KEEPER),  # r1 Team 2 kept
            (2, 0, "Player 3", PickType.LIVE),  # r2 Team 1
            (3, 1, "Player 4", PickType.LIVE),  # r2 Team 2
        ],
    )

    cur = _create_league(c)
    token = cur["access_token"]

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert len(setup["previous_drafts"]) == 1
    assert setup["previous_drafts"][0]["picks"] == 4

    r = c.post(
        f"/api/draft/{token}/admin/keepers/use-draft",
        json={"draft_league_id": src_league.id, "role": "previous"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == src_league.season
    assert body["teams"] == {"Team 1": 2, "Team 2": 2}

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["draft"]["has_draft"] is True
    assert setup["draft"]["previous_year"] == src_league.season
    assert "Team 1" in setup["draft"]["draft_teams"]

    r = c.post(
        f"/api/draft/{token}/admin/keepers/use-draft",
        json={"draft_league_id": src_league.id, "role": "prior"},
    )
    assert r.status_code == 200
    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["draft"]["prior_year"] == src_league.season

    # The current league itself cannot be used as its own prior draft.
    r = c.post(
        f"/api/draft/{token}/admin/keepers/use-draft",
        json={"draft_league_id": cur["id"], "role": "previous"},
    )
    assert r.status_code == 400
    assert "not a completed draft" in r.json()["detail"]