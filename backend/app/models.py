from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeagueStatus:
    SETUP = "SETUP"
    READY = "READY"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"


class PickType:
    KEEPER = "keeper"
    LIVE = "live"
    COMMISSIONER = "commissioner"


DEFAULT_ROSTER_SLOTS = [
    "QB1",
    "QB2",
    "RB1",
    "RB2",
    "WR1",
    "WR2",
    "TE",
    "Flex",
    "DST",
    "K",
]


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    season: Mapped[str] = mapped_column(String(20))
    num_teams: Mapped[int] = mapped_column(Integer)
    num_rounds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=LeagueStatus.SETUP)
    access_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    roster_slots: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    teams: Mapped[list["Team"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    players: Mapped[list["Player"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    rankings: Mapped[list["Ranking"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    slots: Mapped[list["DraftSlot"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    keepers: Mapped[list["Keeper"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    picks: Mapped[list["Pick"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    events: Mapped[list["DraftEvent"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    draft_position: Mapped[int] = mapped_column(Integer)
    manager_name: Mapped[str] = mapped_column(String(200), default="")
    access_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    league: Mapped[League] = relationship(back_populates="teams")
    keepers: Mapped[list["Keeper"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    picks: Mapped[list["Pick"]] = relationship(back_populates="team")

    __table_args__ = (
        UniqueConstraint("league_id", "draft_position", name="uq_league_position"),
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    player_id: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str] = mapped_column(String(10), default="")
    nfl_team: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(20), default="available")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    league: Mapped[League] = relationship(back_populates="players")
    rankings: Mapped[list["Ranking"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    keepers: Mapped[list["Keeper"]] = relationship(back_populates="player")
    picks: Mapped[list["Pick"]] = relationship(back_populates="player")

    __table_args__ = (
        UniqueConstraint("league_id", "player_id", name="uq_league_player_id"),
    )


class Ranking(Base):
    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    adp: Mapped[float | None] = mapped_column(Integer, nullable=True)

    league: Mapped[League] = relationship(back_populates="rankings")
    player: Mapped[Player] = relationship(back_populates="rankings")

    __table_args__ = (
        UniqueConstraint("league_id", "player_id", name="uq_league_ranked_player"),
    )


class DraftSlot(Base):
    __tablename__ = "draft_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    pick_number: Mapped[int] = mapped_column(Integer, index=True)
    original_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    drafting_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    league: Mapped[League] = relationship(back_populates="slots")
    original_team: Mapped[Team] = relationship(foreign_keys=[original_team_id])
    drafting_team: Mapped[Team] = relationship(foreign_keys=[drafting_team_id])
    pick: Mapped["Pick"] = relationship(back_populates="slot", uselist=False)

    __table_args__ = (
        UniqueConstraint("league_id", "pick_number", name="uq_league_pick_number"),
    )


class Keeper(Base):
    __tablename__ = "keepers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    round: Mapped[int] = mapped_column(Integer)

    league: Mapped[League] = relationship(back_populates="keepers")
    team: Mapped[Team] = relationship(back_populates="keepers")
    player: Mapped[Player] = relationship(back_populates="keepers")


class Pick(Base):
    __tablename__ = "picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    draft_slot_id: Mapped[int] = mapped_column(
        ForeignKey("draft_slots.id"), unique=True, index=True
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    pick_type: Mapped[str] = mapped_column(String(20), default=PickType.LIVE)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    league: Mapped[League] = relationship(back_populates="picks")
    slot: Mapped[DraftSlot] = relationship(back_populates="pick")
    team: Mapped[Team] = relationship(back_populates="picks")
    player: Mapped[Player] = relationship(back_populates="picks")


class DraftEvent(Base):
    __tablename__ = "draft_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    league: Mapped[League] = relationship(back_populates="events")