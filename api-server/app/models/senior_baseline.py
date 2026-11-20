from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, Float, DateTime, JSON, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin
JSON_VALUE = JSON().with_variant(JSONB, "postgresql")
class SeniorBaseline(TimestampMixin, Base):
    __tablename__ = "senior_baselines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False)
    baseline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    learning_status: Mapped[str] = mapped_column(String(30), nullable=False)
    observed_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data_quality: Mapped[float | None] = mapped_column(Float)
    baseline_data: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("senior_id", "baseline_version", name="uq_baseline_senior_version"), CheckConstraint("observed_days >= 0", name="observed_days_nonnegative"), CheckConstraint("data_quality IS NULL OR (data_quality >= 0 AND data_quality <= 1)", name="baseline_quality_range"))
