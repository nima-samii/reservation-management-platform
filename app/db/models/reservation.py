import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class ReservationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AttendanceStatus(str, Enum):
    """Whether the user actually showed up, as decided by an admin.

    Deliberately independent of the score: every combination of outcome and
    delta is legal (attended +10, attended 0, absent +2). Nothing here implies
    a sign — see ``Reservation.attendance_score_delta``.

    ``ABSENT`` rather than ``NO_SHOW``: the legacy no-show flag lives on in
    ``notes["no_show_penalty_applied"]`` and is read by the dashboard, the
    summaries and broadcast segmentation. The two must stay tellable apart.
    """

    ATTENDED = "attended"
    ABSENT = "absent"


class Reservation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reservations"
    __table_args__ = (
        # Partial unique index: only one ACTIVE reservation per slot.
        # Cancelled/completed rows don't block re-booking the same slot.
        Index(
            "uq_reservations_slot_active",
            "slot_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        # Composite index for the "my active reservations" lookup (migration 0004).
        # Declared here (not via a bare column index=True) so its name matches the
        # index that actually exists in the database.
        Index("ix_reservations_user_status", "user_id", "status"),
        # Partial index backing lifecycle transitions on active rows (migration 0004).
        Index(
            "ix_reservations_active_slot",
            "slot_id",
            postgresql_where=text("status = 'active'"),
        ),
        # Backs the query the attendance feature is built around: completed
        # reservations still awaiting a decision (migration 0015). Plain rather
        # than partial so it serves both directions — Postgres indexes NULLs,
        # and as decided rows accumulate `attendance_status IS NULL` becomes the
        # selective end of a very skewed distribution, which is exactly the
        # lookup the admin queue makes.
        Index("ix_reservations_attendance_status", "attendance_status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reservation_slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=ReservationStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Set when an admin cancels the reservation from the admin panel (Sprint 1).
    # User-initiated cancellations leave these NULL.
    cancelled_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Admin attendance decision (migration 0015) ────────────────────────
    # All five are written together by exactly one conditional UPDATE
    # (ReservationRepository.claim_attendance_decision) and never updated
    # again; `attendance_status IS NULL` is what makes a decision claimable,
    # so it doubles as the at-most-once guard. NULL across the board means no
    # decision has been made — including for every row predating this
    # migration, which is why nothing here is backfilled.
    #
    # A score of 0 is a real decision, so `attendance_score_delta` is 0, not
    # NULL, once decided. Read attendance from these columns, never from
    # `notes` — the legacy no-show flag lives there and means something else.
    attendance_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attendance_score_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attendance_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attendance_marked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attendance_marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="reservations")  # noqa: F821
    slot: Mapped["ReservationSlot"] = relationship(  # noqa: F821
        "ReservationSlot", back_populates="reservation"
    )
    channel: Mapped["Channel"] = relationship("Channel", back_populates="reservations")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Reservation {self.id} status={self.status}>"
