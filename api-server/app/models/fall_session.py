from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from .senior_baseline import JSON_VALUE
from .base import Base, TimestampMixin
class FallSession(TimestampMixin, Base):
    __tablename__ = "fall_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[str] = mapped_column(ForeignKey("camera_devices.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    __table_args__ = (Index("ix_fall_sessions_senior_started", "senior_id", "started_at"),)
