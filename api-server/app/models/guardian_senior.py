from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
class GuardianSenior(TimestampMixin, Base):
    __tablename__ = "guardian_senior"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guardian_id: Mapped[str] = mapped_column(ForeignKey("guardians.id", ondelete="CASCADE"), nullable=False)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False)
    permission_role: Mapped[str] = mapped_column(String(30), default="viewer", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    guardian: Mapped["Guardian"] = relationship(back_populates="relationships")
    senior: Mapped["Senior"] = relationship(back_populates="guardians")
    __table_args__ = (UniqueConstraint("guardian_id", "senior_id", name="uq_guardian_senior_pair"),)
