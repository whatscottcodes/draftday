import asyncio
import hmac
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import loop
from .api.keeper_admin import router as keeper_admin_router
from .api.routes import router
from .database import SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop.main_loop = asyncio.get_running_loop()
    init_db()
    yield


app = FastAPI(title="Draft Night", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(keeper_admin_router)

_ADMIN_PATH_RE = re.compile(r"^/api/draft/[^/]+/admin(/.*)?$")
_GATED_PATHS = {"/api/leagues"}


@app.middleware("http")
async def admin_gate(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if path not in _GATED_PATHS and _ADMIN_PATH_RE.match(path) is None:
        return await call_next(request)
    expected = os.environ.get("ADMIN_PASSCODE", "").strip()
    if not expected:
        return _gate_response(
            request,
            503,
            "ADMIN_PASSCODE is not configured on the server",
        )
    provided = unquote(request.headers.get("X-Admin-Passcode", ""))
    if not provided or not hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        return _gate_response(request, 401, "Commissioner passcode required")
    return await call_next(request)


def _gate_response(request: Request, status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"detail": detail},
        headers={
            "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        },
    )


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> Response:
    body = b'{"ok":true}'
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Length": str(len(body)), "Connection": "close"},
    )


@app.api_route("/api/ping", methods=["GET", "HEAD"])
def ping() -> Response:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
    body = b'{"ok":true}'
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Length": str(len(body)), "Connection": "close"},
    )