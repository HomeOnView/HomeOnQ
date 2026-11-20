from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, DateTime, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin
class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fall_event_id: Mapped[str] = mapped_column(ForeignKey("fall_events.id", ondelete="CASCADE"), nullable=False)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("guardians.id", ondelete="RESTRICT"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (UniqueConstraint("fall_event_id", "alert_type", "recipient_id", name="uq_notification_event_type_recipient"), CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"), Index("ix_notifications_status_created", "status", "created_at"))
