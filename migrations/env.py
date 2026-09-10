"""Alembic environment for the version-2 schema.

The target database comes from DATABASE_URL, or from a URL the caller places in
the Alembic config as ``sqlalchemy.url`` (which the migration tests do, so a
test can point a run at a throwaway file or a PostgreSQL instance without
touching process environment).
"""
from alembic import context

from api.servicedesk.db.models import Base
from api.servicedesk.db.session import database_url, make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url", None) or database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
