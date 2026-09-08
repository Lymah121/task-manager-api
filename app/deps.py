from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Task, User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

DbSession = Annotated[Session, Depends(get_db)]

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    db: DbSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        # InvalidTokenError is the base class for ExpiredSignatureError,
        # DecodeError, InvalidSignatureError and InvalidSubjectError, so
        # malformed / tampered / expired all collapse into one indistinguishable
        # 401. Never tell a caller *why* their token failed.
        raise CREDENTIALS_ERROR from exc

    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_ERROR
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_owned_task(task_id: int, db: DbSession, current_user: CurrentUser) -> Task:
    """The ONLY place in this codebase that loads a Task by id.

    Ownership is part of the WHERE clause, not a check performed afterwards, so
    there is no point in execution at which a Task belonging to someone else
    exists in a variable that could be returned by mistake.

    Returns 404 rather than 403 for another user's task: a 403 would confirm the
    row exists, letting an authenticated caller walk the ID space and map out
    other users' data without reading any of it.
    """
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == current_user.id))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


OwnedTask = Annotated[Task, Depends(get_owned_task)]
