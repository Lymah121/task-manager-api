from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RefreshToken(Base):
    """A refresh token, stored as a hash.

    The raw token is returned to the client once and never persisted. If this
    table leaks, an attacker holds SHA-256 digests of high-entropy random
    strings, which are not usable as credentials -- the same reasoning that
    applies to passwords, minus the need for a slow KDF, because a 256-bit
    random token is not brute-forceable the way a human-chosen password is.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # WHY a token was revoked, not just that it was. Reuse detection must fire
    # only for a token retired by rotation: replaying one the user explicitly
    # logged out is a stale client, not a thief, and burning every other
    # session over it would log the user out of their other devices for free.
    revoked_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_refresh_tokens_user_id_expires_at", "user_id", "expires_at"),)

    def is_usable(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


class RevocationReason:
    ROTATED = "rotated"      # superseded by a refresh; replay means theft
    LOGOUT = "logout"        # user ended this session
    LOGOUT_ALL = "logout_all"
    REUSE_DETECTED = "reuse_detected"
