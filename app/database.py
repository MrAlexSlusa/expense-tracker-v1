import os

from sqlalchemy import create_engine
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
