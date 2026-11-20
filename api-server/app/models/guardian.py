from sqlalchemy import String, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
class Guardian(TimestampMixin, Base):
    __tablename__ = "guardians"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    relationships: Mapped[list["GuardianSenior"]] = relationship(back_populates="guardian", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("email", name="uq_guardians_email"),)
