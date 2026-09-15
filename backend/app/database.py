"""
SQLite via SQLAlchemy. First real persistence layer in this project --
everything before this (mapping runs, validation) was intentionally
stateless. Templates need to survive across sessions, so this is where
a DB actually earns its complexity.

Swapping to Postgres later is just changing DATABASE_URL and installing
psycopg2 -- no model changes needed.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./mapper.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()