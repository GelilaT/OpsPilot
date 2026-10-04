"""Alembic environment (async, psycopg 3). The database URL comes from app settings / DATABASE_URL."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.settings import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
EXCLUDE_TABLES_PREFIX = ("procrastinate_",)


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
    if type_ == "table" and name and (name.startswith(EXCLUDE_TABLES_PREFIX) or name in AUTH_TABLES):
        return False
    return True


# Tables owned by Better Auth in the web app.
AUTH_TABLES = {"user", "session", "account", "verification", "jwks"}


def url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().owner_database_url


def run_migrations_offline() -> None:
    context.configure(url=url(), target_metadata=target_metadata, literal_binds=True,
                      include_object=include_object, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # noqa: ANN001
    context.configure(connection=connection, target_metadata=target_metadata,
                      include_object=include_object, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
