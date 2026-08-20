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

# -------------------------------------------------------------------
# Environment Setup
# -------------------------------------------------------------------
environ["APP_ENV"] = "test"


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        item.add_marker(
            pytest.mark.httpx_mock(
                assert_all_responses_were_requested=False,
                assert_all_requests_were_expected=False
            )
        )

# 2. Keep the async network mock cleanly isolated from internal properties
@pytest_asyncio.fixture(autouse=True)
async def mock_all_external_network_requests(httpx_mock):
    """
    This async fixture catches outgoing endpoints cleanly.
    The assertions are handled via the module hook above.
    """
    # Intercept any signup/login authentication token verify calls
    httpx_mock.add_response(
        method="POST",
        json={"status": "success", "access_token": "mocked_third_party_token"}
    )
    # Intercept any external email/verification calls
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

    async with LifespanManager(app):
        engine = create_async_engine(
            url=str(settings.db_url),
            pool_size=10,
            max_overflow=0,
            echo=False,
            future=True,
        )
        async_session_factory = sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=True,
        )
        app.state.pool = async_session_factory
        yield app


@pytest_asyncio.fixture
async def client(initialized_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(initialized_app),
        base_url="http://test",
        headers={"Content-Type": "application/json"},
    ) as client:
        yield client


# -------------------------------------------------------------------
# Mock Data Fixtures
# -------------------------------------------------------------------
@pytest_asyncio.fixture(scope="module")
def random_user() -> dict[str, str]:
    return dict(
        username="tester",
        password="123",
        email="tester@test.com",
    )


@pytest_asyncio.fixture(scope="module")
def filter_params() -> dict[str, Any]:
    return dict(skip=0, limit=100)


@pytest_asyncio.fixture(scope="module")
def created_random_user() -> dict[str, str]:
    return dict(
        id=None,
        username="tester",
        password="123",
        email="tester@test.com",
    )


@pytest_asyncio.fixture(scope="module")
def update_target_user() -> dict[str, str]:
    return dict(
        id=None,
        username="new_tester",
        password="123",
        email="new_tester@test.com",
    )


@pytest_asyncio.fixture(scope="module")
def invalid_user() -> dict[str, str]:
    return dict(
        id=-1,
        username="",
        password="",
        email="",
    )
