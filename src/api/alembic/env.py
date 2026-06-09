import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.config import settings
from app.database import Base
from app.models import kiosk  # noqa: F401 — registers model with Base.metadata
from app.models import node_token  # noqa: F401
from app.models import playlist  # noqa: F401
from app.models import command_log  # noqa: F401
from app.models import node_meta  # noqa: F401
from app.models import hardware_detect_log  # noqa: F401
from app.models import feature_flag  # noqa: F401
from app.models import app_setting  # noqa: F401
from app.models import saved_url  # noqa: F401
from app.models import api_key  # noqa: F401

target_metadata = Base.metadata


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url)

    async def _run():
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await engine.dispose()

    asyncio.run(_run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
