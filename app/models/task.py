import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class TaskStatus(enum.StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


# VARCHAR + CHECK rather than a native Postgres TYPE. Adding a value to a native
# enum needs ALTER TYPE ... ADD VALUE (historically not transaction-safe) and
# removing one is impossible without recreating the type; Alembic autogenerate
# detects neither. Here a value change is an ordinary drop/create of the CHECK.
#
# NOTE: autogenerate cannot see changes to this value list. Adding a status
# requires a hand-written op.drop_constraint + op.create_check_constraint pair.
TASK_STATUS_TYPE = SAEnum(
    TaskStatus,
    name="task_status",
    native_enum=False,  # VARCHAR + CHECK, not CREATE TYPE
    create_constraint=True,  # NOT the default since SQLAlchemy 1.4
    values_callable=lambda cls: [m.value for m in cls],  # store "in_progress", not "IN_PROGRESS"
    length=20,
)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        TASK_STATUS_TYPE, default=TaskStatus.TODO, server_default=TaskStatus.TODO.value
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="tasks")

    __table_args__ = (Index("ix_tasks_owner_id_status", "owner_id", "status"),)
