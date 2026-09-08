from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import settings
from app.models import Base  # noqa: F401  -- registers User and Task on Base.metadata

config = context.config

# URL from settings unless a caller (conftest, CI) already set one. The %% escape
# matters because alembic.ini is read by configparser with interpolation on, so a
# password containing '%' -- very likely from a generated RDS password -- would
# otherwise raise InterpolationSyntaxError.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate's source of truth. Without the app.models import above this is
# empty and `alembic revision --autogenerate` silently produces a no-op migration.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Both default to False: without them a String(200) -> String(500) change
        # or an altered server_default is silently ignored by autogenerate.
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
