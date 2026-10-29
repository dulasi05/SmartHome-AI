"""
Pytest configuration and shared fixtures for SmartHome AI test suite.
Provides an isolated in-memory SQLite database with StaticPool for thread-safe test isolation.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_DB_URL = "sqlite:///:memory:"
os.environ["DATABASE_URL"] = TEST_DB_URL

from app.main import app
from app.core.database import Base, get_db
from app.api.sensors import _RECENT_EVENTS_CACHE, _EVENT_IDS_SEEN

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_test_database():
    """Create all database tables, configure dependency override, and clean up after each test."""
    Base.metadata.create_all(bind=engine)
    _RECENT_EVENTS_CACHE.clear()
    _EVENT_IDS_SEEN.clear()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    _RECENT_EVENTS_CACHE.clear()
    _EVENT_IDS_SEEN.clear()


@pytest.fixture
def client():
    """FastAPI TestClient fixture using overridden test database."""
    return TestClient(app)
