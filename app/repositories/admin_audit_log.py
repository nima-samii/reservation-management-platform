from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.admin_audit_log import AdminAuditLog
from app.repositories.base import BaseRepository


class AdminAuditLogRepository(BaseRepository[AdminAuditLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AdminAuditLog, session)

    async def log(
        self,
        action: str,
        admin_username: str = "admin",
        entity_type: str | None = None,
        entity_id: str | None = None,
        details: str | None = None,
        ip_address: str | None = None,
    ) -> AdminAuditLog:
        entry = AdminAuditLog(
            action=action,
            admin_username=admin_username,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address,
        )
        return await self.save(entry)
