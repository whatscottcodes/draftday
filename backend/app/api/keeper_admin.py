from __future__ import annotations

import asyncio
import csv
import io
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..draft import draft_csv, engine, keeper_identify, state as state_builder
from ..draft import yahoo as yahoo_mod
from ..draft.engine import DraftError
from ..draft.keepers import clear_candidates, import_candidate_rows
from ..draft.yahoo import YahooError
from ..models import (
    Keeper,
    KeeperCandidate,
    League,
    LeagueStatus,
    Pick,
    PickType,
    Team,
    YahooConfig,
)
from ..schemas import (
    KeeperMappingsIn,
    KeeperSaveIn,
    UseDraftIn,
    YahooCodeIn,
    YahooConfigIn,
)
from ..ws import manager

router = APIRouter(prefix="/api")

_YEAR_RE = re.compile(r"^\d{4}$")


def _get_league(db: Session, token: str) -> League:
    league = engine.get_league_by_token(db, token)
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    return league


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


def _get_workspace(league: League) -> dict:
    ws = league.keeper_workspace
    return dict(ws) if isinstance(ws, dict) else {}


def _save_workspace(db: Session, league: League, ws: dict) -> None:
    league.keeper_workspace = ws
    _commit(db)


def _get_yahoo_config(db: Session, league: League) -> YahooConfig | None:
    return db.scalar(
        select(YahooConfig).where(YahooConfig.league_id == league.id)
    )


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    return value[:6] + "…" if len(value) > 6 else "…"


def _masked_yahoo(config: YahooConfig | None) -> dict:
    if config is None:
        return {
            "configured": False,
            "league_id_external": "",
            "game_id": None,
            "season_id": "",
            "week": None,
            "consumer_key": "",
            "has_token": False,
        }
    token = config.access_token_json or {}
    return {
        "configured": True,
        "league_id_external": config.league_id_external,
        "game_id": config.game_id,
        "season_id": config.season_id,
        "week": config.week,
        "consumer_key": _mask_secret(config.consumer_key),
        "has_token": bool(token.get("access_token")),
    }


def _normalize(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip()).casefold()


def _suggest_mappings(app_teams: list[dict], draft_cols: list[str], yahoo_teams: list[str]) -> list[dict]:
    suggestions: list[dict] = []
    for team in app_teams:
        app_key = _normalize(team["name"])
        draft_name = next(
            (c for c in draft_cols if _normalize(c) == app_key), ""
        )
        yahoo_name = next(
            (t for t in yahoo_teams if _normalize(t) == app_key), ""
        )
        suggestions.append(
            {
                "team_id": team["id"],
                "team_name": team["name"],
                "draft_name": draft_name,
                "yahoo_name": yahoo_name,
            }
        )
    return suggestions


def _mappings_int(ws: dict) -> dict[int, dict]:
    raw = ws.get("mappings", {})
    result: dict[int, dict] = {}
    for key, value in raw.items():
        result[int(key)] = dict(value)
    return result


def _build_preview(ws: dict, app_teams: list[dict], season: str):
    drafts = ws.get("drafts", {})
    previous_year = ws.get("previous_year", "")
    prior_year = ws.get("prior_year", "")
    draft_picks = drafts.get(previous_year, {})
    prior_picks = drafts.get(prior_year, {})
    rosters = ws.get("rosters", {})
    mappings = _mappings_int(ws)
    preview, warnings = keeper_identify.identify_candidates(
        app_teams=app_teams,
        draft_picks=draft_picks,
        prior_draft_picks=prior_picks,
        rosters=rosters,
        mappings=mappings,
        season=season,
    )
    return preview, warnings


def _rows_from_preview(teams: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for team in teams:
        for cand in team.get("candidates", []):
            rows.append(
                {
                    "team_name": team["team_name"],
                    "player_name": cand["player_name"],
                    "position": cand.get("position", ""),
                    "nfl_team": cand.get("nfl_team", ""),
                    "player_id_external": cand.get("player_id_external", ""),
                    "cost_round": cand["cost_round"],
                    "years_kept": cand.get("years_kept", 0),
                    "keepable_until_year": cand.get("keepable_until_year", ""),
                }
            )
    return rows


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]", "", name).strip() or "team"


# ---------------------------------------------------------------- setup


@router.get("/draft/{token}/admin/keepers/setup")
def keeper_setup(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    ws = _get_workspace(league)
    teams = sorted(league.teams, key=lambda t: t.draft_position)
    app_teams = [
        {"id": t.id, "name": t.name, "manager_name": t.manager_name}
        for t in teams
    ]
    draft_cols = ws.get("draft_team_cols", [])
    yahoo_teams = ws.get("yahoo_teams", [])
    previous_year = ws.get("previous_year", "")
    prior_year = ws.get("prior_year", "")
    drafts = ws.get("drafts", {})
    preview = ws.get("preview", [])
    saved_at = ws.get("saved_at")

    completed = db.scalars(
        select(League)
        .where(League.status == LeagueStatus.COMPLETED, League.id != league.id)
        .order_by(League.created_at.desc())
    )
    completed_list = list(completed)
    pick_counts = dict(
        db.execute(
            select(Pick.league_id, func.count(Pick.id))
            .where(Pick.league_id.in_([l.id for l in completed_list]))
            .group_by(Pick.league_id)
        ).all()
    )

    return {
        "league": {
            "id": league.id,
            "name": league.name,
            "season": league.season,
            "status": league.status,
            "editable": league.status in (LeagueStatus.SETUP, LeagueStatus.READY),
        },
        "teams": app_teams,
        "draft": {
            "previous_year": previous_year,
            "prior_year": prior_year,
            "draft_teams": draft_cols,
            "has_draft": bool(draft_cols),
            "draft_counts": {
                year: {
                    col: len(picks) for col, picks in data.items()
                }
                for year, data in drafts.items()
            },
        },
        "mappings": [
            {
                "team_id": int(team_id),
                "draft_name": m.get("draft_name", ""),
                "yahoo_name": m.get("yahoo_name", ""),
            }
            for team_id, m in sorted(_mappings_int(ws).items())
        ],
        "suggested_mappings": _suggest_mappings(app_teams, draft_cols, yahoo_teams),
        "rosters": {
            "has_rosters": bool(ws.get("rosters")),
            "teams": yahoo_teams,
            "week": ws.get("roster_week"),
            "player_count": sum(
                len(rows) for rows in ws.get("rosters", {}).values()
            ),
        },
        "preview": {
            "teams": preview,
            "warnings": ws.get("preview_warnings", []),
            "saved_at": saved_at,
        },
        "yahoo": _masked_yahoo(_get_yahoo_config(db, league)),
        "previous_drafts": [
            {
                "id": l.id,
                "name": l.name,
                "season": l.season,
                "picks": pick_counts.get(l.id, 0),
            }
            for l in completed_list
        ],
    }


# ---------------------------------------------------------------- draft csv


@router.post("/draft/{token}/admin/keepers/draft-csv")
async def upload_draft_csv(
    token: str,
    file: UploadFile = File(...),
    year: str = Form(...),
    role: str = Form("previous"),
    db: Session = Depends(get_db),
):
    league = _get_league(db, token)
    if not _YEAR_RE.match(year):
        raise HTTPException(status_code=400, detail="year must be like 2024")
    if role not in ("previous", "prior"):
        raise HTTPException(status_code=400, detail="role must be 'previous' or 'prior'")
    raw = (await file.read()).decode("utf-8-sig")
    picks = draft_csv.parse_draft_csv(raw)
    if not picks:
        raise HTTPException(status_code=400, detail="No picks found in CSV")
    ws = _get_workspace(league)
    drafts = ws.setdefault("drafts", {})
    drafts[year] = {}
    for pick in picks:
        drafts[year].setdefault(pick["team"], []).append(
            {
                "round": pick["round"],
                "position": pick["position"],
                "nfl_team": pick["nfl_team"],
                "name": pick["name"],
                "is_keeper": pick["is_keeper"],
            }
        )
    if role == "prior":
        ws["prior_year"] = year
    else:
        ws["previous_year"] = year
    ws["draft_team_cols"] = sorted({p["team"] for p in picks})
    ws.pop("preview", None)
    ws.pop("preview_warnings", None)
    ws.pop("saved_at", None)
    _save_workspace(db, league, ws)
    team_counts = {
        col: len(picks_col)
        for col, picks_col in sorted(drafts[year].items())
    }
    return {
        "ok": True,
        "year": year,
        "role": role,
        "teams": team_counts,
        "total_picks": len(picks),
    }


@router.post("/draft/{token}/admin/keepers/use-draft")
def use_completed_draft(
    token: str, body: UseDraftIn, db: Session = Depends(get_db)
):
    """Load a completed draft from this app as previous/prior-season data."""
    league = _get_league(db, token)
    if body.role not in ("previous", "prior"):
        raise HTTPException(
            status_code=400, detail="role must be 'previous' or 'prior'"
        )
    completed = db.scalar(
        select(League)
        .where(League.id == body.draft_league_id, League.id != league.id)
        .options(
            selectinload(League.picks).selectinload(Pick.slot),
            selectinload(League.picks).selectinload(Pick.player),
            selectinload(League.picks).selectinload(Pick.team),
        )
    )
    if completed is None or completed.status != LeagueStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Selected league is not a completed draft",
        )
    picks_by_team: dict[str, list[dict]] = {}
    for pick in completed.picks:
        team_name = pick.team.name
        picks_by_team.setdefault(team_name, []).append(
            {
                "round": pick.slot.round,
                "position": pick.player.position,
                "nfl_team": pick.player.nfl_team,
                "name": pick.player.name,
                "is_keeper": pick.pick_type == PickType.KEEPER,
            }
        )
    if not picks_by_team:
        raise HTTPException(
            status_code=400,
            detail=f"Completed draft '{completed.name}' has no picks",
        )
    year = completed.season
    ws = _get_workspace(league)
    drafts = ws.setdefault("drafts", {})
    drafts[year] = picks_by_team
    if body.role == "prior":
        ws["prior_year"] = year
    else:
        ws["previous_year"] = year
    ws["draft_team_cols"] = sorted(picks_by_team.keys())
    ws.pop("preview", None)
    ws.pop("preview_warnings", None)
    ws.pop("saved_at", None)
    _save_workspace(db, league, ws)
    return {
        "ok": True,
        "year": year,
        "role": body.role,
        "teams": {name: len(picks) for name, picks in picks_by_team.items()},
        "total_picks": sum(len(picks) for picks in picks_by_team.values()),
    }


@router.post("/draft/{token}/admin/keepers/rosters-csv")
async def upload_rosters_csv(
    token: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    league = _get_league(db, token)
    ws = _get_workspace(league)
    rosters = ws.setdefault("rosters", {})
    yahoo_teams = ws.setdefault("yahoo_teams", [])
    loaded: dict[str, int] = {}
    errors: list[str] = []
    for file in files:
        stem = (file.filename or "").rsplit(".", 1)[0].strip()
        if not stem:
            continue
        rows = draft_csv.parse_roster_csv(
            (await file.read()).decode("utf-8-sig")
        )
        if not rows:
            errors.append(f"{stem}: no players found")
            continue
        rosters[stem] = rows
        if stem not in yahoo_teams:
            yahoo_teams.append(stem)
        loaded[stem] = len(rows)
    ws.pop("preview", None)
    ws.pop("preview_warnings", None)
    ws.pop("saved_at", None)
    _save_workspace(db, league, ws)
    return {"ok": True, "teams": loaded, "errors": errors}


# ---------------------------------------------------------------- mappings


@router.post("/draft/{token}/admin/keepers/mappings")
def save_mappings(
    token: str, body: KeeperMappingsIn, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    ws = _get_workspace(league)
    mappings = {}
    for item in body.mappings:
        mappings[str(item.team_id)] = {
            "draft_name": item.draft_name,
            "yahoo_name": item.yahoo_name,
        }
    ws["mappings"] = mappings
    ws.pop("preview", None)
    ws.pop("preview_warnings", None)
    _save_workspace(db, league, ws)
    return {"ok": True}


# ---------------------------------------------------------------- identify


@router.post("/draft/{token}/admin/keepers/identify")
def identify_keepers(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    ws = _get_workspace(league)
    if not ws.get("drafts", {}).get(ws.get("previous_year", "")):
        raise HTTPException(
            status_code=400,
            detail="Upload a previous-season draft CSV first",
        )
    if not ws.get("rosters"):
        raise HTTPException(
            status_code=400,
            detail="No roster data. Fetch from Yahoo or upload roster CSVs first.",
        )
    app_teams = [
        {"id": t.id, "name": t.name} for t in league.teams
    ]
    preview, warnings = _build_preview(ws, app_teams, league.season)
    ws["preview"] = preview
    ws["preview_warnings"] = warnings
    ws.pop("saved_at", None)
    _save_workspace(db, league, ws)
    return {
        "ok": True,
        "preview": preview,
        "warnings": warnings,
        "total": sum(len(t["candidates"]) for t in preview),
    }


# ---------------------------------------------------------------- save / export


@router.post("/draft/{token}/admin/keepers/save")
def save_keepers(
    token: str, body: KeeperSaveIn | None = None, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    ws = _get_workspace(league)
    if body and body.teams:
        preview = [
            {
                "team_id": t.team_id,
                "team_name": next(
                    (x["name"] for x in league.teams if x.id == t.team_id),
                    f"team-{t.team_id}",
                ),
                "candidates": [
                    {
                        "player_name": c.player_name,
                        "position": c.position,
                        "nfl_team": c.nfl_team,
                        "player_id_external": c.player_id_external,
                        "cost_round": c.cost_round,
                        "years_kept": c.years_kept,
                        "keepable_until_year": c.keepable_until_year,
                    }
                    for c in t.candidates
                ],
            }
            for t in body.teams
        ]
    else:
        preview = ws.get("preview", [])
    if not preview:
        raise HTTPException(
            status_code=400,
            detail="No keeper preview to save. Run identification first.",
        )
    rows = _rows_from_preview(preview)
    clear_candidates(db, league)
    stats = import_candidate_rows(db, league, rows, source="admin")
    ws["preview"] = preview
    ws["preview_warnings"] = ws.get("preview_warnings", [])
    from ..models import utcnow

    ws["saved_at"] = utcnow().isoformat()
    _save_workspace(db, league, ws)
    return {"ok": True, "stats": stats}


@router.get("/draft/{token}/admin/keepers/export")
def export_keepers(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    ws = _get_workspace(league)
    preview = ws.get("preview", [])
    if not preview:
        saved = db.scalars(
            select(KeeperCandidate)
            .where(KeeperCandidate.league_id == league.id)
            .order_by(KeeperCandidate.cost_round, KeeperCandidate.player_name)
        )
        by_team: dict[str, list[dict]] = {}
        for c in saved:
            by_team.setdefault(c.team.name, []).append(
                {
                    "player_name": c.player_name,
                    "position": c.position,
                    "nfl_team": c.player.nfl_team if c.player else "",
                    "cost_round": c.cost_round,
                    "years_kept": c.years_kept,
                    "keepable_until_year": c.keepable_until_year,
                }
            )
        preview = [
            {"team_name": name, "candidates": cands}
            for name, cands in by_team.items()
        ]
    files: list[dict] = []
    combined = io.StringIO()
    writer = csv.writer(combined)
    writer.writerow(
        ["Team", "Player", "Position", "NFL_Team", "Cost_Round", "Years_Kept", "Keepable_Until_Year"]
    )
    for team in preview:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Player", "Position", "NFL_Team", "Cost_Round", "Years_Kept", "Keepable_Until_Year"])
        for cand in team.get("candidates", []):
            row = [
                cand["player_name"],
                cand.get("position", ""),
                cand.get("nfl_team", ""),
                cand["cost_round"],
                cand.get("years_kept", 0),
                cand.get("keepable_until_year", ""),
            ]
            w.writerow(row)
            writer.writerow(
                [team["team_name"]] + row
            )
        files.append(
            {
                "filename": f"{_safe_filename(team['team_name'])}.csv",
                "csv": buf.getvalue(),
            }
        )
    return {
        "ok": True,
        "teams": files,
        "combined": combined.getvalue(),
        "total": sum(len(t.get("candidates", [])) for t in preview),
    }


# ---------------------------------------------------------------- yahoo


def _ensure_token(db: Session, config: YahooConfig) -> dict:
    token = config.access_token_json or {}
    if not token.get("access_token"):
        raise HTTPException(status_code=400, detail="Yahoo not authorized yet")
    import time as _time

    token_time = token.get("token_time", 0)
    refresh = token.get("refresh_token", "")
    if (
        refresh
        and _time.time() - float(token_time) > 3500
        and config.consumer_key
        and config.consumer_secret
    ):
        try:
            body = yahoo_mod.refresh_access_token(
                config.consumer_key, config.consumer_secret, refresh
            )
        except YahooError:
            body = {}
        if body.get("access_token"):
            config.access_token_json = yahoo_mod.build_token_json(
                config.consumer_key,
                config.consumer_secret,
                body,
                refresh_token=refresh,
                guid=token.get("guid", ""),
            )
            _commit(db)
            return config.access_token_json
    return token


def _fetch_teams_for_config(db: Session, config: YahooConfig) -> list[str]:
    token_json = _ensure_token(db, config)
    game_id = config.game_id or 449
    return yahoo_mod.fetch_league_teams(
        league_id=config.league_id_external,
        game_code=config.game_code or "nfl",
        game_id=game_id,
        consumer_key=config.consumer_key,
        consumer_secret=config.consumer_secret,
        token_json=token_json,
    )


@router.post("/draft/{token}/admin/keepers/yahoo-config")
async def save_yahoo_config(
    token: str, body: YahooConfigIn, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    config = _get_yahoo_config(db, league)
    if config is None:
        config = YahooConfig(league_id=league.id)
        db.add(config)
    if body.league_id_external:
        config.league_id_external = body.league_id_external
    if body.game_id is not None:
        config.game_id = body.game_id
    if body.game_code:
        config.game_code = body.game_code
    if body.season_id:
        config.season_id = body.season_id
    config.week = body.week
    if body.consumer_key:
        config.consumer_key = body.consumer_key
    if body.consumer_secret:
        config.consumer_secret = body.consumer_secret
    _commit(db)

    teams_fetched = False
    fetched_teams: list[str] = []
    warning: str | None = None

    token_json = config.access_token_json or {}
    if token_json.get("access_token") and config.league_id_external and config.consumer_key and config.consumer_secret:
        try:
            fetched_teams = await asyncio.to_thread(_fetch_teams_for_config, db, config)
            ws = _get_workspace(league)
            ws["yahoo_teams"] = fetched_teams
            _save_workspace(db, league, ws)
            teams_fetched = True
        except Exception as exc:
            warning = f"Config saved, but testing Yahoo connection failed: {exc}"

    return {
        "ok": True,
        "yahoo": _masked_yahoo(config),
        "teams_fetched": teams_fetched,
        "teams": fetched_teams,
        "warning": warning,
    }


@router.post("/draft/{token}/admin/keepers/yahoo/authorize")
def yahoo_authorize(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    config = _get_yahoo_config(db, league)
    if config is None or not config.consumer_key:
        raise HTTPException(
            status_code=400,
            detail="Set a Yahoo consumer key first",
        )
    return {"ok": True, "authorization_url": yahoo_mod.authorization_url(config.consumer_key)}


@router.post("/draft/{token}/admin/keepers/yahoo/callback")
async def yahoo_callback(
    token: str, body: YahooCodeIn, db: Session = Depends(get_db)
):
    league = _get_league(db, token)
    config = _get_yahoo_config(db, league)
    if config is None or not (config.consumer_key and config.consumer_secret):
        raise HTTPException(
            status_code=400,
            detail="Yahoo consumer key/secret not configured",
        )
    try:
        token_body = yahoo_mod.exchange_code(
            config.consumer_key, config.consumer_secret, body.code
        )
    except YahooError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    config.access_token_json = yahoo_mod.build_token_json(
        config.consumer_key, config.consumer_secret, token_body
    )
    _commit(db)

    teams_fetched = False
    fetched_teams: list[str] = []
    warning: str | None = None
    if config.league_id_external:
        try:
            fetched_teams = await asyncio.to_thread(_fetch_teams_for_config, db, config)
            ws = _get_workspace(league)
            ws["yahoo_teams"] = fetched_teams
            _save_workspace(db, league, ws)
            teams_fetched = True
        except Exception as exc:
            warning = f"Authorized with Yahoo, but fetching team names failed: {exc}"

    return {
        "ok": True,
        "yahoo": _masked_yahoo(config),
        "teams_fetched": teams_fetched,
        "teams": fetched_teams,
        "warning": warning,
    }


@router.post("/draft/{token}/admin/keepers/fetch")
async def fetch_yahoo(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    config = _get_yahoo_config(db, league)
    if config is None or not config.league_id_external:
        raise HTTPException(
            status_code=400,
            detail="Set the Yahoo league ID first",
        )
    token_json = _ensure_token(db, config)
    game_id = config.game_id or 449

    def _fetch() -> dict:
        return yahoo_mod.fetch_snapshot(
            league_id=config.league_id_external,
            game_code=config.game_code or "nfl",
            game_id=game_id,
            consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret,
            token_json=token_json,
            week=config.week,
        )

    try:
        rosters = await asyncio.to_thread(_fetch)
    except YahooError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Yahoo fetch failed: {exc}",
        )

    ws = _get_workspace(league)
    ws["rosters"] = rosters
    ws["yahoo_teams"] = list(rosters.keys())
    ws["roster_week"] = config.week
    ws.pop("preview", None)
    ws.pop("preview_warnings", None)
    ws.pop("saved_at", None)
    _save_workspace(db, league, ws)
    return {
        "ok": True,
        "teams": list(rosters.keys()),
        "player_count": sum(len(rows) for rows in rosters.values()),
    }


@router.post("/draft/{token}/admin/keepers/yahoo/teams")
async def yahoo_teams(token: str, db: Session = Depends(get_db)):
    """Test the Yahoo config/token and store the league team names.

    Lets the commissioner map Yahoo teams to draft teams before any roster
    fetch. A success proves the consumer key/secret + OAuth token + league
    ID are all valid.
    """
    league = _get_league(db, token)
    config = _get_yahoo_config(db, league)
    if config is None or not config.league_id_external:
        raise HTTPException(
            status_code=400,
            detail="Set the Yahoo league ID first",
        )
    try:
        names = await asyncio.to_thread(_fetch_teams_for_config, db, config)
    except YahooError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Yahoo fetch failed: {exc}",
        )

    ws = _get_workspace(league)
    ws["yahoo_teams"] = names
    ws.pop("preview", None)
    ws.pop("preview_warnings", None)
    _save_workspace(db, league, ws)
    return {"ok": True, "teams": names, "count": len(names)}


@router.delete("/draft/{token}/admin/keepers/workspace")
def reset_workspace(token: str, db: Session = Depends(get_db)):
    league = _get_league(db, token)
    league.keeper_workspace = {}
    clear_candidates(db, league)
    _commit(db)
    return {"ok": True}