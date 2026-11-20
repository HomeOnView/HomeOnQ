from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, Float, DateTime, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .senior_baseline import JSON_VALUE
from .base import Base, TimestampMixin
class FallLearningSequence(TimestampMixin, Base):
    __tablename__ = "fall_learning_sequences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("fall_sessions.id", ondelete="CASCADE"), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    coordinate_system: Mapped[str] = mapped_column(String(40), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(30))
    fps: Mapped[float | None] = mapped_column(Float)
    joint_data: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False)
    torso_tilt_angle: Mapped[float | None] = mapped_column(Float)
    vertical_speed: Mapped[float | None] = mapped_column(Float)
    label: Mapped[str | None] = mapped_column(String(30))
    data_source: Mapped[str] = mapped_column(String(30), nullable=False)
    data_quality: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("session_id", "frame_index", name="uq_sequence_session_frame"), CheckConstraint("frame_index >= 0", name="frame_index_nonnegative"), CheckConstraint("fps IS NULL OR fps > 0", name="fps_positive"), Index("ix_sequences_session_timestamp", "session_id", "timestamp"))
