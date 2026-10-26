"""
Database configuration and initialization for the Smart Home Activity Recognition System.
Layer 4: Storage Layer - SQLite via SQLAlchemy
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Database file location
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./smarthome.db"
)

# SQLite engine with WAL mode for better concurrent access
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

# Enable WAL mode for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency injection for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize the database, creating all tables."""
    from app.models import db_models  # noqa: F401 - triggers table registration
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully.")
