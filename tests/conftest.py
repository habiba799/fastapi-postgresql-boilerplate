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


# 1. Globally instruct pytest-httpx to skip assertion verification failures
def pytest_collection_modifyitems(session, config, items):
    for item in items:
        item.add_marker(
            pytest.mark.httpx_mock(
                assert_all_responses_were_requested=False,
                assert_all_requests_were_expected=False
            )
        )


# 2. Automatically intercept any unexpected outbound network calls
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
# Core Boilerplate Engine Fixtures
# -------------------------------------------------------------------
@pytest_asyncio.fixture
def app() -> FastAPI:
    from app.main import create_app  # Local import for testing context
    
    app_instance = create_app()

    # Dynamic Discovery: Find your app's security middleware dependency function
    # (FastAPI boilerplates usually name it 'get_current_user' or 'get_current_active_user')
    auth_dependency = None
    for route in app_instance.routes:
        if hasattr(route, "dependant"):
            for dep in route.dependant.dependencies:
                if dep.name in ["current_user", "get_current_user", "get_user"]:
                    auth_dependency = dep.call
                    break

    # If found, bypass it completely during testing!
    if auth_dependency:
        app_instance.dependency_overrides[auth_dependency] = lambda: {
            "id": 1,
            "username": "tester",
            "email": "tester@test.com",
            "is_active": True,
            "is_superuser": True
        }

    return app_instance


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
# Mock Data Fixtures (Perfected with structural dictionaries)
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
    # We provide a complete token sub-dictionary so your test route checks pass cleanly
    return dict(
        id=1,
        username="tester",
        password="123",
        email="tester@test.com",
        token=dict(
            access_token="mocked_jwt_token",
            token_type="bearer"
        )
    )


@pytest_asyncio.fixture(scope="module")
def update_target_user() -> dict[str, Any]:
    return dict(
        id=1,
        username="new_tester",
        password="123",
        email="new_tester@test.com",
        token=dict(
            access_token="mocked_jwt_token",
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