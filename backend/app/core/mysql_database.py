"""
MySQL database connection module for SmartHome AI.
Separate and isolated from the existing SQLite storage (backend/app/core/database.py).
Reads credentials securely from environment variables without hardcoding.
"""

import os
import urllib.parse
from typing import Optional, Tuple, Dict, Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Load .env file if present in backend or root
load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "smarthome")

# Lazy-loaded engine and session factory
_mysql_engine = None
_MySQLSessionLocal = None


def get_mysql_url(include_db: bool = True) -> Optional[str]:
    """
    Construct the SQLAlchemy connection string for MySQL using mysqlconnector.
    Returns None if MYSQL_PASSWORD is not set.
    """
    if not MYSQL_PASSWORD:
        return None

    # URL-encode password in case it contains special characters (@, :, /, etc.)
    encoded_password = urllib.parse.quote_plus(MYSQL_PASSWORD)
    encoded_user = urllib.parse.quote_plus(MYSQL_USER)

    db_part = f"/{MYSQL_DATABASE}" if include_db else ""
    return f"mysql+mysqlconnector://{encoded_user}:{encoded_password}@{MYSQL_HOST}:{MYSQL_PORT}{db_part}"


def get_mysql_engine(include_db: bool = True):
    """Obtain or initialize the SQLAlchemy engine for MySQL."""
    global _mysql_engine
    if not include_db:
        url = get_mysql_url(include_db=False)
        if not url:
            raise ValueError("MYSQL_PASSWORD environment variable is not set.")
        return create_engine(url, pool_recycle=3600, pool_pre_ping=True)

    if _mysql_engine is None:
        url = get_mysql_url(include_db=True)
        if not url:
            raise ValueError("MYSQL_PASSWORD environment variable is not set.")
        _mysql_engine = create_engine(
            url,
            pool_recycle=3600,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _mysql_engine


def get_mysql_session_factory():
    """Get the SQLAlchemy sessionmaker for MySQL."""
    global _MySQLSessionLocal
    if _MySQLSessionLocal is None:
        engine = get_mysql_engine(include_db=True)
        _MySQLSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _MySQLSessionLocal


def get_mysql_db():
    """FastAPI-compatible dependency injection for MySQL sessions (when activated)."""
    SessionFactory = get_mysql_session_factory()
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


def test_mysql_connection() -> Tuple[bool, str, Dict[str, Any]]:
    """
    Verify MySQL connectivity and server status.
    Returns:
        (success: bool, message: str, details: dict)
    """
    if not MYSQL_PASSWORD:
        return (
            False,
            "Environment variable 'MYSQL_PASSWORD' is not set. Please set MYSQL_PASSWORD before connecting.",
            {"host": MYSQL_HOST, "port": MYSQL_PORT, "user": MYSQL_USER, "database": MYSQL_DATABASE}
        )

    try:
        # Step 1: Connect to server without database to verify credentials
        server_engine = get_mysql_engine(include_db=False)
        with server_engine.connect() as conn:
            version_res = conn.execute(text("SELECT VERSION()")).scalar()
            databases_res = [row[0] for row in conn.execute(text("SHOW DATABASES")).fetchall()]

        db_exists = MYSQL_DATABASE in databases_res

        # Step 2: Test connection directly to the target database if it exists
        tables = []
        if db_exists:
            db_engine = get_mysql_engine(include_db=True)
            with db_engine.connect() as conn:
                tables = [row[0] for row in conn.execute(text("SHOW TABLES")).fetchall()]

        return (
            True,
            f"Successfully connected to MySQL server version {version_res}.",
            {
                "host": MYSQL_HOST,
                "port": MYSQL_PORT,
                "user": MYSQL_USER,
                "server_version": version_res,
                "database": MYSQL_DATABASE,
                "database_exists": db_exists,
                "existing_tables": tables,
            }
        )
    except Exception as err:
        return (
            False,
            f"MySQL connection failed: {err}",
            {
                "host": MYSQL_HOST,
                "port": MYSQL_PORT,
                "user": MYSQL_USER,
                "database": MYSQL_DATABASE,
                "error_type": type(err).__name__,
            }
        )


def create_mysql_tables() -> Tuple[bool, str, list]:
    """
    Create all tables in MySQL based on the SQLAlchemy db_models definition.
    Safe and non-destructive: uses Base.metadata.create_all(bind=engine).
    """
    from app.core.database import Base
    import app.models.db_models  # noqa: F401 - register models

    success, msg, details = test_mysql_connection()
    if not success:
        return False, msg, []

    if not details.get("database_exists"):
        # Auto-create database if needed
        try:
            server_engine = get_mysql_engine(include_db=False)
            with server_engine.connect() as conn:
                conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
                conn.commit()
        except Exception as err:
            return False, f"Failed to create database '{MYSQL_DATABASE}': {err}", []

    try:
        db_engine = get_mysql_engine(include_db=True)
        Base.metadata.create_all(bind=db_engine)

        with db_engine.connect() as conn:
            created_tables = [row[0] for row in conn.execute(text("SHOW TABLES")).fetchall()]

        return True, "Successfully created all tables in MySQL database.", created_tables
    except Exception as err:
        return False, f"Failed to create tables in MySQL: {err}", []
