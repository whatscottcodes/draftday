import asyncio
import json

import httpx
import websockets

BASE = "http://localhost:8000"
WS = "ws://localhost:8000"


async def main():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{BASE}/api/leagues",
            json={
                "name": "E2E League",
                "season": "2026",
                "num_teams": 4,
                "num_rounds": 3,
                "teams": [{"name": f"Team {i}", "manager_name": f"M{i}"} for i in range(1, 5)],
            },
        )
        assert r.status_code == 200, r.text
        league = r.json()
        token = league["access_token"]
        teams = league["teams"]
        print("1. league created:", league["name"])

        csv_data = (
            "player_id,name,position,nfl_team,rank,adp\n"
            + "\n".join(
                f"p{i},Player {i},{['QB', 'RB', 'WR', 'TE'][i % 4]},NFL,{i},{i}.0"
                for i in range(1, 41)
            )
        )
        r = await c.post(
            f"{BASE}/api/draft/{token}/admin/import/csv",
            files={"file": ("players.csv", csv_data, "text/csv")},
        )
        assert r.status_code == 200, r.text
        print("2. imported", r.json()["imported"], "players")

        cfg = (await c.get(f"{BASE}/api/draft/{token}/admin/config")).json()
        players = cfg["players"]
        p1 = next(p for p in players if p["name"] == "Player 1")
        p2 = next(p for p in players if p["name"] == "Player 2")

        # Keepers: Team 1 keeps P1 (round 1); Team 2 keeps P2 (round 2).
        for team, p, rnd in [(teams[0], p1, 1), (teams[1], p2, 2)]:
            r = await c.post(
                f"{BASE}/api/draft/{token}/admin/keepers",
                json={"team_id": team["id"], "player_id": p["id"], "round": rnd},
            )
            assert r.status_code == 200, r.text
        print("3. added 2 keepers")

        # Trade: Team 1's round-3 pick goes to Team 2 (Team 1 still owns round 1+2).
        round3_team1 = next(
            s
            for s in cfg["slots"]
            if s["round"] == 3 and s["original_team_id"] == teams[0]["id"]
        )
        r = await c.put(
            f"{BASE}/api/draft/{token}/admin/slots/{round3_team1['slot_id']}",
            json={"drafting_team_id": teams[1]["id"]},
        )
        assert r.status_code == 200, r.text
        print("4. traded Team 1 round-3 slot to Team 2")

        vr = (await c.post(f"{BASE}/api/draft/{token}/admin/validate")).json()
        assert vr["valid"], vr
        r = await c.post(f"{BASE}/api/draft/{token}/admin/start")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "LIVE"
        print("5. validated + started")

        # WS listener simulating a display client.
        async with websockets.connect(f"{WS}/api/draft/{token}/ws") as ws:
            first = json.loads(await ws.recv())["data"]
            assert first["status"] == "LIVE"
            print("6. ws initial state received")

            # Round 1 pick 1 = Team 1 (keeper-filled by P1) -> Team 2 is on the clock.
            assert first["board"][0]["status"] == "FILLED"
            assert first["board"][0]["player_name"] == "Player 1"
            cur = first["current_slot"]
            assert cur["drafting_team_id"] == teams[1]["id"], cur
            print("7. on the clock:", cur["drafting_team_id"], "(Team 2)")

            # Team 2 makes a pick via its team link.
            team2_tok = next(t["access_token"] for t in teams if t["id"] == teams[1]["id"])
            p3 = next(p for p in players if p["name"] == "Player 3")
            r = await c.post(
                f"{BASE}/api/draft/{token}/team/{team2_tok}/picks",
                json={"player_id": p3["id"]},
            )
            assert r.status_code == 200, r.text

            # WS should have received the broadcast with the new pick.
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))["data"]
            by_pick = {p["pick_number"]: p for p in msg["recent_picks"]}
            assert by_pick[2]["player_name"] == "Player 3"
            assert by_pick[2]["pick_type"] == "live"
            print("8. ws broadcast received pick:", by_pick[2]["player_name"])

            # Round 1 pick 3 (traded slot check): pick 3 = Team 2 (again, since round1
            # odd order 1,2,3,4 and Team 2 drafted at pick 2 -> next open is pick 3 = Team 3).
            # Verify a keeper slot shows correctly: round 2 pick for Team 2 is keeper.
            # After pick 2 (Team 2) and pick 3 (Team 3), pick 4 = Team 4.
            p4 = next(p for p in players if p["name"] == "Player 4")
            p5 = next(p for p in players if p["name"] == "Player 5")
            for pid in (p4, p5):
                r = await c.post(
                    f"{BASE}/api/draft/{token}/team/{team2_tok}/picks",
                    json={"player_id": pid["id"]},
                )
                # These should be rejected: only the team on the clock can pick.
                assert r.status_code == 400, r.text
            print("9. out-of-turn picks rejected (400)")

            # Commissioner override: pick for Team 3 at the current slot.
            cur = (await c.get(f"{BASE}/api/draft/{token}/display")).json()["current_slot"]
            p6 = next(p for p in players if p["name"] == "Player 6")
            r = await c.post(
                f"{BASE}/api/draft/{token}/admin/picks",
                json={"slot_id": cur["slot_id"], "team_id": cur["drafting_team_id"], "player_id": p6["id"]},
            )
            assert r.status_code == 200, r.text
            print("10. commissioner override pick recorded")

            # Undo the last live pick.
            r = await c.post(f"{BASE}/api/draft/{token}/admin/undo")
            assert r.status_code == 200, r.text
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))["data"]
            assert msg["board"][3]["status"] == "OPEN"
            print("11. undo restored slot to OPEN via broadcast")

            # Team 2 picks Player 3 on the clock again? No -- current slot reverted to
            # the override slot (Team 3 on the clock). Let the team pick.
            cur = (await c.get(f"{BASE}/api/draft/{token}/display")).json()["current_slot"]
            team3_tok = next(t["access_token"] for t in teams if t["id"] == teams[2]["id"])
            p7 = next(p for p in players if p["name"] == "Player 7")
            r = await c.post(
                f"{BASE}/api/draft/{token}/team/{team3_tok}/picks",
                json={"player_id": p7["id"]},
            )
            assert r.status_code == 200, r.text
            print("12. team pick after undo works")

            # Reach the traded slot: continue to end of round 1 (pick 4 Team 4),
            # then round 2 starts with Team 4 (snake). Team 2's round-2 slot is a keeper
            # so it's skipped. Verify the traded round-3 Team 2 slot eventually is on clock.
            # Team 4 picks.
            team4_tok = next(t["access_token"] for t in teams if t["id"] == teams[3]["id"])
            p8 = next(p for p in players if p["name"] == "Player 8")
            r = await c.post(
                f"{BASE}/api/draft/{token}/team/{team4_tok}/picks",
                json={"player_id": p8["id"]},
            )
            assert r.status_code == 200, r.text
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))["data"]
            # Round 2 pick 5 (snake, team 4), then round 2 pick 6 = Team 3.
            assert msg["current_slot"]["drafting_team_id"] == teams[2]["id"]
            print("13. round 2 snake order correct (Team 3 on the clock)")

        # Export results.
        exp = (await c.get(f"{BASE}/api/draft/{token}/admin/export")).json()
        assert len(exp["picks"]) >= 5
        print("14. export results:", len(exp["picks"]), "picks recorded")
        print("E2E PASS")


asyncio.run(main())