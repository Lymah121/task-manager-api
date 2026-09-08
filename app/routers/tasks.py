from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession, OwnedTask
from app.models import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: DbSession, current_user: CurrentUser) -> Task:
    task = Task(**payload.model_dump(), owner_id=current_user.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[TaskRead])
def list_tasks(
    db: DbSession,
    current_user: CurrentUser,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Task]:
    # Filtered at the source, never post-filtered.
    stmt = select(Task).where(Task.owner_id == current_user.id)
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    stmt = stmt.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task: OwnedTask) -> Task:
    # No task_id parameter and no db session: there is nothing in this body that
    # could load the wrong row.
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(payload: TaskUpdate, task: OwnedTask, db: DbSession) -> Task:
    # exclude_unset distinguishes {"description": null} (clear it) from {} (leave it).
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task: OwnedTask, db: DbSession) -> None:
    db.delete(task)
    db.commit()
