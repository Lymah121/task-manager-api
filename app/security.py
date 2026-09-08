from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.config import settings

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _password_hash.verify(plain_password, hashed_password)


def create_access_token(subject: int, expires_delta: timedelta | None = None) -> str:
    """Mint an access token. expires_delta exists so tests can mint an already
    expired token without sleeping or freezing the clock."""
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    # 'sub' must be a string: RFC 7519 requires it and PyJWT >= 2.10 raises
    # InvalidSubjectError otherwise.
    payload = {"sub": str(subject), "iat": now, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        # Never omit: an unpinned algorithm list is what enables alg=none and
        # HS/RS key-confusion attacks.
        algorithms=[settings.jwt_algorithm],
    )
