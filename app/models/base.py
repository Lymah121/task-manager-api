from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Must be in place BEFORE the first migration. Postgres auto-names unnamed
# constraints (tasks_owner_id_fkey); Alembic cannot emit DROP CONSTRAINT for a
# name it does not know, so retrofitting this later means a churn migration
# renaming every constraint in the schema.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
