from __future__ import annotations

import re

_STARTER_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}

_SELECTED_POS_MAP = {
    "W/R/T": "",
    "W/T": "",
    "DST": "DST",
    "DEF": "DST",
    "DT": "DST",
    "K": "K",
    "PK": "K",
    "BN": "",
    "IR": "",
}


def normalize_name(name: str) -> str:
    """Normalize a player name for loose cross-source matching."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    name = re.sub(r"\b(sr|jr|iii|ii|iv)\.?$", "", name, flags=re.IGNORECASE)
    return name.strip().casefold()


def _pick_position(candidate_pos: str, draft_pos: str) -> str:
    if candidate_pos in _STARTER_POSITIONS:
        return candidate_pos
    if draft_pos in _STARTER_POSITIONS:
        return draft_pos
    return _SELECTED_POS_MAP.get(candidate_pos, candidate_pos or draft_pos)


def identify_candidates(
    *,
    app_teams: list[dict],
    draft_picks: dict[str, list[dict]],
    prior_draft_picks: dict[str, list[dict]],
    rosters: dict[str, list[dict]],
    transactions: list[dict],
    mappings: dict[int, dict],
    season: str,
) -> tuple[list[dict], list[str]]:
    """Compute keepable players and round costs for each app team.

    Rules:
      - A player drafted by their current team keeps that draft round as the
        cost basis (round - 2, or round - 1 when they were kept last season,
        floored at 1).
      - A player NOT drafted by their current team is only credited to another
        team's draft when a confirmed trade brought them to this team; the cost
        basis is the round from the original drafting team's draft.
      - A player drafted in round 1 or 2 of the previous season cannot be kept.
      - A player kept two consecutive seasons (kept in both the previous and
        the season before) is no longer keepable.
      - A player neither drafted by the team nor traded to them is assumed to
        have been dropped during the season and costs round 11.
    """
    warnings: list[str] = []
    draft_key_index = _draft_key_index(draft_picks, mappings)
    txs_by_key = _index_transactions(transactions)
    all_prior_picks = _index_all_picks(prior_draft_picks)

    results: list[dict] = []
    for team in app_teams:
        mapping = mappings.get(team["id"])
        if not mapping:
            warnings.append(f"{team['name']}: no team mapping configured")
            continue
        draft_name = (mapping.get("draft_name") or "").strip()
        yahoo_name = (mapping.get("yahoo_name") or "").strip()
        if not draft_name or draft_name not in draft_picks:
            warnings.append(f"{team['name']}: no previous-draft data for '{draft_name}'")
            continue
        roster = rosters.get(yahoo_name) or []
        if not roster:
            warnings.append(f"{team['name']}: no roster data for '{yahoo_name}'")

        draft_index = _index_picks(draft_picks[draft_name])
        prior_index = (
            _index_picks(prior_draft_picks[draft_name])
            if draft_name in prior_draft_picks
            else {}
        )

        team_results: list[dict] = []
        for player in roster:
            name = (player.get("name") or "").strip()
            if not name:
                continue
            nkey = normalize_name(name)
            player_id = str(player.get("player_id") or "")
            pick = draft_index.get(nkey)
            if pick is None:
                pick = _find_traded_pick(
                    player_id=player_id,
                    nkey=nkey,
                    draft_name=draft_name,
                    yahoo_name=yahoo_name,
                    txs_by_key=txs_by_key,
                    draft_picks=draft_picks,
                    draft_key_index=draft_key_index,
                )
                if pick is None:
                    warnings.append(
                        f"{team['name']}: {name} not drafted by this team and no "
                        f"trade found — assuming dropped; using round 11"
                    )
                    team_results.append(
                        _candidate(
                            name,
                            player,
                            None,
                            cost_round=11,
                            years_kept=0,
                            season=season,
                        )
                    )
                    continue
            if pick["round"] <= 2:
                warnings.append(
                    f"{team['name']}: {name} drafted in round {pick['round']} — cannot be kept"
                )
                continue
            prior = all_prior_picks.get(nkey, {}).get("pick") or prior_index.get(nkey)
            if prior and prior.get("is_keeper") and pick.get("is_keeper"):
                warnings.append(
                    f"{team['name']}: {name} kept 2 consecutive years — ineligible"
                )
                continue
            cost = max(1, pick["round"] - (1 if pick.get("is_keeper") else 2))
            years_kept = 1 if pick.get("is_keeper") else 0
            team_results.append(
                _candidate(
                    name,
                    player,
                    pick,
                    cost_round=cost,
                    years_kept=years_kept,
                    season=season,
                )
            )
        team_results.sort(key=lambda r: (r["cost_round"], r["player_name"]))
        results.append(
            {
                "team_id": team["id"],
                "team_name": team["name"],
                "candidates": team_results,
            }
        )
    return results, warnings


def _candidate(
    name: str,
    roster_player: dict,
    pick: dict | None,
    *,
    cost_round: int,
    years_kept: int,
    season: str,
) -> dict:
    position = _pick_position(
        roster_player.get("selected_position", ""),
        pick.get("position", "") if pick else "",
    )
    keepable_until = str(int(season) + (1 if years_kept == 0 else 0))
    return {
        "player_name": name,
        "position": position,
        "nfl_team": (roster_player.get("team") or "").upper(),
        "player_id_external": str(roster_player.get("player_id") or ""),
        "cost_round": cost_round,
        "years_kept": years_kept,
        "keepable_until_year": keepable_until,
    }


def _index_picks(picks: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for pick in picks:
        name = pick.get("name")
        if not name:
            continue
        key = normalize_name(name)
        if key not in index:
            index[key] = pick
    return index


def _index_all_picks(drafts: dict[str, list[dict]]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for team_name, picks in drafts.items():
        for key, pick in _index_picks(picks).items():
            index.setdefault(key, {"team": team_name, "pick": pick})
    return index


def _draft_key_index(
    draft_picks: dict[str, list[dict]], mappings: dict[int, dict]
) -> dict[str, str]:
    """Map any normalized team name (draft or Yahoo) to a draft data key."""
    index: dict[str, str] = {}
    for key in draft_picks:
        index.setdefault(normalize_name(key), key)
    for mapping in mappings.values():
        draft_name = (mapping.get("draft_name") or "").strip()
        yahoo_name = (mapping.get("yahoo_name") or "").strip()
        if draft_name:
            index.setdefault(normalize_name(draft_name), draft_name)
        if yahoo_name:
            index.setdefault(normalize_name(yahoo_name), draft_name or yahoo_name)
    return index


def _index_transactions(transactions: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for tx in transactions:
        player_id = str(tx.get("player_id") or "")
        name = normalize_name(tx.get("player") or "")
        if player_id:
            index.setdefault(player_id, []).append(tx)
        if name:
            index.setdefault(name, []).append(tx)
    return index


def _picks_for_team(
    team_name: str,
    draft_picks: dict[str, list[dict]],
    draft_key_index: dict[str, str],
) -> list[dict] | None:
    draft_key = draft_key_index.get(normalize_name(team_name))
    if draft_key:
        return draft_picks.get(draft_key)
    return draft_picks.get(team_name) or draft_picks.get(normalize_name(team_name))


def _find_traded_pick(
    *,
    player_id: str,
    nkey: str,
    draft_name: str,
    yahoo_name: str,
    txs_by_key: dict[str, list[dict]],
    draft_picks: dict[str, list[dict]],
    draft_key_index: dict[str, str],
) -> dict | None:
    """Round a traded player was originally drafted at.

    Finds the trade that brought the player to the current team, then traces
    the trade chain back to the team that originally drafted them and returns
    that pick. Returns None when the player was never traded to this team or no
    draft pick can be traced for the original team.
    """
    txs = (txs_by_key.get(player_id) if player_id else []) or txs_by_key.get(nkey) or []
    if not txs:
        return None
    current_names = {normalize_name(n) for n in (draft_name, yahoo_name) if n}
    inbound = next(
        (
            tx
            for tx in txs
            if normalize_name(tx.get("to_team") or "") in current_names
        ),
        None,
    )
    if inbound is None:
        return None
    seen: set[str] = set()
    current = inbound.get("from_team") or ""
    while current and normalize_name(current) not in seen:
        seen.add(normalize_name(current))
        picks = _picks_for_team(current, draft_picks, draft_key_index)
        if picks:
            pick = _index_picks(picks).get(nkey)
            if pick is not None:
                return pick
        current = next(
            (
                tx.get("from_team") or ""
                for tx in txs
                if normalize_name(tx.get("to_team") or "") == normalize_name(current)
            ),
            "",
        )
    return None
