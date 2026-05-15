import uuid
from enum import Enum

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NOT_SAY = "not_say"


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        UniqueConstraint("public_user_code", name="uq_users_public_code"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    public_user_code: Mapped[str] = mapped_column(String(6), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("countries.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    country_rel: Mapped["Country"] = relationship("Country", back_populates="users")  # noqa: F821
    reservations: Mapped[list["Reservation"]] = relationship(  # noqa: F821
        "Reservation", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # noqa: F821
        "AuditLog", back_populates="user"
    )

    def __repr__(self) -> str:
        return f"<User {self.public_user_code}: {self.full_name}>"
