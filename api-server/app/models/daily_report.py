from datetime import date, datetime

from sqlalchemy import (
    String, ForeignKey, Integer, Date, Text, DateTime, JSON, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin
from .senior_baseline import JSON_VALUE


class DailyReport(TimestampMixin, Base):
    """파이프라인이 생성한 안심 일일 리포트.

    점수 산식은 아직 확정 전이므로(PoC) 점수와 문장을 함께 저장하되,
    산식 버전을 policy_version 대신 source/model_name/data_status로 남긴다.
    """

    __tablename__ = "daily_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    senior_id: Mapped[str] = mapped_column(
        ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    risk_label: Mapped[str] = mapped_column(String(20), default="확인 필요", nullable=False)
    ui_color: Mapped[str] = mapped_column(String(20), default="#64748b", nullable=False)
    headline: Mapped[str | None] = mapped_column(String(200))
    narrative: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    factors: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    data_status: Mapped[str] = mapped_column(String(30), default="RECEIVED", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="pipeline-rule", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(80))
    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("senior_id", "report_date", name="uq_daily_report_senior_date"),
        Index("ix_daily_reports_senior_date", "senior_id", "report_date"),
    )
