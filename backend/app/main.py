import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
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