from datetime import datetime
from sqlalchemy import String, ForeignKey, Float, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from .senior_baseline import JSON_VALUE
from .base import Base, TimestampMixin
class BehaviorEvent(TimestampMixin, Base):
    __tablename__ = "behavior_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_value: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_value: Mapped[float | None] = mapped_column(Float)
    deviation_percent: Mapped[float | None] = mapped_column(Float)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_quality: Mapped[float | None] = mapped_column(Float)
    analysis_status: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    __table_args__ = (Index("ix_behavior_events_senior_occurred", "senior_id", "occurred_at"),)
