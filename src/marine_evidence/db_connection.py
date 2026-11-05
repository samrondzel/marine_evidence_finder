"""Small database connection helper for future CorpusStore integration."""
from __future__ import annotations

import os

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine


def database_url_from_env() -> URL | str:
    """Prefer DATABASE_URL when supplied; otherwise build a safely quoted PG URL.

    PG* variables are standard PostgreSQL client environment variables.
    Explicit construction handles special characters in passwords correctly.
    """
    raw = os.environ.get("DATABASE_URL")
    if raw:
        return raw
    password = os.environ.get("PGPASSWORD")
    if not password:
        raise RuntimeError("Set DATABASE_URL or PGPASSWORD before connecting to PostgreSQL")
    return URL.create(
        drivername="postgresql+psycopg",
        username=os.environ.get("PGUSER", "marine_evidence"),
        password=password,
        host=os.environ.get("PGHOST", "db"),
        port=int(os.environ.get("PGPORT", "5432")),
        database=os.environ.get("PGDATABASE", "marine_evidence"),
    )


def make_engine() -> Engine:
    return create_engine(database_url_from_env(), pool_pre_ping=True)
