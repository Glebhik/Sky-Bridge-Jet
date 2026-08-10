from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import URL

from alembic import context
from sky_bridge_jet.core.config import get_settings
from sky_bridge_jet.db.base import Base
from sky_bridge_jet.db.model_discovery import import_domain_models

config = context.config
import_domain_models()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Render a connection URL for Alembic without logging it."""
    configured_url = get_settings().database_url_for_sync
    if isinstance(configured_url, URL):
        return configured_url.render_as_string(hide_password=False)
    return configured_url


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with the configured synchronous SQLAlchemy engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
