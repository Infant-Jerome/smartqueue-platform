"""Shared API exceptions (Phase 1 foundation).

All errors use a consistent ``{"success": False, "message": ..., "data": None}``
shape via the handlers in ``app.main``. These classes add typed,
importable errors so Phase 2 (auth, appointment engine) can raise domain
errors without scattering raw HTTPException literals.
"""
from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base typed HTTP error with a stable message payload."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail: str = "Internal server error"

    def __init__(self, detail: str | None = None, headers: dict | None = None):
        super().__init__(
            status_code=self.status_code,
            detail=detail or self.default_detail,
            headers=headers,
        )


class BadRequestException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Bad request"


class UnauthorizedException(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Not authenticated"


class ForbiddenException(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Insufficient permissions"


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Resource not found"


class ConflictException(AppException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Resource conflict"


class UnprocessableException(AppException):
    status_code = 422
    default_detail = "Invalid request"


class ServiceUnavailableException(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Service unavailable"


# Domain shortcuts for Phase 2 (auth, appointment engine).
class InvalidCredentialsException(UnauthorizedException):
    default_detail = "Invalid email or password"


class EmailAlreadyRegisteredException(ConflictException):
    default_detail = "Email already registered"


class SlotAlreadyBookedException(ConflictException):
    default_detail = "Time slot already booked"
