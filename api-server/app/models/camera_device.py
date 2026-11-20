from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .senior_baseline import JSON_VALUE


class CameraDevice(TimestampMixin, Base):
    __tablename__ = "camera_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id", ondelete="RESTRICT"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 엣지 파이프라인 하트비트(HealthMonitor) 상태를 마지막 값으로 보관한다.
    health_status: Mapped[str | None] = mapped_column(String(30))
    health_metrics: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    senior: Mapped["Senior"] = relationship()

    __table_args__ = (Index("ix_camera_devices_senior_id", "senior_id"),)
