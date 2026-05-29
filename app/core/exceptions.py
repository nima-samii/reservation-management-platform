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


class NoChannelAvailableError(ReservationError):
    def __init__(self) -> None:
        super().__init__("No channels are currently available for reservations.")


class RateLimitError(AppError):
    def __init__(self) -> None:
        super().__init__("Too many requests. Please slow down.", "RATE_LIMITED")


class UserNotRegisteredError(AppError):
    def __init__(self) -> None:
        super().__init__("User is not registered.", "NOT_REGISTERED")
