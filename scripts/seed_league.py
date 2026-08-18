#!/usr/bin/env python3
"""Create a draft league on the deployed backend and print shareable links.

Usage:
    python scripts/seed_league.py \
        --url https://draftday-backend.onrender.com \
        --frontend https://draftday.vercel.app \
        --name "League 2026" --season 2026 --num-rounds 15 \
        --teams "Team A,Team B,Team C"
"""

import argparse
import json
import sys
from urllib.parse import quote

import requests


def parse_teams(raw: str) -> list[dict]:
    teams = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, manager = part.partition(":")
        teams.append(
            {
                "name": name.strip(),
                "manager_name": manager.strip(),
            }
        )
    return teams


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a draft league and print shareable links."
    )
    parser.add_argument("--url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument(
        "--frontend",
        default="http://localhost:3000",
        help="Frontend base URL for printed links",
    )
    parser.add_argument("--name", required=True, help="League name")
    parser.add_argument("--season", default="2026", help="Season year")
    parser.add_argument("--num-teams", type=int, required=True, help="Number of teams")
    parser.add_argument("--num-rounds", type=int, default=15, help="Number of draft rounds")
    parser.add_argument(
        "--teams",
        required=True,
        help='Comma-separated team names; use "Name:Manager" for managers',
    )
    args = parser.parse_args()

    teams = parse_teams(args.teams)
    if len(teams) != args.num_teams:
        print(
            f"error: --num-teams ({args.num_teams}) does not match the "
            f"number of teams provided ({len(teams)})",
            file=sys.stderr,
        )
        return 2

    payload = {
        "name": args.name,
        "season": args.season,
        "num_teams": args.num_teams,
        "num_rounds": args.num_rounds,
        "teams": teams,
    }
    url = args.url.rstrip("/") + "/api/leagues"

    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as exc:
        print(f"error: could not reach {url}: {exc}", file=sys.stderr)
        return 2

    if resp.status_code != 200:
        detail = resp.text[:500]
        print(f"error: {resp.status_code}: {detail}", file=sys.stderr)
        return 2

    data = resp.json()
    token = data["access_token"]
    frontend = args.frontend.rstrip("/")

    print()
    print("=" * 64)
    print(f"League created: {data['name']} ({data['season']})")
    print("=" * 64)
    print(f"Admin:    {frontend}/draft/{token}/admin")
    print(f"Display:  {frontend}/draft/{token}/display")
    print()
    for team in sorted(data["teams"], key=lambda t: t["draft_position"]):
        print(
            f"Team {team['draft_position']:>2}: {team['name']:<30} "
            f"{frontend}/draft/{token}/team/{team['access_token']}"
        )
    print()
    print("Share the Display or per-team links with your league.")
    return 0


if __name__ == "__main__":
    sys.exit(main())