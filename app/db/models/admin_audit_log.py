from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class AdminAuditLog(Base, UUIDMixin):
    __tablename__ = "admin_audit_logs"

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    admin_username: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AdminAuditLog {self.action} by {self.admin_username}>"
