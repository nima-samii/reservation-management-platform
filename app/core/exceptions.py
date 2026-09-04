from typing import Optional


class AppError(Exception):
    """Base application exception."""

    def __init__(self, message: str, code: str = "APP_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: Optional[str] = None) -> None:
        msg = f"{resource} not found"
        if identifier:
            msg = f"{resource} '{identifier}' not found"
        super().__init__(msg, "NOT_FOUND")


class AlreadyExistsError(AppError):
    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} already exists", "ALREADY_EXISTS")


class ValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "VALIDATION_ERROR")


class ReservationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "RESERVATION_ERROR")


class SlotUnavailableError(ReservationError):
    def __init__(self) -> None:
        super().__init__("This time slot is no longer available.")


class DailyLimitError(ReservationError):
    """Raised when a booking would exceed the per-day cap for that user.

    The default of 1 keeps every existing call site and test working, and makes
    the singular wording the fallback rather than something a caller has to
    remember to ask for.
    """

    def __init__(self, max_per_day: int = 1) -> None:
        # "a maximum of 1 reservations" is not a sentence — at the default cap
        # the rule is better stated as the fact the user has already hit it.
        if max_per_day <= 1:
            message = "You already have a reservation for this day."
        else:
            message = (
                f"You have reached the maximum of {max_per_day} reservations "
                "for this day."
            )
        super().__init__(message)
        self.max_per_day = max_per_day


class DuplicateSlotTimeError(ReservationError):
    """Raised when a booking would give one user two sessions at the same instant.

    Slots are unique per ``(slot_datetime, channel_id)``, so one clock time
    exists as one row per channel. Nothing stopped a user from taking two of
    them — they are different rows, each free, each within the daily cap once
    that cap is above 1. They are also the same hour of the same evening, and
    nobody can attend two live sessions at once.

    Distinct from :class:`SlotUnavailableError`: the slot really is free, it
    just runs at a time this user is already booked for.

    Unlike the daily and active caps this is not configurable. It is not a
    policy dial but a fact about the user — there is no setting at which
    being in two places at once becomes possible.
    """

    def __init__(self, local_time: str | None = None) -> None:
        at = f" at {local_time}" if local_time else " at this time"
        super().__init__(
            f"You already have a reservation{at}. Please choose a different time."
        )
        self.local_time = local_time


class MaxReservationsError(ReservationError):
    def __init__(self, max_count: int) -> None:
        super().__init__(
            f"You have reached the maximum of {max_count} active reservations."
        )


class PastSlotError(ReservationError):
    def __init__(self) -> None:
        super().__init__("Cannot reserve a slot in the past.")


def _format_cutoff(cutoff: "str | int") -> str:
    """Render a cutoff as HH:MM, tolerating a legacy bare-hour int."""
    if isinstance(cutoff, int) and not isinstance(cutoff, bool):
        return f"{cutoff:02d}:00"
    return str(cutoff)


class SameDayCutoffError(ReservationError):
    def __init__(self, cutoff_time: "str | int" = "12:00") -> None:
        super().__init__(
            f"Same-day reservations are closed after {_format_cutoff(cutoff_time)}."
        )


class CancellationCutoffError(ReservationError):
    def __init__(self, cutoff_time: "str | int" = "12:00") -> None:
        super().__init__(
            f"Same-day cancellations are closed after {_format_cutoff(cutoff_time)}."
        )


class ReservationNotCancellableError(ReservationError):
    """Raised when a cancellation is attempted on a non-ACTIVE reservation."""

    def __init__(self, current_status: str) -> None:
        super().__init__(
            f"Only active reservations can be cancelled (current status: {current_status})."
        )
        self.current_status = current_status


class AttendanceNotDecidableError(ReservationError):
    """Raised when an attendance decision is attempted on a non-COMPLETED row.

    An active reservation has not happened yet and a cancelled one never will,
    so neither can be judged. Note that a reservation whose slot has just
    passed is still ACTIVE until the lifecycle job promotes it (:00/:30), and
    lands here — hence the status in the message, which is the only thing that
    explains the wait.
    """

    def __init__(self, current_status: str) -> None:
        # Normalised because callers hand this either a raw status string read
        # back from the database or a ReservationStatus member, and a
        # (str, Enum) member interpolates as "ReservationStatus.EXPIRED" — not
        # something to show an admin.
        current_status = getattr(current_status, "value", current_status)
        super().__init__(
            "Attendance can only be recorded for completed reservations "
            f"(current status: {current_status})."
        )
        self.current_status = current_status


class AttendanceAlreadyRecordedError(ReservationError):
    """Raised when a reservation already carries an attendance decision.

    Decisions are immutable — the score has been applied and the user has been
    told. A correction is a new admin score adjustment on the user, not an
    edit here.
    """

    def __init__(self) -> None:
        super().__init__(
            "Attendance has already been recorded for this reservation."
        )


class LegacyNoShowRecordedError(ReservationError):
    """Raised when the reservation already carries the legacy no-show penalty.

    The two mechanisms score the same session, so allowing both would charge
    the user twice for one absence. They cannot be merged either: the legacy
    flag lives in ``notes["no_show_penalty_applied"]``, always means -1, and is
    still read by the dashboard, the summaries and broadcast segmentation.

    Distinct from :class:`AttendanceAlreadyRecordedError` because the remedy is
    different — there is no attendance decision to point at, only an older
    penalty, and an admin who wants a different number applies a score
    adjustment on the user.
    """

    def __init__(self) -> None:
        super().__init__(
            "A no-show penalty was already applied to this reservation under "
            "the previous system, so an attendance decision would score the "
            "same session twice."
        )


class NoChannelAvailableError(ReservationError):
    def __init__(self) -> None:
        super().__init__("No channels are currently available for reservations.")


class UserBannedError(ReservationError):
    """Raised when a reservation is attempted for a banned user."""

    def __init__(self) -> None:
        super().__init__("Cannot create a reservation for a banned user.")


class UnsupportedReservationStrategyError(AppError):
    """Raised when RESERVATION_STRATEGY names a strategy that cannot be built.

    Deliberately fatal rather than falling back to a default: a strategy that
    is configured but unusable must surface as an error, never as silently
    different booking behaviour.
    """

    def __init__(self, strategy: str, reason: str) -> None:
        super().__init__(
            f"Reservation strategy {strategy!r} cannot be used: {reason}.",
            "UNSUPPORTED_STRATEGY",
        )
        self.strategy = strategy


class RateLimitError(AppError):
    def __init__(self) -> None:
        super().__init__("Too many requests. Please slow down.", "RATE_LIMITED")


class UserNotRegisteredError(AppError):
    def __init__(self) -> None:
        super().__init__("User is not registered.", "NOT_REGISTERED")
