"""Async SQLAlchemy 2.0 engine, session, and declarative base."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for all Rasathane models."""


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://rasathane:rasathane@localhost:5435/rasathane",
    )


engine = create_async_engine(
    _database_url(),
    echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
    pool_pre_ping=True,
)

session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession scoped to the request."""
    async with session_factory() as session:
        yield session
