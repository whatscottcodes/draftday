import asyncio
import hmac
import os
import re
from contextlib import asynccontextmanager

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
        return JSONResponse(
            status_code=503,
            content={"detail": "ADMIN_PASSCODE is not configured on the server"},
        )
    provided = request.headers.get("X-Admin-Passcode", "")
    if not provided or not hmac.compare_digest(provided, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": "Commissioner passcode required"},
        )
    return await call_next(request)


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