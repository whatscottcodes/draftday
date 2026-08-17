import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./draftnight.db",
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_MIGRATIONS = [
    ("players", "extra", {"sqlite": "extra JSON", "postgresql": "extra JSONB"}),
    (
        "leagues",
        "roster_slots",
        {"sqlite": "roster_slots JSON", "postgresql": "roster_slots JSONB"},
    ),
    (
        "leagues",
        "keeper_workspace",
        {"sqlite": "keeper_workspace JSON", "postgresql": "keeper_workspace JSONB"},
    ),
    (
        "yahoo_configs",
        "week",
        {"sqlite": "week INTEGER", "postgresql": "week INTEGER"},
    ),
]


def _existing_columns(conn, table):
    if engine.dialect.name == "sqlite":
        return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
    if engine.dialect.name == "postgresql":
        rows = conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table}'"
        )
        return {row[0] for row in rows}
    return None


def init_db():
    from . import models  # noqa: F401  (registers ORM models with Base.metadata)

    Base.metadata.create_all(bind=engine)

    existing = _existing_columns
    for table, column, ddl_by_dialect in _MIGRATIONS:
        ddl = ddl_by_dialect.get(engine.dialect.name)
        if ddl is None:
            continue
        with engine.begin() as conn:
            columns = existing(conn, table)
            if columns is not None and column not in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")