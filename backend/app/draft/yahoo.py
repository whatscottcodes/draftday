from __future__ import annotations

import time

import requests

_YAHOO_REQUEST_AUTH = "https://api.login.yahoo.com/oauth2/request_auth"
_YAHOO_GET_TOKEN = "https://api.login.yahoo.com/oauth2/get_token"


class YahooError(Exception):
    pass


def authorization_url(consumer_key: str) -> str:
    return (
        f"{_YAHOO_REQUEST_AUTH}?client_id={consumer_key}"
        "&redirect_uri=oob&response_type=code&language=en-us"
    )


def _token_request(consumer_key: str, consumer_secret: str, data: dict) -> dict:
    payload = dict(data)
    payload.update(
        {"client_id": consumer_key, "client_secret": consumer_secret}
    )
    resp = requests.post(_YAHOO_GET_TOKEN, data=payload, timeout=60)
    if resp.status_code != 200:
        raise YahooError(f"Yahoo token request failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def exchange_code(
    consumer_key: str, consumer_secret: str, code: str, guid: str = ""
) -> dict:
    body = _token_request(
        consumer_key,
        consumer_secret,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": "oob"},
    )
    body.setdefault("xoauth_yahoo_guid", guid)
    return body


def refresh_access_token(
    consumer_key: str, consumer_secret: str, refresh_token: str
) -> dict:
    return _token_request(
        consumer_key,
        consumer_secret,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": "oob",
        },
    )


def build_token_json(
    consumer_key: str,
    consumer_secret: str,
    token_body: dict,
    refresh_token: str | None = None,
    guid: str = "",
    token_time: float | None = None,
) -> dict:
    """Normalize a Yahoo /get_token response into the yfpy access-token shape."""
    return {
        "access_token": token_body.get("access_token", ""),
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret,
        "guid": guid or token_body.get("xoauth_yahoo_guid", ""),
        "refresh_token": refresh_token
        or token_body.get("refresh_token", ""),
        "token_time": token_time or time.time(),
        "token_type": token_body.get("token_type", "bearer"),
    }


def _attr(obj, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _player_row(player, was_added: bool = False) -> dict:
    name_obj = _attr(player, "name", {}) or {}
    name = _attr(name_obj, "full", None) or name_obj if not isinstance(
        name_obj, str
    ) else name_obj
    if isinstance(name, dict):
        name = _attr(name, "full", "") or ""
    if not isinstance(name, str):
        name = str(name)
    sel_obj = _attr(player, "selected_position", None)
    sel_pos = _attr(sel_obj, "position", "") if sel_obj else ""
    return {
        "name": (name or "").strip(),
        "player_id": str(_attr(player, "player_id", "") or ""),
        "selected_position": sel_pos or "",
        "team": (_attr(player, "editorial_team_abbr", "") or "").upper(),
        "was_added": was_added,
    }


def fetch_snapshot(
    *,
    league_id: str,
    game_code: str,
    game_id: int,
    consumer_key: str,
    consumer_secret: str,
    token_json: dict,
    week: int | None = None,
) -> dict:
    """Fetch per-team rosters and mark waiver-adds from league transactions.

    Returns {yahoo_team_name: [roster rows]} where each row is
    {name, player_id, selected_position, team, was_added}.
    """
    try:
        from yfpy.query import YahooFantasySportsQuery
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise YahooError("yfpy is not installed in the backend environment") from exc

    query = YahooFantasySportsQuery(
        league_id=str(league_id),
        game_code=game_code,
        game_id=game_id,
        yahoo_consumer_key=consumer_key,
        yahoo_consumer_secret=consumer_secret,
        yahoo_access_token_json=token_json,
        env_var_fallback=False,
    )

    teams = query.get_league_teams() or []
    rosters: dict[str, list[dict]] = {}
    team_id_by_key: dict[str, str] = {}
    for team in teams:
        team_key = str(_attr(team, "team_key", ""))
        team_name = str(_attr(team, "name", "")).strip()
        team_id = str(_attr(team, "team_id", ""))
        if not team_name:
            continue
        team_id_by_key[team_key] = team_name
        try:
            if week is not None:
                roster = query.get_team_roster_by_week(team_id, week)
            else:
                roster = query.get_team_roster(team_id)
        except Exception as exc:  # pragma: no cover - network errors
            raise YahooError(f"Failed to fetch roster for {team_name}: {exc}") from exc
        rows = [_player_row(p) for p in (getattr(roster, "players", None) or [])]
        rosters[team_name] = rows

    added_ids: set[str] = set()
    try:
        transactions = query.get_league_transactions() or []
    except Exception:
        transactions = []
    for tx in transactions:
        if _attr(tx, "type", "") not in ("add", "add/drop"):
            continue
        players = _attr(tx, "players", None) or []
        for entry in players:
            pid = _attr(entry, "player_id", None)
            if pid is None:
                inner = _attr(entry, "player", None)
                if inner:
                    pid = _attr(inner, "player_id", None)
            if pid is not None:
                added_ids.add(str(pid))

    if added_ids:
        for rows in rosters.values():
            for row in rows:
                if row["player_id"] in added_ids:
                    row["was_added"] = True

    return rosters