import json
import os

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
    os.environ["ADMIN_PASSCODE"] = "test-passcode"
    with TestClient(
        app, headers={"X-Admin-Passcode": "test-passcode"}
    ) as c:
        yield c, session
    os.environ.pop("ADMIN_PASSCODE", None)
    app.dependency_overrides.clear()
    session.close()


@pytest.fixture()
def client_no_auth():
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
    os.environ["ADMIN_PASSCODE"] = "test-passcode"
    with TestClient(app) as c:
        yield c, session
    os.environ.pop("ADMIN_PASSCODE", None)
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
    assert "tier" not in cmc
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


def test_set_draft_order_rebuilds_slots_and_resets_trades(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]

    # Simulate a trade: give the round-2 pick 2 slot to a different team.
    cfg = c.get(f"/api/draft/{token}/admin/config").json()
    round2_pick1 = next(
        s for s in cfg["slots"] if s["round"] == 2 and s["pick_number"] == 5
    )
    other = next(t for t in data["teams"] if t["id"] != round2_pick1["original_team_id"])
    r = c.put(
        f"/api/draft/{token}/admin/slots/{round2_pick1['slot_id']}",
        json={"drafting_team_id": other["id"]},
    )
    assert r.status_code == 200

    # Reverse the draft order and save.
    rev = list(reversed(data["teams"]))
    order = [{"position": i + 1, "team_id": rev[i]["id"]} for i in range(len(rev))]
    resp = c.post(f"/api/draft/{token}/admin/draft-order", json={"order": order})
    assert resp.status_code == 200

    cfg = c.get(f"/api/draft/{token}/admin/config").json()
    assert len(cfg["slots"]) == 8
    assert [t["draft_position"] for t in cfg["teams"]] == [1, 2, 3, 4]
    # Round 1 pick 1 is now owned by the old last team.
    slot1 = cfg["slots"][0]
    assert slot1["round"] == 1 and slot1["pick_number"] == 1
    assert slot1["original_team_id"] == rev[0]["id"]
    # All trades were reset: drafting team == original owner everywhere.
    assert all(s["drafting_team_id"] == s["original_team_id"] for s in cfg["slots"])
    # Snake order is preserved for the new mapping.
    rev_sorted = sorted(cfg["teams"], key=lambda t: t["draft_position"])
    round2_pick1_after = next(
        s for s in cfg["slots"] if s["round"] == 2 and s["pick_number"] == 5
    )
    assert round2_pick1_after["original_team_id"] == rev_sorted[-1]["id"]


def test_set_draft_order_rejects_bad_permutations(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    teams = data["teams"]
    dup_order = [{"position": 1, "team_id": teams[0]["id"]},
                 {"position": 2, "team_id": teams[0]["id"]},
                 {"position": 3, "team_id": teams[2]["id"]},
                 {"position": 4, "team_id": teams[3]["id"]}]
    r = c.post(f"/api/draft/{token}/admin/draft-order", json={"order": dup_order})
    assert r.status_code == 400

    partial = [{"position": 1, "team_id": teams[0]["id"]}]
    r = c.post(f"/api/draft/{token}/admin/draft-order", json={"order": partial})
    assert r.status_code == 400

    # Once the draft starts, the order is frozen.
    c.post(f"/api/draft/{token}/admin/start")
    ok_order = [{"position": i + 1, "team_id": teams[i]["id"]} for i in range(4)]
    r = c.post(f"/api/draft/{token}/admin/draft-order", json={"order": ok_order})
    assert r.status_code == 400


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


def _clicky_draft_html(year, team_name, picks):
    league = {
        "displayName": f"Test League {year}",
        "year": year,
        "fantasyTeams": [
            {"id": 101, "teamName": team_name, "draftPosition": 1}
        ],
    }
    clicky_picks = []
    for index, pick in enumerate(picks, start=1):
        first, last = pick["name"].split(" ", 1)
        clicky_picks.append(
            {
                "round": pick["round"],
                "posInRound": index,
                "fantasyTeamId": 101,
                "keeper": pick.get("keeper", False),
                "draftablePlayer": {
                    "id": index,
                    "firstName": first,
                    "lastName": last,
                    "positions": [pick["position"]],
                    "teamAbbr": pick["nfl_team"],
                },
            }
        )

    def embedded(value):
        return json.dumps(value).replace("'", "&#39;")

    return (
        "<html><script>window.data = {"
        f"requestedLgInstJSON : '{embedded(league)}',"
        f"requestedPicksJSON : '{embedded(clicky_picks)}',"
        "};</script></html>"
    )


def _yahoo_transactions_html(trade_rows=""):
    return (
        '<html><table class="Tst-transaction-table"><tbody>'
        f"{trade_rows}"
        "</tbody></table></html>"
    )


def _upload_transactions(c, token, html=None):
    return c.post(
        f"/api/draft/{token}/admin/keepers/transactions-html",
        files={
            "file": (
                "Transactions.html",
                html if html is not None else _yahoo_transactions_html(),
                "text/html",
            )
        },
    )


def test_yahoo_transactions_parser_handles_multi_player_and_pick_rows():
    from app.draft import yahoo_transactions

    html = """
      <html><table class="Tst-transaction-table"><tbody>
        <tr>
          <td><span class="F-icon Fz-xl F-trade"></span></td>
          <td>
            <a href="https://sports.yahoo.com/nfl/players/1">Caleb Williams</a>
            <a href="https://sports.yahoo.com/nfl/players/2">Harold Fannin Jr.</a>
            <span>Round 14</span>
          </td>
          <td class="Ta-end"><a href="/2025/f1/123/3">BUC-EES Irving</a></td>
        </tr>
        <tr>
          <td></td>
          <td><a href="https://sports.yahoo.com/nfl/players/3">Some Player</a></td>
          <td class="Ta-end"><a href="/2025/f1/123/4">Talkin' Bout Sun Darts</a></td>
        </tr>
        <tr>
          <td><span class="F-icon Fz-xl F-trade"></span></td>
          <td><a href="https://sports.yahoo.com/nfl/players/5">Lone Player</a></td>
          <td class="Ta-end"><a href="/2025/f1/123/5">Team Five</a></td>
        </tr>
        <tr>
          <td></td>
          <td>Round 6</td>
          <td class="Ta-end"><a href="/2025/f1/123/6">Team Six</a></td>
        </tr>
      </tbody></table></html>
    """
    trades = yahoo_transactions.parse_transactions(html)
    by_name = {trade["player"]: trade for trade in trades}
    assert len(trades) == 3
    assert by_name["Caleb Williams"] == {
        "date": "",
        "player": "Caleb Williams",
        "player_id": "1",
        "from_team": "Talkin' Bout Sun Darts",
        "to_team": "BUC-EES Irving",
    }
    assert by_name["Harold Fannin Jr."]["from_team"] == "Talkin' Bout Sun Darts"
    assert by_name["Some Player"]["from_team"] == "BUC-EES Irving"
    # The second block's pick-only side is skipped, so no trade is emitted.
    assert "Lone Player" not in by_name


def test_keeper_admin_uploads_clickydraft_html_for_both_seasons(client):
    c, _ = client
    token = _create_league(c)["access_token"]
    previous = _clicky_draft_html(
        2025,
        "Current Team Name",
        [
            {"round": 3, "name": "Breece Hall", "position": "RB", "nfl_team": "NYJ"},
            {"round": 5, "name": "Ja'Marr Chase", "position": "WR", "nfl_team": "CIN", "keeper": True},
        ],
    )
    r = c.post(
        f"/api/draft/{token}/admin/keepers/draft-html",
        files={"file": ("clickydraft-2025.html", previous, "text/html")},
        data={"role": "previous"},
    )
    assert r.status_code == 200
    assert r.json() == {
        "ok": True,
        "year": "2025",
        "role": "previous",
        "draft_name": "Test League 2025",
        "teams": {"Current Team Name": 2},
        "total_picks": 2,
    }

    prior = _clicky_draft_html(
        2024,
        "Old Team Name",
        [{"round": 6, "name": "Ja'Marr Chase", "position": "WR", "nfl_team": "CIN", "keeper": True}],
    )
    r = c.post(
        f"/api/draft/{token}/admin/keepers/draft-html",
        files={"file": ("clickydraft-2024.html", prior, "text/html")},
        data={"role": "prior"},
    )
    assert r.status_code == 200
    assert r.json()["year"] == "2024"

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["draft"]["previous_year"] == "2025"
    assert setup["draft"]["prior_year"] == "2024"
    assert setup["draft"]["draft_teams"] == ["Current Team Name"]
    assert setup["draft"]["draft_counts"] == {
        "2025": {"Current Team Name": 2},
        "2024": {"Old Team Name": 1},
    }


def test_keeper_admin_rejects_non_clickydraft_html(client):
    c, _ = client
    token = _create_league(c)["access_token"]
    r = c.post(
        f"/api/draft/{token}/admin/keepers/draft-html",
        files={"file": ("draft.html", "<html></html>", "text/html")},
        data={"role": "previous"},
    )
    assert r.status_code == 400
    assert "requestedLgInstJSON" in r.json()["detail"]


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
        '3,"WR\nNYJ\n2\nTyreek\nHill(K)"\n'
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
    assert _upload_transactions(c, token).status_code == 200

    r = c.post(f"/api/draft/{token}/admin/keepers/identify")
    assert r.status_code == 200
    body = r.json()
    preview = body["preview"]
    assert len(preview) == 1
    candidates = preview[0]["candidates"]
    by_name = {x["player_name"]: x for x in candidates}
    # Kept 2 consecutive years -> ineligible.
    assert "Tyreek Hill" not in by_name
    # Round-1 drafted -> cannot be kept.
    assert "Breece Hall" not in by_name
    # Drafted by this team (round 3) -> draft-based cost, even if later added/dropped.
    assert by_name["Jahmyr Gibbs"]["cost_round"] == 1
    assert by_name["Jahmyr Gibbs"]["years_kept"] == 0
    assert "kept 2 consecutive" in "\n".join(body["warnings"])
    assert "Breece Hall drafted in round 1" in "\n".join(body["warnings"])

    r = c.post(f"/api/draft/{token}/admin/keepers/save", json={})
    assert r.status_code == 200
    assert r.json()["stats"]["created"] == 1

    cfg = c.get(f"/api/draft/{token}/admin/config").json()
    assert len(cfg["keeper_candidates"]) == 1

    r = c.get(f"/api/draft/{token}/admin/keepers/export")
    assert r.status_code == 200
    export = r.json()
    assert len(export["teams"]) == 1
    assert "Breece Hall" not in export["teams"][0]["csv"]
    assert "Jahmyr Gibbs" in export["teams"][0]["csv"]


def test_keeper_admin_round_two_draft_eliminated(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    team1 = data["teams"][0]["id"]

    previous = (
        "ROUND,Team 1,Team 2\n"
        '2,"WR\nCIN\n2\nSecond\nRounder"\n'
        '3,"RB\nNYJ\n3\nThird\nRounder"\n'
    )
    assert _upload_draft_csv(c, token, "2025", "previous", previous).status_code == 200

    prior = "ROUND,Team 1,Team 2\n" '1,"RB\nNYJ\n3\nThird\nRounder"\n'
    assert _upload_draft_csv(c, token, "2024", "prior", prior).status_code == 200

    roster1 = (
        "name,player_id,team,selected_position,was_added\n"
        "Second Rounder,p2,CIN,WR,False\n"
        "Third Rounder,p3,NYJ,RB,False\n"
    )
    assert c.post(
        f"/api/draft/{token}/admin/keepers/rosters-csv",
        files=[("files", ("Team 1.csv", roster1, "text/csv"))],
    ).status_code == 200

    mappings = {"mappings": [{"team_id": team1, "draft_name": "Team 1", "yahoo_name": "Team 1"}]}
    assert c.post(f"/api/draft/{token}/admin/keepers/mappings", json=mappings).status_code == 200
    assert _upload_transactions(c, token).status_code == 200

    r = c.post(f"/api/draft/{token}/admin/keepers/identify")
    assert r.status_code == 200
    body = r.json()
    by_name = {x["player_name"]: x for x in body["preview"][0]["candidates"]}
    assert "Second Rounder" not in by_name
    assert by_name["Third Rounder"]["cost_round"] == 1
    assert "Second Rounder drafted in round 2" in "\n".join(body["warnings"])


def test_keeper_admin_saves_and_restores_each_team_independently(client):
    c, session = client
    data = _create_league(c)
    token = data["access_token"]
    team1 = data["teams"][0]
    team2 = data["teams"][1]
    league = session.query(League).filter(League.access_token == token).one()
    league.keeper_workspace = {
        "preview": [
            {
                "team_id": team1["id"],
                "team_name": team1["name"],
                "candidates": [
                    {
                        "player_name": "Player 1",
                        "position": "RB",
                        "nfl_team": "NYJ",
                        "player_id_external": "p1",
                        "cost_round": 3,
                        "years_kept": 0,
                        "keepable_until_year": "2027",
                    }
                ],
            },
            {
                "team_id": team2["id"],
                "team_name": team2["name"],
                "candidates": [
                    {
                        "player_name": "Player 2",
                        "position": "WR",
                        "nfl_team": "CIN",
                        "player_id_external": "p2",
                        "cost_round": 4,
                        "years_kept": 0,
                        "keepable_until_year": "2027",
                    }
                ],
            },
        ],
        "preview_warnings": [],
    }
    session.commit()

    team1_save = {
        "teams": [
            {
                "team_id": team1["id"],
                "candidates": [
                    {
                        "player_name": "Player 1",
                        "position": "RB",
                        "nfl_team": "NYJ",
                        "player_id_external": "p1",
                        "cost_round": 7,
                        "years_kept": 0,
                        "keepable_until_year": "2027",
                    }
                ],
            }
        ]
    }
    response = c.post(f"/api/draft/{token}/admin/keepers/save", json=team1_save)
    assert response.status_code == 200
    assert response.json()["reviewed_team_ids"] == [team1["id"]]

    # Returning to setup restores the edited round and leaves team 2 untouched.
    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    preview = {team["team_id"]: team for team in setup["preview"]["teams"]}
    assert preview[team1["id"]]["candidates"][0]["cost_round"] == 7
    assert preview[team2["id"]]["candidates"][0]["cost_round"] == 4
    assert setup["preview"]["reviewed_team_ids"] == [team1["id"]]
    config = c.get(f"/api/draft/{token}/admin/config").json()
    assert [candidate["team_id"] for candidate in config["keeper_candidates"]] == [
        team1["id"]
    ]

    team2_save = {
        "teams": [
            {
                "team_id": team2["id"],
                "candidates": preview[team2["id"]]["candidates"],
            }
        ]
    }
    response = c.post(f"/api/draft/{token}/admin/keepers/save", json=team2_save)
    assert response.status_code == 200
    assert response.json()["reviewed_team_ids"] == sorted([team1["id"], team2["id"]])
    config = c.get(f"/api/draft/{token}/admin/config").json()
    assert {candidate["team_id"] for candidate in config["keeper_candidates"]} == {
        team1["id"],
        team2["id"],
    }


def test_keeper_admin_uploads_yahoo_roster_html(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    team1 = data["teams"][0]["id"]

    previous = (
        "ROUND,Team 1\n"
        '3,"RB\nNYJ\n1\nBreece\nHall"\n'
        '5,"WR\nMIA\n2\nTyreek\nHill"\n'
    )
    assert _upload_draft_csv(c, token, "2025", "previous", previous).status_code == 200
    prior = "ROUND,Team 1\n"
    assert _upload_draft_csv(c, token, "2024", "prior", prior).status_code == 400
    prior = (
        "ROUND,Team 1\n"
        '8,"RB\nNYJ\n1\nAnother\nPlayer"\n'
    )
    assert _upload_draft_csv(c, token, "2024", "prior", prior).status_code == 200

    html = """
        <html><body>
          <span class="flyout-title">Week 13</span>
          <div>
            <p><a href="/2025/f1/123/1">Team 1</a></p>
            <table id="Tst-team-1"><tbody>
              <tr><td>RB</td><td><a class="name" href="https://sports.yahoo.com/nfl/players/31879">Breece Hall</a></td></tr>
              <tr><td>BN</td><td><a class="name" href="https://sports.yahoo.com/nfl/players/30123">Tyreek Hill</a><a href="#">Video Forecast</a></td></tr>
            </tbody></table>
          </div>
          <div>
            <p><a href="/2025/f1/123/2">Team 2</a></p>
            <table id="Tst-team-2"><tbody>
              <tr><td>QB</td><td><a class="name" href="https://sports.yahoo.com/nfl/players/999">Josh Allen</a></td></tr>
            </tbody></table>
          </div>
        </body></html>
    """
    r = c.post(
        f"/api/draft/{token}/admin/keepers/rosters-html",
        files={"file": ("Starting Rosters.html", html, "text/html")},
    )
    assert r.status_code == 200
    assert r.json() == {
        "ok": True,
        "teams": {"Team 1": 2, "Team 2": 1},
        "week": 13,
        "player_count": 3,
    }

    setup = c.get(f"/api/draft/{token}/admin/keepers/setup").json()
    assert setup["rosters"] == {
        "has_rosters": True,
        "teams": ["Team 1", "Team 2"],
        "week": 13,
        "source": "Yahoo HTML",
        "player_count": 3,
    }
    mappings = {
        "mappings": [
            {"team_id": team1, "draft_name": "Team 1", "yahoo_name": "Team 1"}
        ]
    }
    assert c.post(f"/api/draft/{token}/admin/keepers/mappings", json=mappings).status_code == 200
    assert _upload_transactions(c, token).status_code == 200
    identified = c.post(f"/api/draft/{token}/admin/keepers/identify")
    assert identified.status_code == 200
    candidates = identified.json()["preview"][0]["candidates"]
    assert [(p["player_name"], p["cost_round"], p["player_id_external"]) for p in candidates] == [
        ("Breece Hall", 1, "31879"),
        ("Tyreek Hill", 3, "30123"),
    ]


def test_keeper_admin_rejects_non_roster_html(client):
    c, _ = client
    token = _create_league(c)["access_token"]
    r = c.post(
        f"/api/draft/{token}/admin/keepers/rosters-html",
        files={"file": ("page.html", "<html><body>Yahoo</body></html>", "text/html")},
    )
    assert r.status_code == 400
    assert "No Yahoo roster tables found" in r.json()["detail"]


def test_keeper_admin_uses_original_draft_pick_for_traded_player(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    team1 = data["teams"][0]["id"]
    previous = (
        "ROUND,Team 1,Team 2\n"
        '3,"RB\nNYJ\n1\nOwn\nPlayer",\n'
        '8,,"WR\nCIN\n2\nTraded\nPlayer"\n'
        '10,,"TE\nDET\n3\nInferred\nTrade"\n'
    )
    assert _upload_draft_csv(c, token, "2025", "previous", previous).status_code == 200
    prior = (
        "ROUND,Team 1,Team 2\n"
        '10,"QB\nBUF\n1\nPrior\nPlayer",\n'
    )
    assert _upload_draft_csv(c, token, "2024", "prior", prior).status_code == 200

    roster = (
        "name,player_id,team,selected_position,was_added\n"
        "Own Player,p1,NYJ,RB,False\n"
        "Traded Player,p2,CIN,WR,True\n"
        "Inferred Trade,p5,DET,TE,True\n"
        "Free Agent,p3,DAL,WR,False\n"
    )
    assert c.post(
        f"/api/draft/{token}/admin/keepers/rosters-csv",
        files=[("files", ("Team 1.csv", roster, "text/csv"))],
    ).status_code == 200

    trade_rows = """
      <tr>
        <td><span class="F-icon Fz-xl F-trade"></span></td>
        <td>
          <a href="https://sports.yahoo.com/nfl/players/2">Traded Player</a>
        </td>
        <td class="Ta-end">
          <a href="/2025/f1/123/1">Team 1</a>
          <span class="F-timestamp">Oct 8, 11:37 pm</span>
        </td>
      </tr>
      <tr>
        <td></td>
        <td>
          <a href="https://sports.yahoo.com/nfl/players/4">Return Player</a>
        </td>
        <td class="Ta-end">
          <a href="/2025/f1/123/2">Team 2</a>
          <span class="F-timestamp">Oct 8, 11:37 pm</span>
        </td>
      </tr>
    """
    transaction_response = _upload_transactions(
        c, token, _yahoo_transactions_html(trade_rows)
    )
    assert transaction_response.status_code == 200
    assert transaction_response.json()["trade_count"] == 2
    assert transaction_response.json()["trades"][0] == {
        "date": "Oct 8",
        "player": "Traded Player",
        "player_id": "2",
        "from_team": "Team 2",
        "to_team": "Team 1",
    }

    mappings = {
        "mappings": [
            {"team_id": team1, "draft_name": "Team 1", "yahoo_name": "Team 1"}
        ]
    }
    assert c.post(f"/api/draft/{token}/admin/keepers/mappings", json=mappings).status_code == 200
    response = c.post(f"/api/draft/{token}/admin/keepers/identify")
    assert response.status_code == 200
    candidates = {
        player["player_name"]: player
        for player in response.json()["preview"][0]["candidates"]
    }
    assert candidates["Own Player"]["cost_round"] == 1
    # Trade confirmed by transaction row -> round from the ORIGINAL team's draft.
    assert candidates["Traded Player"]["cost_round"] == 6
    # No transaction row: not drafted by this team and not traded -> dropped (round 11).
    assert candidates["Inferred Trade"]["cost_round"] == 11
    assert candidates["Free Agent"]["cost_round"] == 11
    assert "Free Agent not drafted by this team and no trade found" in "\n".join(
        response.json()["warnings"]
    )


def test_keeper_admin_traces_multi_hop_trade_to_original_drafter(client):
    c, _ = client
    data = _create_league(c)
    token = data["access_token"]
    team1 = data["teams"][0]["id"]

    # Team 2 drafted "Chained Player" in round 8, then traded him to Team 3,
    # who traded him to Team 1. Cost must come from Team 2's draft, not Team 3.
    previous = (
        "ROUND,Team 1,Team 2,Team 3\n"
        '5,"RB\nNYJ\n1\nOwn\nPlayer",,\n'
        '8,,"WR\nCIN\n2\nChained\nPlayer"\n'
        '10,,,"TE\nDET\n3\nTeam3\nPlayer"\n'
    )
    assert _upload_draft_csv(c, token, "2025", "previous", previous).status_code == 200

    prior = "ROUND,Team 1,Team 2,Team 3\n" '12,"QB\nBUF\n1\nPrior\nPlayer",,\n'
    assert _upload_draft_csv(c, token, "2024", "prior", prior).status_code == 200

    roster = (
        "name,player_id,team,selected_position,was_added\n"
        "Own Player,p1,NYJ,RB,False\n"
        "Chained Player,p2,CIN,WR,True\n"
    )
    assert c.post(
        f"/api/draft/{token}/admin/keepers/rosters-csv",
        files=[("files", ("Team 1.csv", roster, "text/csv"))],
    ).status_code == 200

    mappings = {
        "mappings": [
            {"team_id": team1, "draft_name": "Team 1", "yahoo_name": "Team 1"}
        ]
    }
    assert c.post(f"/api/draft/{token}/admin/keepers/mappings", json=mappings).status_code == 200

    # Trade 1: Chained Player Team 2 -> Team 3 (with Team3 Player going back).
    trade_rows = """
      <tr>
        <td><span class="F-icon Fz-xl F-trade"></span></td>
        <td>
          <a href="https://sports.yahoo.com/nfl/players/2">Chained Player</a>
        </td>
        <td class="Ta-end">
          <a href="/2025/f1/123/3">Team 3</a>
          <span class="F-timestamp">Oct 1, 11:00 am</span>
        </td>
      </tr>
      <tr>
        <td></td>
        <td>
          <a href="https://sports.yahoo.com/nfl/players/3">Team3 Player</a>
        </td>
        <td class="Ta-end">
          <a href="/2025/f1/123/2">Team 2</a>
          <span class="F-timestamp">Oct 1, 11:00 am</span>
        </td>
      </tr>
      <tr>
        <td><span class="F-icon Fz-xl F-trade"></span></td>
        <td>
          <a href="https://sports.yahoo.com/nfl/players/2">Chained Player</a>
        </td>
        <td class="Ta-end">
          <a href="/2025/f1/123/1">Team 1</a>
          <span class="F-timestamp">Oct 9, 2:30 pm</span>
        </td>
      </tr>
      <tr>
        <td></td>
        <td>
          <a href="https://sports.yahoo.com/nfl/players/4">Return Player</a>
        </td>
        <td class="Ta-end">
          <a href="/2025/f1/123/3">Team 3</a>
          <span class="F-timestamp">Oct 9, 2:30 pm</span>
        </td>
      </tr>
    """
    assert _upload_transactions(c, token, _yahoo_transactions_html(trade_rows)).status_code == 200

    response = c.post(f"/api/draft/{token}/admin/keepers/identify")
    assert response.status_code == 200
    candidates = {
        player["player_name"]: player
        for player in response.json()["preview"][0]["candidates"]
    }
    # Own draft pick -> own round.
    assert candidates["Own Player"]["cost_round"] == 3
    # Traced back through Team 3 to the original drafter Team 2 (round 8).
    assert candidates["Chained Player"]["cost_round"] == 6


def test_keeper_admin_rejects_non_transaction_html(client):
    c, _ = client
    token = _create_league(c)["access_token"]
    response = _upload_transactions(c, token, "<html></html>")
    assert response.status_code == 400
    assert "transaction table" in response.json()["detail"]


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


def test_admin_gate_blocks_without_passcode(client_no_auth):
    c, _ = client_no_auth
    assert c.get("/api/leagues").status_code == 401
    payload = {
        "name": "Blocked",
        "season": "2026",
        "num_teams": 2,
        "num_rounds": 2,
        "teams": [{"name": "Team 1", "manager_name": ""}, {"name": "Team 2", "manager_name": ""}],
    }
    assert c.post("/api/leagues", json=payload).status_code == 401
    assert c.get("/api/draft/whatever/admin/config").status_code == 401
    assert c.post("/api/draft/whatever/admin/start").status_code == 401


def test_admin_gate_rejects_wrong_passcode(client_no_auth):
    c, _ = client_no_auth
    r = c.get("/api/leagues", headers={"X-Admin-Passcode": "wrong"})
    assert r.status_code == 401


def test_admin_gate_lets_public_paths_through(client_no_auth):
    c, _ = client_no_auth
    data = {
        "name": "Public",
        "season": "2026",
        "num_teams": 2,
        "num_rounds": 2,
        "teams": [{"name": "Team 1", "manager_name": ""}, {"name": "Team 2", "manager_name": ""}],
    }
    # Creating a league requires the passcode, so seed via the authed client path:
    c.post("/api/leagues", json=data, headers={"X-Admin-Passcode": "test-passcode"})
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/ping").status_code == 200


def test_admin_gate_unconfigured_returns_503(client_no_auth, monkeypatch):
    c, _ = client_no_auth
    monkeypatch.delenv("ADMIN_PASSCODE", raising=False)
    assert c.get("/api/leagues").status_code == 503


def test_admin_gate_allows_authed_create(client):
    c, _ = client
    data = _create_league(c)
    assert data["status"] == "SETUP"
    token = data["access_token"]
    assert c.get(f"/api/draft/{token}/admin/config").status_code == 200
