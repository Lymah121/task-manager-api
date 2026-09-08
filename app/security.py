import hashlib
import secrets
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


def generate_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash).

    The raw value goes to the client exactly once; only the hash is stored.
    SHA-256 without a slow KDF is correct here: unlike a password, this is 256
    bits of CSPRNG output, so there is no dictionary to run against it.
    """
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
