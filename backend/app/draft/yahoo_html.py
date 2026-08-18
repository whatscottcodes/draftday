from __future__ import annotations

import re

from bs4 import BeautifulSoup


_PLAYER_ID_RE = re.compile(r"/players/(\d+)")


def clean_player_name(text: str) -> str:
    """Remove Yahoo UI/status text and return only the player name."""
    text = " ".join(text.split())
    for pattern in (
        r"\s+Video\b.*$",
        r"\s+Forecast\b.*$",
        r"\s+Final\b.*$",
        r"\s+Projected\b.*$",
        r"\s+Injury\b.*$",
        r"\s+News\b.*$",
        r"\s+Game Log\b.*$",
        r"\s+Player Note\b.*$",
    ):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_rosters(html: str) -> tuple[dict[str, list[dict]], int | None]:
    """Parse a Yahoo Starting Rosters page into keeper roster records."""
    soup = BeautifulSoup(html, "html.parser")
    team_tables = soup.select('table[id^="Tst-team-"]')
    if not team_tables:
        raise ValueError(
            "No Yahoo roster tables found. Save the Yahoo Starting Rosters page "
            "with the Team tab selected and upload that HTML file."
        )

    rosters: dict[str, list[dict]] = {}
    for table in team_tables:
        team_link = table.find_previous("a", href=True)
        team_name = team_link.get_text(" ", strip=True) if team_link else ""
        if not team_name:
            raise ValueError(f"Could not determine team name for {table.get('id')}")

        players: list[dict] = []
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            position = cells[0].get_text(" ", strip=True)
            player_cell = cells[1]
            player_link = player_cell.select_one("a.name")
            if player_link is None:
                player_link = player_cell.find("a", href=_PLAYER_ID_RE)
            player_name = clean_player_name(
                player_link.get_text(" ", strip=True)
                if player_link
                else player_cell.get_text(" ", strip=True)
            )
            if not player_name:
                continue

            player_id = ""
            if player_link:
                match = _PLAYER_ID_RE.search(player_link.get("href", ""))
                if match:
                    player_id = match.group(1)
            players.append(
                {
                    "name": player_name,
                    "player_id": player_id,
                    "selected_position": position,
                    "team": "",
                    "was_added": False,
                }
            )
        if players:
            rosters[team_name] = players

    if not rosters:
        raise ValueError("Yahoo roster tables were found, but they contained no players")

    week = None
    week_label = soup.select_one(".flyout-title")
    if week_label:
        match = re.search(r"\bWeek\s+(\d+)\b", week_label.get_text(" ", strip=True))
        if match:
            week = int(match.group(1))
    return rosters, week
