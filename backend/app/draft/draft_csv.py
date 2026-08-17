from __future__ import annotations

import csv
import io

_SELECTED_POS_MAP = {
    "W/R/T": "",
    "W/T": "",
    "DST": "DST",
    "DEF": "DST",
    "DT": "DST",
    "K": "K",
    "PK": "K",
}


def parse_draft_csv(raw: str) -> list[dict]:
    """Parse a clickydraft export (e.g. '2024-Draft - Sheet1.csv').

    The file is a matrix: the first column header is 'ROUND', the remaining
    columns are team names, and each cell holds a player encoded over several
    lines as::

        POS
        NFL_TEAM
        ROUND
        FIRST
        LAST[(K)]

    Players kept the previous season carry a '(K)' suffix on the last line.
    Returns a list of picks with keys team, round, position, nfl_team, name,
    is_keeper.
    """
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    if not headers or headers[0].upper() != "ROUND":
        # Tolerate a missing ROUND header by treating the first column as round.
        if headers:
            headers = ["ROUND"] + [h for h in headers if h != "ROUND"]
    picks: list[dict] = []
    for row in rows[1:]:
        if not row:
            continue
        round_num = _clean_int(row[0])
        if round_num is None:
            continue
        for col_idx in range(1, len(headers)):
            if col_idx >= len(row):
                continue
            team = headers[col_idx]
            parsed = _parse_cell(row[col_idx])
            if parsed is None:
                continue
            picks.append(
                {
                    "team": team,
                    "round": round_num,
                    "position": parsed[0],
                    "nfl_team": parsed[1],
                    "name": parsed[2],
                    "is_keeper": parsed[3],
                }
            )
    return picks


def parse_roster_csv(raw: str) -> list[dict]:
    """Parse a per-team roster CSV into snapshot rows.

    Expected columns (Yahoo roster export + script-added flags):
    name,player_id,player_key,position_type,team,selected_position,was_added[,2025_Cost]
    """
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        return []
    rows: list[dict] = []
    for rec in reader:
        name = (rec.get("name") or "").strip()
        if not name:
            continue
        was_added = str(rec.get("was_added", "")).strip().lower() in (
            "true",
            "1",
            "yes",
        )
        selected = _SELECTED_POS_MAP.get(
            (rec.get("selected_position") or "").strip(),
            (rec.get("selected_position") or "").strip(),
        )
        rows.append(
            {
                "name": name,
                "player_id": (rec.get("player_id") or "").strip(),
                "selected_position": selected,
                "team": (rec.get("team") or "").strip().upper(),
                "was_added": was_added,
            }
        )
    return rows


def _clean_int(value) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_cell(raw: str) -> tuple[str, str, str, bool] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    is_keeper = "(K)" in raw
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None
    position = _SELECTED_POS_MAP.get(lines[0], lines[0])
    nfl_team = lines[1] if len(lines) > 1 else ""
    name_lines = lines[3:]
    name = " ".join(name_lines).replace("(K)", "").strip()
    if not name and len(lines) >= 2:
        # e.g. 'DEF\\nBAL\\n7\\n \\nBAL DEF' -> take the last non-empty line
        name = lines[-1].replace("(K)", "").strip()
    return position, nfl_team, name, is_keeper