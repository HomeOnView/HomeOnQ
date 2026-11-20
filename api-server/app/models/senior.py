from datetime import date

from sqlalchemy import String, Date, Boolean, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .senior_baseline import JSON_VALUE


class Senior(TimestampMixin, Base):
    """돌봄 대상 어르신. 프로필 필드는 보호자 앱에서 조회·수정한다."""

    __tablename__ = "seniors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- 보호자 앱 프로필 (stage 5에서 추가) ---
    gender: Mapped[str | None] = mapped_column(String(10))
    height_cm: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    medical_conditions: Mapped[list] = mapped_column(JSON_VALUE, default=list, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(1024))
    emergency_contact: Mapped[str | None] = mapped_column(String(40))
    memo: Mapped[str | None] = mapped_column(Text)

    guardians: Mapped[list["GuardianSenior"]] = relationship(
        back_populates="senior", cascade="all, delete-orphan"
    )
