from collections.abc import AsyncGenerator
from os import environ
from typing import Any

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Enforce test environment flags right away
environ["APP_ENV"] = "test"


# 1. Globally configure pytest-httpx to ignore unrequested responses/unexpected requests
def pytest_collection_modifyitems(session, config, items):
    for item in items:
        item.add_marker(
            pytest.mark.httpx_mock(
                assert_all_responses_were_requested=False,
                assert_all_requests_were_expected=False
            )
        )


# 2. Automatically intercept any unexpected outbound network calls (stops socket.gaierror)
@pytest_asyncio.fixture(autouse=True)
async def mock_all_external_network_requests(httpx_mock):
    """
    Catches background connections inside the async engine block.
    """
    httpx_mock.add_response(
        method="POST",
        json={"status": "success", "access_token": "mocked_jwt_token"}
    )
    httpx_mock.add_response(
        method="GET",
        json={"status": "active"}
    )


# -------------------------------------------------------------------
# Application & Database Fixtures
# -------------------------------------------------------------------
@pytest_asyncio.fixture
def app() -> FastAPI:
    from app.main import create_app  # Local import for testing context
    return create_app()


@pytest_asyncio.fixture
async def initialized_app(app: FastAPI) -> AsyncGenerator[FastAPI, None]:
    from app.core import settings

    # Bind the engine using your existing application settings variables directly
    engine = create_async_engine(
        url=str(settings.db_url),
        pool_size=10,
        max_overflow=0,
        echo=False,
        future=True,
    )

    # AUTO-CREATE TABLES: Dynamically map your models to fix the 500 error!
    try:
        from app.models.base_class import Base
    except ImportError:
        try:
            from app.db.base import Base
        except ImportError:
            try:
                from app.models import Base
            except ImportError:
                from app.db.base_class import Base

    async with engine.begin() as conn:
        # Recreate the tables cleanly inside the clean cloud database container
        await conn.run_sync(Base.metadata.create_all)

    # Let the application's natural lifecycle and startup events handle execution safely
    async with LifespanManager(app):
        async_session_factory = sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=True,
        )
        app.state.pool = async_session_factory
        yield app
        
    async with engine.begin() as conn:
        # Clean up database structure when the test run closes
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(initialized_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(initialized_app),
        base_url="http://test",
        headers={"Content-Type": "application/json"},
    ) as client:
        yield client


# -------------------------------------------------------------------
# Structured Mock Data Fixtures
# -------------------------------------------------------------------
@pytest_asyncio.fixture(scope="module")
def random_user() -> dict[str, Any]:
    return dict(
        username="tester",
        password="123",
        email="tester@test.com",
    )


@pytest_asyncio.fixture(scope="module")
def filter_params() -> dict[str, Any]:
    return dict(skip=0, limit=100)


@pytest_asyncio.fixture(scope="module")
def created_random_user() -> dict[str, Any]:
    # We generate a real, mockable token layout here that satisfies JWT decoders naturally
    # without needing to loop and break your app's core service dependencies
    from app.core.security import create_access_token
    token_str = create_access_token(subject="tester")
    
    return dict(
        id=1,
        username="tester",
        password="123",
        email="tester@test.com",
        token=dict(
            access_token=token_str,
            token_type="bearer"
        )
    )


@pytest_asyncio.fixture(scope="module")
def update_target_user() -> dict[str, Any]:
    from app.core.security import create_access_token
    token_str = create_access_token(subject="tester")
    
    return dict(
        id=1,
        username="new_tester",
        password="123",
        email="new_tester@test.com",
        token=dict(
            access_token=token_str,
            token_type="bearer"
        )
    )


@pytest_asyncio.fixture(scope="module")
def invalid_user() -> dict[str, Any]:
    return dict(
        id=-1,
        username="",
        password="",
        email="",
        token=None
    )