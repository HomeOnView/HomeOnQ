from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, Float, DateTime, BigInteger, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin
class VideoClip(TimestampMixin, Base):
    __tablename__ = "video_clips"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fall_event_id: Mapped[str] = mapped_column(ForeignKey("fall_events.id", ondelete="CASCADE"), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    upload_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    duration: Mapped[float | None] = mapped_column(Float)
    pre_seconds: Mapped[float | None] = mapped_column(Float)
    post_seconds: Mapped[float | None] = mapped_column(Float)
    checksum: Mapped[str | None] = mapped_column(String(128))
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("file_size IS NULL OR file_size >= 0", name="video_size_nonnegative"), CheckConstraint("duration IS NULL OR duration >= 0", name="video_duration_nonnegative"), Index("ix_video_clips_event", "fall_event_id"))
