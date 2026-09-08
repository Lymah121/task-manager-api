from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine

from app.models import Base


def test_models_match_migrations(engine: Engine):
    """Catches the day someone edits a model and forgets the revision.

    Uses the session-scoped engine rather than the per-test savepoint session
    because compare_metadata reflects the live catalog.
    """
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        diff = compare_metadata(context, Base.metadata)

    assert diff == [], f"Models and migrations have drifted: {diff}"
