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
    def __init__(self) -> None:
        super().__init__("You already have a reservation for this day.")


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
