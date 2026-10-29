"""
Database configuration and initialization for SmartHome AI.
Layer 4: Storage Layer.

Supports dual backends:
1. MySQL (Primary / Production) — via mysql-connector-python & SQLAlchemy
2. SQLite (Local / Fallback / Testing) — smarthome.db with WAL mode

Automatically selects MySQL when MYSQL_PASSWORD or DB_BACKEND=mysql is configured.
Preserves existing SQLite data without deletion or modification.
"""

import os
import logging
import urllib.parse
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load .env if present in workspace root or backend
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKSPACE_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))
load_dotenv(os.path.join(WORKSPACE_ROOT, ".env"))
load_dotenv()

logger = logging.getLogger(__name__)

Base = declarative_base()

# ─── Configuration Parameters ──────────────────────────────────────────────────
DB_BACKEND = os.environ.get("DB_BACKEND", "").lower().strip()
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "smarthome")

# Absolute path for SQLite database to prevent split databases between root and backend
DEFAULT_SQLITE_PATH = os.path.abspath(
    os.path.join(BACKEND_DIR, "smarthome.db")
)
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH.replace(os.sep, '/')}"

CUSTOM_DATABASE_URL = os.environ.get("DATABASE_URL")

# Determine active database type
ACTIVE_DB_TYPE = "sqlite"
engine = None
SessionLocal = None


def _build_mysql_url() -> str:
    """Build URL-encoded MySQL connection string."""
    encoded_user = urllib.parse.quote_plus(MYSQL_USER)
    encoded_pw = urllib.parse.quote_plus(MYSQL_PASSWORD) if MYSQL_PASSWORD else ""
    return f"mysql+mysqlconnector://{encoded_user}:{encoded_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"


def _init_sqlite_engine(url: str):
    """Initialize SQLite engine with WAL mode and foreign key constraints."""
    eng = create_engine(
        url,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


def configure_database():
    """
    Configures and initializes the active database engine (MySQL or SQLite).
    Strict guarantee: If MySQL is configured, will NOT silently fallback to SQLite.
    """
    global ACTIVE_DB_TYPE, engine, SessionLocal

    # 1. Custom DATABASE_URL override
    if CUSTOM_DATABASE_URL:
        if CUSTOM_DATABASE_URL.startswith("mysql"):
            ACTIVE_DB_TYPE = "mysql"
            engine = create_engine(
                CUSTOM_DATABASE_URL,
                pool_pre_ping=True,
                pool_recycle=3600,
                pool_size=5,
                max_overflow=10,
            )
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            logger.info("✅ Database configured via custom MySQL DATABASE_URL")
            return
        elif CUSTOM_DATABASE_URL.startswith("sqlite"):
            ACTIVE_DB_TYPE = "sqlite"
            engine = _init_sqlite_engine(CUSTOM_DATABASE_URL)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            logger.info("ℹ️ Database configured via custom SQLite DATABASE_URL")
            return

    # 2. Check if MySQL is requested or configured
    should_use_mysql = (
        DB_BACKEND == "mysql" or
        bool(MYSQL_PASSWORD)
    )

    if should_use_mysql:
        if not MYSQL_PASSWORD:
            raise RuntimeError(
                "❌ MySQL is configured as the active database (DB_BACKEND=mysql), "
                "but the 'MYSQL_PASSWORD' environment variable is not set. "
                "Set MYSQL_PASSWORD in your .env file or system environment to connect."
            )

        try:
            mysql_url = _build_mysql_url()
            mysql_engine = create_engine(
                mysql_url,
                pool_pre_ping=True,
                pool_recycle=3600,
                pool_size=5,
                max_overflow=10,
                connect_args={"connect_timeout": 10},
            )
            # Test connection immediately
            with mysql_engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            ACTIVE_DB_TYPE = "mysql"
            engine = mysql_engine
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            logger.info(f"✅ MySQL ACTIVE: Connected to {MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
            return
        except Exception as err:
            raise RuntimeError(
                f"❌ Failed to connect to MySQL database at {MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}: {err}. "
                f"MySQL is configured as active. To prevent silent fallback to SQLite and data divergence, "
                f"please verify that MySQL 8 is running and credentials are valid."
            )

    # 3. Default: SQLite (when MySQL is not configured)
    ACTIVE_DB_TYPE = "sqlite"
    engine = _init_sqlite_engine(DEFAULT_SQLITE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info(f"ℹ️ SQLite ACTIVE: Using storage at {DEFAULT_SQLITE_PATH}")


# Run initial database engine configuration
configure_database()


def get_db():
    """Dependency injection for database sessions across all FastAPI routes."""
    if SessionLocal is None:
        configure_database()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize tables in the active database."""
    from app.models import db_models  # noqa: F401 - triggers model registration
    if engine is None:
        configure_database()
    Base.metadata.create_all(bind=engine)
    logger.info(f"✅ Database tables verified on active backend: [{ACTIVE_DB_TYPE.upper()}]")


def get_active_db_info() -> dict:
    """Return runtime metadata about the currently active database backend."""
    return {
        "active_backend": ACTIVE_DB_TYPE,
        "is_mysql": ACTIVE_DB_TYPE == "mysql",
        "is_sqlite": ACTIVE_DB_TYPE == "sqlite",
        "mysql_host": MYSQL_HOST if ACTIVE_DB_TYPE == "mysql" else None,
        "mysql_port": MYSQL_PORT if ACTIVE_DB_TYPE == "mysql" else None,
        "mysql_database": MYSQL_DATABASE if ACTIVE_DB_TYPE == "mysql" else None,
        "sqlite_path": DEFAULT_SQLITE_PATH if ACTIVE_DB_TYPE == "sqlite" else None,
    }
