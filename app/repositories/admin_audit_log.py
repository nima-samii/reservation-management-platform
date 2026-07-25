from sqlalchemy import select
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

    async def get_for_entity(
        self, entity_type: str, entity_id: str
    ) -> list[AdminAuditLog]:
        """All audit rows for one entity, oldest first.

        Read-only — used by the reservation timeline builder to attribute
        admin-driven events (creation, no-show) to an operator."""
        stmt = (
            select(AdminAuditLog)
            .where(
                AdminAuditLog.entity_type == entity_type,
                AdminAuditLog.entity_id == entity_id,
            )
            .order_by(AdminAuditLog.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
