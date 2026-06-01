from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

def _resolve_database_url() -> str:
    """web_kp uses sync SQLite; ignore catalog bot's aiosqlite DATABASE_URL."""
    url = os.getenv("WEB_KP_DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///./web_kp.db"
    if "aiosqlite" in url:
        return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return url


DATABASE_URL = _resolve_database_url()

connect_args: dict[str, object] = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def init_db() -> None:
    from models import Base

    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
