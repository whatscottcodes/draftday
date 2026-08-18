from __future__ import annotations

import html as html_lib
import json
import re

_YEAR_RE = re.compile(r"^\d{4}$")


def _extract_js_json(text: str, variable_name: str) -> dict | list:
    pattern = rf"{re.escape(variable_name)}\s*:\s*'(.*?)'\s*(?:,|;|\n)"
    match = re.search(pattern, text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Could not find '{variable_name}' in the HTML file.")
    try:
        return json.loads(html_lib.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Found '{variable_name}', but could not parse its JSON."
        ) from exc


def parse_draft(html: str) -> tuple[str, str, list[dict]]:
    """Parse a saved ClickyDraft page into keeper draft records."""
    league = _extract_js_json(html, "requestedLgInstJSON")
    raw_picks = _extract_js_json(html, "requestedPicksJSON")
    if not isinstance(league, dict) or not isinstance(raw_picks, list):
        raise ValueError("ClickyDraft league or pick data has an unexpected format")

    year = str(league.get("year") or "").strip()
    if not _YEAR_RE.match(year):
        raise ValueError("Could not determine a four-digit draft year from the HTML")

    teams = {
        team.get("id"): (team.get("teamName") or "").strip()
        for team in league.get("fantasyTeams", [])
    }
    records: list[dict] = []
    for pick in raw_picks:
        try:
            round_num = int(pick["round"])
        except (KeyError, TypeError, ValueError):
            continue
        player = pick.get("draftablePlayer") or {}
        name = " ".join(
            part
            for part in (
                (player.get("firstName") or "").strip(),
                (player.get("lastName") or "").strip(),
            )
            if part
        )
        team_id = pick.get("fantasyTeamId")
        team = teams.get(team_id) or f"Unknown Team {team_id}"
        if not name or not team:
            continue
        positions = player.get("positions") or []
        records.append(
            {
                "team": team,
                "round": round_num,
                "position": positions[0] if positions else "",
                "nfl_team": (player.get("teamAbbr") or "").strip(),
                "name": name,
                "is_keeper": bool(pick.get("keeper", False)),
            }
        )
    if not records:
        raise ValueError("No draft picks were found in the ClickyDraft HTML")
    return year, str(league.get("displayName") or "").strip(), records
