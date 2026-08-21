from collections.abc import AsyncGenerator
from os import environ
from typing import Any

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
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
    
    try:
        from app.models.user import User as UserModel
    except ImportError:
        try:
            from app.models import User as UserModel
        except ImportError:
            UserModel = None

    app_instance = create_app()

    if UserModel:
        mock_user_instance = UserModel()
        mock_user_instance.id = 1
        mock_user_instance.username = "tester"
        mock_user_instance.email = "tester@test.com"
        mock_user_instance.is_active = True
        mock_user_instance.is_superuser = True

        for route in app_instance.routes:
            if hasattr(route, "dependant") and route.dependant.dependencies:
                for dep in route.dependant.dependencies:
                    dep_name = (dep.name or "").lower()
                    
                    is_auth_guard = "token" in dep_name or "jwt" in dep_name or dep_name == "current_user"
                    is_core_service = "service" in dep_name or "manager" in dep_name or "db" in dep_name
                    
                    if is_auth_guard and not is_core_service:
                        try:
                            app_instance.dependency_overrides[dep.call] = lambda: mock_user_instance
                        except Exception:
                            pass

    return app_instance


@pytest_asyncio.fixture
async def initialized_app(app: FastAPI) -> AsyncGenerator[FastAPI, None]:
    from app.core import settings

    engine = create_async_engine(
        url=str(settings.db_url),
        pool_size=10,
        max_overflow=0,
        echo=False,
        future=True,
    )

    async with LifespanManager(app):
        async_session_factory = sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=True,
        )
        app.state.pool = async_session_factory
        
        async with async_session_factory() as session:
            try:
                await session.execute(text("""
                    INSERT INTO users (id, username, email, password, is_active, is_superuser)
                    VALUES (1, 'tester', 'tester@test.com', 'hashed_123_placeholder', TRUE, TRUE)
                    ON CONFLICT (id) DO NOTHING;
                """))
                await session.commit()
            except Exception as e:
                print(f"Pre-seeding failed: {e}")

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