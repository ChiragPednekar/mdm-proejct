"""Database engine / session management."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
# Sessions run in UTC so timestamps are stored and returned consistently.
engine = create_engine(
    _settings.database_url, pool_pre_ping=True, future=True, connect_args={"options": "-c timezone=UTC"}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    Services commit explicitly; anything left uncommitted (e.g. after an
    exception) is rolled back when the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
