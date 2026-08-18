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

    Rules (mirroring the keepers/ scripts):
      - A player missing from their current team's draft list is searched for
        across the full draft board and treated as traded when found.
      - A transaction-confirmed trade also uses the original pick from the
        previous season's draft, regardless of the current fantasy team.
      - A player drafted in round 1 or 2 of the previous season cannot be kept.
      - A free agent or player with no previous-season draft pick costs round 11.
      - Draft-based cost is round-1 when they were kept that season (the '(K)'
        marker), else round-2, floored at 1.
      - A player kept two consecutive seasons (kept in both the previous and
        the season before) is no longer keepable.
    """
    warnings: list[str] = []
    traded_names = {
        normalize_name(transaction.get("player", ""))
        for transaction in transactions
        if transaction.get("player")
    }
    traded_ids = {
        str(transaction.get("player_id"))
        for transaction in transactions
        if transaction.get("player_id")
    }
    all_draft_picks = _index_all_picks(draft_picks)
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
            transaction_trade = player_id in traded_ids or nkey in traded_names
            team_pick = draft_index.get(nkey)
            drafted = all_draft_picks.get(nkey) if team_pick is None else None
            inferred_trade = drafted is not None
            was_traded = transaction_trade or inferred_trade
            pick = team_pick or (drafted["pick"] if drafted else None)
            if not was_traded and player.get("was_added"):
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
            if pick is None:
                reason = "traded player has no drafting team" if was_traded else "not found in previous draft"
                warnings.append(f"{team['name']}: {name} {reason}; using round 11")
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
