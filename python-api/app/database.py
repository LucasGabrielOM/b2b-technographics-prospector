import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

logger = logging.getLogger("b2b_prospector")


class Base(DeclarativeBase):
    pass


FALLBACK_SQLITE_URL = "sqlite:///./prospector.db"
is_fallback_db = False
current_db_type = "sqlite"


def create_db_engine(raw_url: str):
    url = raw_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args), url


# Initialize engine with safe fallback handling
target_url = get_settings().database_url
try:
    engine, resolved_url = create_db_engine(target_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    current_db_type = "sqlite" if resolved_url.startswith("sqlite") else "postgresql"
    is_fallback_db = False
except Exception as exc:
    logger.warning(
        "[B2B Prospector DB Warning] Could not connect to primary database at '%s': %s. "
        "Falling back to local SQLite database '%s' to ensure application stays online!",
        target_url,
        exc,
    )
    engine, resolved_url = create_db_engine(FALLBACK_SQLITE_URL)
    current_db_type = "sqlite"
    is_fallback_db = True

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_status() -> tuple[str, bool]:
    """Returns tuple of (db_type, is_fallback_db)."""
    return current_db_type, is_fallback_db


def init_db() -> None:
    """Safely creates tables and ensures columns without throwing unhandled exceptions."""
    global engine, SessionLocal, current_db_type, is_fallback_db
    try:
        Base.metadata.create_all(bind=engine)
        ensure_lead_contact_columns()
    except Exception as exc:
        logger.warning(
            "[B2B Prospector DB Warning] Table creation failed on primary engine: %s. Re-attempting on SQLite fallback.",
            exc,
        )
        engine, resolved_url = create_db_engine(FALLBACK_SQLITE_URL)
        current_db_type = "sqlite"
        is_fallback_db = True
        SessionLocal.configure(bind=engine)
        Base.metadata.create_all(bind=engine)
        ensure_lead_contact_columns()


def ensure_lead_contact_columns() -> None:
    """Small forward-only migration for existing SQLite/PostgreSQL deployments."""
    try:
        inspector = inspect(engine)
        if "leads" not in inspector.get_table_names():
            return
        existing = {column["name"] for column in inspector.get_columns("leads")}
        with engine.begin() as connection:
            for name in ("contact_phone", "contact_whatsapp"):
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE leads ADD COLUMN {name} VARCHAR(40)"))
            additions = {
                "location": "VARCHAR(160)",
                "discovery_source": "VARCHAR(500)",
                "pain_score": "INTEGER DEFAULT 0",
                "pain_summary": "TEXT",
                "pain_source": "VARCHAR(1000)",
                "notes": "TEXT",
                "contact_channel": "VARCHAR(40)",
                "contacted_at": "TIMESTAMP WITH TIME ZONE",
            }
            for name, sql_type in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE leads ADD COLUMN {name} {sql_type}"))
    except Exception as exc:
        logger.warning("[B2B Prospector DB Warning] Column check skipped: %s", exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
