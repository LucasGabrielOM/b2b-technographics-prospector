from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


database_url = get_settings().database_url
engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_lead_contact_columns() -> None:
    """Small forward-only migration for existing SQLite/PostgreSQL deployments."""
    inspector = inspect(engine)
    if "leads" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("leads")}
    with engine.begin() as connection:
        for name in ("contact_phone", "contact_whatsapp"):
            if name not in existing:
                connection.execute(text(f"ALTER TABLE leads ADD COLUMN {name} VARCHAR(40)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
