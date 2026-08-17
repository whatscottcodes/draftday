from __future__ import annotations

import csv
import io
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Keeper, KeeperCandidate, League, Player, Team

MAX_KEEPERS_PER_TEAM = 3

_STARTER_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}
_SELECTED_POS_MAP = {
    "W/R/T": "",
    "W/T": "",
    "DST": "DST",
    "DEF": "DST",
    "DT": "DST",
    "K": "K",
    "PK": "K",
}


def normalize_name(name: str) -> str:
    """Normalize a team or player name for loose matching."""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def clean_imported_player(value: str) -> tuple[str, str, str]:
    """Extract (position, nfl_team, name) from keeper rows like
    'RB NYJ 9 Breece Hall'."""
    match = re.match(
        r"^(QB|RB|WR|TE|DEF|DST|PK|K)\s+([A-Z]{2,3})\s+\d*\s*(.+)$",
        (value or "").strip(),
    )
    if not match:
        return "", "", (value or "").strip()
    pos = _SELECTED_POS_MAP.get(match.group(1), match.group(1))
    return pos, match.group(2).upper(), match.group(3).strip()


def _pick_position(candidate_pos: str, player: Player) -> str:
    if candidate_pos in _STARTER_POSITIONS:
        return candidate_pos
    if player.position in _STARTER_POSITIONS:
        return player.position
    return _SELECTED_POS_MAP.get(candidate_pos, candidate_pos or player.position)


def _find_or_create_player(
    db: Session, league: League, player_id_ext: str, name: str, position: str
) -> Player:
    existing = db.scalar(
        select(Player).where(Player.league_id == league.id, Player.name == name)
    )
    if existing is not None:
        if position and not existing.position:
            existing.position = position
        return existing
    player = Player(
        league_id=league.id,
        player_id=player_id_ext or name,
        name=name,
        position=position,
    )
    db.add(player)
    db.flush()
    return player


def import_candidate_rows(
    db: Session, league: League, rows: list[dict], source: str
) -> dict:
    """Upsert keeper candidates from parsed rows.

    Each row: team_name, player_name, position, nfl_team, player_id_external,
    cost_round, years_kept (optional), keepable_until_year (optional).
    Returns a stats dict for reporting.
    """
    teams_by_name: dict[str, Team] = {}
    for team in league.teams:
        teams_by_name.setdefault(normalize_name(team.name), team)

    stats = {
        "created": 0,
        "updated": 0,
        "skipped_no_cost": 0,
        "unmatched_teams": [],
        "unmatched_players": [],
    }
    for row in rows:
        team = teams_by_name.get(normalize_name(row["team_name"]))
        if team is None:
            stats["unmatched_teams"].append(row["team_name"])
            continue
        cost = row.get("cost_round")
        if cost is None:
            stats["skipped_no_cost"] += 1
            continue
        player = _find_or_create_player(
            db,
            league,
            row.get("player_id_external", ""),
            row["player_name"],
            row.get("position", ""),
        )
        position = _pick_position(row.get("position", ""), player)
        keepable_until_year = row.get("keepable_until_year", "")
        years_kept = row.get("years_kept", 0)
        if not keepable_until_year and league.season:
            keepable_until_year = str(
                int(league.season) + (1 if years_kept == 0 else 0)
            )
        existing = db.scalar(
            select(KeeperCandidate).where(
                KeeperCandidate.league_id == league.id,
                KeeperCandidate.team_id == team.id,
                KeeperCandidate.player_id == player.id,
            )
        )
        if existing is None:
            db.add(
                KeeperCandidate(
                    league_id=league.id,
                    team_id=team.id,
                    player_id=player.id,
                    player_name=player.name,
                    position=position,
                    cost_round=int(cost),
                    years_kept=years_kept,
                    keepable_until_year=keepable_until_year,
                    source=source,
                )
            )
            stats["created"] += 1
        else:
            existing.cost_round = int(cost)
            existing.position = position
            existing.player_name = player.name
            if years_kept:
                existing.years_kept = years_kept
            if keepable_until_year:
                existing.keepable_until_year = keepable_until_year
            existing.source = source
            stats["updated"] += 1
    db.flush()
    return stats


def _clean_int(value) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_candidate_csv(
    raw: str, default_team_name: str = ""
) -> tuple[list[dict], list[str]]:
    """Parse a keeper-candidate CSV into import rows.

    Supports the keepers_2024.csv format
    (Team,Player,Keeper_2024,...,2025_Cost) as well as the per-team roster
    format (name,player_id,...,selected_position,was_added,2025_Cost).
    """
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        return [], ["Empty CSV"]
    fields = {f.strip() for f in reader.fieldnames}
    warnings: list[str] = []
    rows: list[dict] = []

    if "Team" in fields and "Player" in fields:
        for i, rec in enumerate(reader, start=2):
            pos, nfl_team, name = clean_imported_player(rec.get("Player", ""))
            cost = _clean_int(rec.get("2025_Cost"))
            if not name:
                continue
            keeper_2024 = str(rec.get("Keeper_2024", "")).strip().lower() in (
                "true",
                "1",
                "yes",
            )
            rows.append(
                {
                    "team_name": rec.get("Team", "").strip(),
                    "player_name": name,
                    "position": pos,
                    "nfl_team": nfl_team,
                    "player_id_external": "",
                    "cost_round": cost,
                    "years_kept": 1 if keeper_2024 else 0,
                }
            )
            if cost is None:
                warnings.append(f"Row {i}: no keep cost for {name} — skipped")
    elif "name" in fields:
        for i, rec in enumerate(reader, start=2):
            name = (rec.get("name") or "").strip()
            if not name:
                continue
            cost = _clean_int(rec.get("2025_Cost"))
            was_added = str(rec.get("was_added", "")).strip().lower() in (
                "true",
                "1",
                "yes",
            )
            if cost is None and was_added:
                cost = 11
            rows.append(
                {
                    "team_name": default_team_name,
                    "player_name": name,
                    "position": _SELECTED_POS_MAP.get(
                        (rec.get("selected_position") or "").strip(),
                        (rec.get("selected_position") or "").strip(),
                    ),
                    "nfl_team": (rec.get("team") or "").strip().upper(),
                    "player_id_external": (rec.get("player_id") or "").strip(),
                    "cost_round": cost,
                    "years_kept": 0,
                }
            )
            if cost is None:
                warnings.append(f"Row {i}: no keep cost for {name} — skipped")
    else:
        return [], ["Unrecognized CSV: expected Team/Player or name columns"]

    return rows, warnings


def clear_candidates(db: Session, league: League) -> int:
    count = len(league.keeper_candidates)
    for c in list(league.keeper_candidates):
        db.delete(c)
    db.flush()
    return count


def team_keeper_count(db: Session, league: League, team_id: int) -> int:
    return len(
        db.scalars(
            select(Keeper).where(
                Keeper.league_id == league.id, Keeper.team_id == team_id
            )
        ).all()
    )


def candidate_dict(kc: KeeperCandidate, selected: bool) -> dict:
    return {
        "candidate_id": kc.id,
        "player_id": kc.player_id,
        "player_name": kc.player_name,
        "position": kc.position,
        "nfl_team": kc.player.nfl_team if kc.player else "",
        "cost_round": kc.cost_round,
        "years_kept": kc.years_kept,
        "keepable_until_year": kc.keepable_until_year,
        "selected": selected,
    }