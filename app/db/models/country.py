from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class Country(Base, UUIDMixin):
    __tablename__ = "countries"
    __table_args__ = (
        UniqueConstraint("code", name="uq_countries_code"),
        UniqueConstraint("name", name="uq_countries_name"),
    )

    code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flag_emoji: Mapped[str] = mapped_column(String(10), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list["User"]] = relationship("User", back_populates="country_rel")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Country {self.code}: {self.name}>"
