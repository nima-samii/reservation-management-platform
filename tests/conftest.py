"""
Shared test fixtures.

Integration tests run against a real PostgreSQL server — the same one
docker-compose starts for development, on its host-mapped port. They use a
dedicated `reservations_test` database, which this module creates on demand, so
the development database is never touched.

Point them somewhere else with `TEST_DATABASE_URL`, or override the pieces with
`TEST_DB_HOST` / `TEST_DB_PORT` / `TEST_DB_NAME`.
"""
import asyncio
import os
from collections.abc import AsyncGenerator
from urllib.parse import quote_plus

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base

# docker-compose publishes the db container's 5432 on the host as 5433, so the
# host-side port deliberately differs from settings.POSTGRES_PORT (which is the
# in-container value the app uses).
TEST_DB_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_DB_PORT = os.getenv("TEST_DB_PORT", "5433")
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "reservations_test")

_CREDENTIALS = (
    f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
)
_SERVER = f"{TEST_DB_HOST}:{TEST_DB_PORT}"

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or (
    f"postgresql+asyncpg://{_CREDENTIALS}@{_SERVER}/{TEST_DB_NAME}"
)
# Maintenance connection used only to create the test database if it is missing.
_ADMIN_DATABASE_URL = f"postgresql+asyncpg://{_CREDENTIALS}@{_SERVER}/postgres"

_UNREACHABLE = (
    f"PostgreSQL is not reachable at {_SERVER}. Integration tests need it.\n"
    f"Start it with:  docker compose up -d db"
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_database() -> str:
    """Ensure the test database exists; skip the DB suite if the server is down.

    Skipping rather than erroring keeps a `pytest` run without Docker usable for
    the pure-unit tests, while still naming the exact command to fix it.
    """
    import asyncpg

    async def ensure() -> None:
        dsn = _ADMIN_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn)
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
            )
            if not exists:
                # No IF NOT EXISTS for CREATE DATABASE; the check above plus this
                # call is fine because the test session is single-writer.
                await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
        finally:
            await conn.close()

    if os.getenv("TEST_DATABASE_URL"):
        # Explicitly pointed elsewhere — assume the caller provisioned it.
        return TEST_DATABASE_URL

    try:
        asyncio.run(ensure())
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"{_UNREACHABLE}\n({type(exc).__name__}: {exc})", allow_module_level=True)
    return TEST_DATABASE_URL


@pytest_asyncio.fixture(scope="function")
async def db_session(test_database: str) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(test_database, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
