"""
SQLAlchemy async engine + session factory.
Also provides a sync engine for Alembic migrations.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings


# ── Async engine (used by the application) ──────────────────────────────────
from sqlalchemy.pool import NullPool

engine = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=NullPool,     # No persistent pool — fresh connection each time.
                            # Prevents WinError 64 on Windows/Docker from stale
                            # connections accumulating across CLI invocations.
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """All ORM models inherit from this."""
    pass


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables (used in dev; production uses Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
