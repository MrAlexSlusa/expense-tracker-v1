import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite for local dev. In production, set DATABASE_URL to a Postgres URL
# (e.g. from Neon) - nothing else in the app needs to change.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./expenses.db")

# Some providers (Neon included) hand out "postgres://" URLs, but SQLAlchemy
# needs the "postgresql://" scheme.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns(*, table: str, columns: dict[str, str]) -> None:
    """
    Adds columns that an already-deployed database is missing.

    `Base.metadata.create_all` creates whole tables but never alters existing
    ones, so a column added to a model after the first deploy would be
    missing in production until something adds it. There's no Alembic setup
    here (one app, additive-only changes so far), so this covers the gap:
    it's idempotent, runs on every boot, and only ever adds nullable columns.
    """
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return  # create_all will build it with every column already present

    existing = {c["name"] for c in inspector.get_columns(table)}
    missing = {name: ddl for name, ddl in columns.items() if name not in existing}
    if not missing:
        return

    with engine.begin() as connection:
        for name, ddl in missing.items():
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
