import asyncio
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from src.configs.db import get_session
from src.main import app

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    """Defines the asyncio backend to be used by AnyIO."""
    return "asyncio"


@pytest.fixture(scope="session")
def event_loop():
    """Redefine the event_loop fixture to have a session scope."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(name="engine", scope="session")
async def engine_fixture() -> AsyncGenerator[AsyncEngine, None]:
    """Create a test database engine."""
    engine = AsyncEngine(create_engine(TEST_DATABASE_URL, echo=False))
    yield engine
    # Cleanup after all tests in the session have run
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
async def create_db_tables(engine: AsyncEngine) -> None:
    """Create all database tables before running tests."""
    async with engine.begin() as conn:
        # Import all models here for them to be found by SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)


@pytest.fixture(name="session", scope="function")
async def session_fixture(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provides a fresh database session for each test."""
    async with AsyncSession(engine) as session:
        yield session
        # Teardown: Clean up the database after each test
        await session.rollback()


@pytest.fixture(name="client")
async def client_fixture(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provides an async test client with an overridden database session."""

    async def get_session_override() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = get_session_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()
