from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin

class AuthSession(TimestampMixin, Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guardian_id: Mapped[str] = mapped_column(ForeignKey('guardians.id', ondelete='CASCADE'), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[str | None] = mapped_column(String(36))
    __table_args__ = (Index('ix_auth_sessions_guardian_id', 'guardian_id'),)
