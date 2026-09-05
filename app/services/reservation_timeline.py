"""Read-only reservation timeline builder.

Assembles a chronological list of events for a single reservation from data
that already exists in the system. There is **no** timeline persistence — no
events table, no migrations, no write path. Each call re-derives the timeline
from:

  * ``reservations``        — creation and (admin) cancellation
  * ``score_transactions``  — the attendance decision, the retired no-show
                              penalty, and any admin score adjustment
  * ``notification_logs``   — same-day / pre-session reminders
  * ``admin_audit_logs``    — attributes admin-driven events to an operator

Business logic lives here, not in the API controller. The pure assembly step
(:meth:`ReservationTimelineService.assemble`) takes already-fetched rows so it
can be unit-tested without a database.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.admin_audit_log import AdminAuditLog
from app.db.models.notification_log import NotificationLog
from app.db.models.reservation import AttendanceStatus, Reservation, ReservationStatus
from app.db.models.score import ScoreTransaction, ScoreTransactionType
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.notification import NotificationRepository
from app.repositories.reservation import ReservationRepository
from app.repositories.score import ScoreTransactionRepository

# Stable tie-breaker for events that share a timestamp (e.g. an attendance
# decision and its ledger row are written in the same transaction). Lower
# sorts first.
_TYPE_ORDER = {
    "reservation_created": 0,
    "score_awarded": 1,
    "score_adjusted": 1,
    "notification_sent": 2,
    "attendance_recorded": 3,
    "no_show_applied": 3,
    "reservation_cancelled": 4,
}

_REMINDER_TITLES = {
    "same_day": "Same-Day Reminder Sent",
    "pre_session": "Pre-Session Reminder Sent",
    "final": "Final Live Reminder Sent",
}

# Outcome first, because the score cannot express it: an absence may still
# carry points and an attended session may be worth none.
_ATTENDANCE_LABEL = {
    AttendanceStatus.ATTENDED.value: "Attended",
    AttendanceStatus.ABSENT.value: "Did Not Attend",
}


class TimelineEvent(BaseModel):
    """One normalized point on a reservation's read-only timeline.

    Assembled from existing system data (reservations, notification_logs,
    score_transactions, admin_audit_logs) — there is no timeline persistence.
    Doubles as the API response DTO."""

    type: str
    title: str
    timestamp: datetime
    metadata: dict = Field(default_factory=dict)


class ReservationTimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self._res_repo = ReservationRepository(session)
        self._notif_repo = NotificationRepository(session)
        self._score_repo = ScoreTransactionRepository(session)
        self._audit_repo = AdminAuditLogRepository(session)

    async def build(self, reservation_id: uuid.UUID) -> list[TimelineEvent]:
        """Fetch every source and return the reservation's timeline, oldest first.

        Raises :class:`NotFoundError` if the reservation does not exist so the
        endpoint can translate it to a 404.
        """
        reservation = await self._res_repo.get_reservation_admin_detail(reservation_id)
        if reservation is None:
            raise NotFoundError("Reservation")

        notifications = await self._notif_repo.get_for_reservation(reservation_id)
        score_txns = await self._score_repo.get_for_reservation(reservation_id)
        audit_logs = await self._audit_repo.get_for_entity(
            "reservation", str(reservation_id)
        )

        return self.assemble(reservation, notifications, score_txns, audit_logs)

    @staticmethod
    def assemble(
        reservation: Reservation,
        notifications: Sequence[NotificationLog],
        score_txns: Sequence[ScoreTransaction],
        audit_logs: Sequence[AdminAuditLog],
    ) -> list[TimelineEvent]:
        """Pure: normalize the source rows into a sorted list of events.

        No I/O — safe to unit-test with plain objects.
        """
        events: list[TimelineEvent] = []

        # ── Reservation Created ───────────────────────────────────────────
        created_by_admin = next(
            (a for a in audit_logs if a.action == "reservation_created_by_admin"),
            None,
        )
        events.append(
            TimelineEvent(
                type="reservation_created",
                title=(
                    "Reservation Created by Admin"
                    if created_by_admin
                    else "Reservation Created"
                ),
                timestamp=reservation.created_at,
                metadata={
                    "created_by_admin": created_by_admin is not None,
                    **(
                        {"admin": created_by_admin.admin_username}
                        if created_by_admin
                        else {}
                    ),
                },
            )
        )

        # ── Score events (from the immutable ledger) ──────────────────────
        # Every ledger row linked to this reservation produces an event. The
        # branch used to end at `elif tx.score_delta > 0`, which silently
        # dropped anything that was not a gain — including an attendance
        # decision worth 0 or -5, the two cases this feature exists to make
        # possible, and any negative admin adjustment.
        no_show_admin = next(
            (a.admin_username for a in audit_logs if a.action == "no_show_applied"),
            None,
        )
        attendance_admin = next(
            (a.admin_username for a in audit_logs if a.action == "attendance_recorded"),
            None,
        )
        for tx in score_txns:
            if tx.transaction_type == ScoreTransactionType.ATTENDANCE_SCORE.value:
                # The reservation column is authoritative; the ledger row's
                # `meta` mirror is the fallback for a row whose reservation was
                # deleted (reservation_id is ON DELETE SET NULL).
                outcome = reservation.attendance_status or (tx.meta or {}).get(
                    "attendance_status"
                )
                label = _ATTENDANCE_LABEL.get(outcome or "", "Attendance Recorded")
                # `{:+d}` would render a zero decision as "+0"; it is a real
                # outcome and deserves to read as one.
                score_part = f"{tx.score_delta:+d}" if tx.score_delta else "0"
                events.append(
                    TimelineEvent(
                        type="attendance_recorded",
                        title=f"{label} · Score {score_part}",
                        timestamp=tx.created_at,
                        metadata={
                            "attendance_status": outcome,
                            "delta": tx.score_delta,
                            "admin": attendance_admin
                            or reservation.attendance_marked_by,
                            "reason": tx.reason,
                        },
                    )
                )
            elif tx.transaction_type == ScoreTransactionType.NO_SHOW_PENALTY.value:
                events.append(
                    TimelineEvent(
                        type="no_show_applied",
                        title="No Show Applied",
                        timestamp=tx.created_at,
                        metadata={
                            "penalty": tx.score_delta,
                            "admin": no_show_admin,
                            "reason": tx.reason,
                        },
                    )
                )
            else:
                if tx.score_delta > 0:
                    event_type = "score_awarded"
                    title = f"Score +{tx.score_delta} Awarded"
                elif tx.score_delta < 0:
                    event_type = "score_adjusted"
                    title = f"Score {tx.score_delta} Deducted"
                else:
                    event_type = "score_adjusted"
                    title = "Score Reviewed, Unchanged"
                events.append(
                    TimelineEvent(
                        type=event_type,
                        title=title,
                        timestamp=tx.created_at,
                        metadata={
                            "delta": tx.score_delta,
                            "transaction_type": tx.transaction_type,
                            "reason": tx.reason,
                        },
                    )
                )

        # ── Notifications ─────────────────────────────────────────────────
        for n in notifications:
            base = _REMINDER_TITLES.get(n.reminder_type, "Notification Sent")
            failed = n.status == "failed"
            events.append(
                TimelineEvent(
                    type="notification_sent",
                    title=base.replace("Sent", "Failed") if failed else base,
                    timestamp=n.sent_at,
                    metadata={
                        "reminder_type": n.reminder_type,
                        "status": n.status,
                    },
                )
            )

        # ── Reservation Cancelled ─────────────────────────────────────────
        # cancelled_at is set on admin cancellations; user cancellations leave
        # it NULL, so fall back to updated_at when the row is cancelled.
        cancelled_ts: datetime | None = reservation.cancelled_at
        if cancelled_ts is None and reservation.status == ReservationStatus.CANCELLED.value:
            cancelled_ts = reservation.updated_at
        if cancelled_ts is not None:
            events.append(
                TimelineEvent(
                    type="reservation_cancelled",
                    title="Reservation Cancelled",
                    timestamp=cancelled_ts,
                    metadata={
                        "cancelled_by": reservation.cancelled_by,
                        "reason": reservation.cancellation_reason,
                    },
                )
            )

        events.sort(key=lambda e: (e.timestamp, _TYPE_ORDER.get(e.type, 99)))
        return events
