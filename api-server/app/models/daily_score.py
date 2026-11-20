from datetime import date, datetime
from sqlalchemy import String, ForeignKey, Date, Integer, JSON, DateTime, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .senior_baseline import JSON_VALUE
from .base import Base, TimestampMixin
class DailyScore(TimestampMixin, Base):
    __tablename__ = "daily_scores"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False)
    score_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    ui_color: Mapped[str] = mapped_column(String(20), nullable=False)
    influencing_factors: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    data_status: Mapped[str] = mapped_column(String(30), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("senior_id", "score_date", name="uq_daily_score_senior_date"), CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"))
