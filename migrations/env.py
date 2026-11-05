"""Alembic environment: uses an explicit DATABASE_URL or PG* variables.

No schema is created on import. Migrations run only when invoked deliberately.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from marine_evidence.db_connection import database_url_from_env
from marine_evidence.db_models import Base

config = context.config
if config.config_file_name and config.get_section(config.config_ini_section, {}).get("loggers"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migration_url():
    url = database_url_from_env()
    return url.render_as_string(hide_password=False) if hasattr(url, "render_as_string") else url


def run_migrations_offline():
    context.configure(url=migration_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = migration_url()
    engine = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
