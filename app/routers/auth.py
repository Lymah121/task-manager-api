from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import DbSession
from app.models import User
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Both login failure modes return this identical message. Asserting against one
# constant in the tests means a future change that starts leaking "no such user"
# breaks the build.
INVALID_CREDENTIALS = "Incorrect email or password"


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: DbSession) -> User:
    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Rely on the unique index rather than a pre-flight SELECT: checking
        # first is a TOCTOU race where two concurrent signups both see "free"
        # and one gets a 500.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered") from exc
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    email = form_data.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))
