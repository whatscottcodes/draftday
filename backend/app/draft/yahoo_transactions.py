from __future__ import annotations

import re

from bs4 import BeautifulSoup


_PLAYER_ID_RE = re.compile(r"/players/(\d+)")


def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def _get_date(timestamp: str) -> str:
    timestamp = _clean(timestamp)
    match = re.match(
        r"(.+?),\s+\d{1,2}:\d{2}\s*(?:am|pm)?",
        timestamp,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else timestamp


def _is_trade_start(row) -> bool:
    return row.select_one(".F-trade") is not None


def _get_receiving_team(row) -> str:
    cells = row.find_all("td")
    if len(cells) < 3:
        return ""
    for link in cells[-1].find_all("a", href=True):
        if "/f1/" in link.get("href", ""):
            team_name = _clean(link.get_text(" ", strip=True))
            if team_name:
                return team_name
    return ""


def _get_timestamp(row) -> str:
    timestamp = row.select_one(".F-timestamp")
    return _clean(timestamp.get_text(" ", strip=True)) if timestamp else ""


def _get_players(row) -> list[dict]:
    players: list[dict] = []
    for link in row.select('a[href*="/nfl/players/"]'):
        name = _clean(link.get_text(" ", strip=True))
        if not name:
            continue
        id_match = _PLAYER_ID_RE.search(link.get("href", ""))
        players.append(
            {
                "player": name,
                "player_id": id_match.group(1) if id_match else "",
            }
        )
    return players


def _find_trade_blocks(table) -> list[list]:
    blocks: list[list] = []
    current_block: list = []
    for row in table.select("tbody > tr"):
        if _is_trade_start(row):
            if current_block:
                blocks.append(current_block)
            current_block = [row]
        elif current_block:
            current_block.append(row)
    if current_block:
        blocks.append(current_block)
    return blocks


def _parse_trade_block(block: list) -> list[dict]:
    sides: list[dict] = []
    for row in block:
        players = _get_players(row)
        to_team = _get_receiving_team(row)
        timestamp = _get_timestamp(row)
        if not players or not to_team:
            continue
        sides.append(
            {
                "players": players,
                "to_team": to_team,
                "timestamp": timestamp,
            }
        )
    if len(sides) < 2:
        return []

    side_a = sides[0]
    side_b = sides[1]
    date = _get_date(side_a["timestamp"] or side_b["timestamp"])

    trades: list[dict] = []
    for player in side_a["players"]:
        trades.append(
            {
                "date": date,
                **player,
                "from_team": side_b["to_team"],
                "to_team": side_a["to_team"],
            }
        )
    for player in side_b["players"]:
        trades.append(
            {
                "date": date,
                **player,
                "from_team": side_a["to_team"],
                "to_team": side_b["to_team"],
            }
        )
    return trades


def parse_transactions(html: str) -> list[dict]:
    """Parse completed player trades from a Yahoo Transactions page."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.Tst-transaction-table")
    if table is None:
        raise ValueError(
            "Could not find the Yahoo transaction table. Save the league "
            "Transactions page as HTML and upload that file."
        )

    trades: list[dict] = []
    for block in _find_trade_blocks(table):
        trades.extend(_parse_trade_block(block))
    return trades
