"""Sprint-1 quick-segment audience resolver.

Kept for backward compatibility: it now delegates to the Sprint-2
SegmentationService via quick_segment_to_filter, so the three quick segments
(all_users / active_users / users_with_reservations) resolve through the exact
same engine — no duplicated filtering logic.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.segmentation import SegmentationService, quick_segment_to_filter


class AudienceResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._engine = SegmentationService(session)

    async def count(self, audience_type: str) -> int:
        """Number of users matching the quick segment.

        Raises ValueError for an unknown audience (propagated from
        quick_segment_to_filter).
        """
        return await self._engine.count(quick_segment_to_filter(audience_type))

    async def fetch_recipients(self, audience_type: str) -> list[tuple[uuid.UUID, int]]:
        """Return (user_id, telegram_id) tuples for every matching user."""
        return await self._engine.fetch_recipients(quick_segment_to_filter(audience_type))
