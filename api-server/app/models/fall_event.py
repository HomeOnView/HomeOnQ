from datetime import datetime
from sqlalchemy import String, ForeignKey, Float, DateTime, JSON, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .senior_baseline import JSON_VALUE
from .base import Base, TimestampMixin
class FallEvent(TimestampMixin, Base):
    __tablename__ = "fall_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("fall_sessions.id", ondelete="RESTRICT"), nullable=False)
    event_status: Mapped[str] = mapped_column(String(20), default="SUSPECTED", nullable=False)
    severity: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    __table_args__ = (CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="fall_confidence_range"), CheckConstraint("event_status IN ('SUSPECTED','CONFIRMED','DISMISSED')", name="fall_event_status_valid"), Index("ix_fall_events_session_occurred", "session_id", "occurred_at"))
