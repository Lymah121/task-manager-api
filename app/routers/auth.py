from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, DbSession
from app.models import RefreshToken, User
from app.models.refresh_token import RevocationReason
from app.schemas.token import RefreshRequest, TokenPair
from app.schemas.user import UserCreate, UserRead
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Both login failure modes return this identical message. Asserting against one
# constant in the tests means a future change that starts leaking "no such user"
# breaks the build.
INVALID_CREDENTIALS = "Incorrect email or password"
INVALID_REFRESH = "Invalid or expired refresh token"


def _issue_token_pair(db: DbSession, user: User) -> TokenPair:
    raw, hashed = generate_refresh_token()
    db.add(
        RefreshToken(user_id=user.id, token_hash=hashed, expires_at=refresh_token_expiry())
    )
    db.commit()
    return TokenPair(access_token=create_access_token(user.id), refresh_token=raw)


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: DbSession) -> User:
    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Rely on the unique index rather than a pre-flight SELECT: checking
        # first is a TOCTOU race where two simultaneous signups both see "free"
        # and one gets a 500.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered") from exc
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> TokenPair:
    email = form_data.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_token_pair(db, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    """Exchange a refresh token for a new pair, rotating the old one.

    Rotation with reuse detection: each refresh token is single-use. Presenting
    one that has already been revoked means either a replay or that a token was
    stolen and used by both parties -- and since we cannot tell which holder is
    legitimate, every token for that user is revoked, forcing a fresh login.
    Losing a session is a far better outcome than leaving a thief with one.
    """
    now = datetime.now(UTC)
    token_hash = hash_refresh_token(payload.refresh_token)
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_REFRESH)

    if token.revoked_at is not None:
        if token.revoked_reason != RevocationReason.ROTATED:
            # Revoked by an explicit logout. Replaying it is a stale client,
            # not evidence of theft -- do not punish their other devices.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_REFRESH)

        # A token already superseded by rotation is being presented again:
        # either a replay, or a thief and the real user both hold it. We cannot
        # tell which caller is genuine, so the whole family is burned.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == token.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=RevocationReason.REUSE_DETECTED)
        )
        db.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected; all sessions revoked",
        )

    if token.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_REFRESH)

    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_REFRESH)

    token.revoked_at = now  # single use
    token.revoked_reason = RevocationReason.ROTATED
    return _issue_token_pair(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: DbSession) -> None:
    """Revoke one refresh token.

    The access token stays valid until it expires -- that is the accepted
    trade-off of stateless JWTs, and it is why the access lifetime is 15
    minutes rather than hours.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if token is not None and token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        token.revoked_reason = RevocationReason.LOGOUT
        db.commit()


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(db: DbSession, current_user: CurrentUser) -> None:
    """Revoke every session for the caller. The 'I lost my laptop' button."""
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == current_user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revoked_reason=RevocationReason.LOGOUT_ALL)
    )
    db.commit()
