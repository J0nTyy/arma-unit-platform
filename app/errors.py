"""Application-wide error hierarchy.

Every expected failure mode gets a typed exception carrying a `user_message`
that is safe to show to end users. Internal details (stack traces, raw driver
errors) belong in logs only — the centralized Discord error handler relies on
this contract.

Discord-specific errors (e.g. permission check failures) live in the bot layer
so this module stays free of interface dependencies.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected application errors."""

    default_user_message = "Something went wrong. The problem has been logged."

    def __init__(self, message: str = "", *, user_message: str | None = None) -> None:
        super().__init__(message or user_message or self.default_user_message)
        self.user_message = user_message or self.default_user_message


class ConfigurationError(AppError):
    """Required configuration is missing or invalid."""

    default_user_message = "The application is misconfigured. Contact an administrator."


class ValidationError(AppError):
    """User-supplied input failed validation."""

    default_user_message = "Invalid input."

    def __init__(self, message: str = "", *, user_message: str | None = None) -> None:
        super().__init__(message, user_message=user_message or message or None)


class DatabaseError(AppError):
    """A database operation failed."""

    default_user_message = "A database error occurred. Please try again later."


class NotFoundError(AppError):
    """A requested resource does not exist."""

    default_user_message = "The requested resource could not be found."


class MissionNotFoundError(NotFoundError):
    def __init__(self, mission_id: str) -> None:
        self.mission_id = mission_id
        super().__init__(
            f"mission {mission_id!r} not found",
            user_message=(
                f"Mission `{mission_id}` could not be found. "
                "If it was added recently, run `/mission sync` first."
            ),
        )


class MissionsNotConfiguredError(AppError):
    """The GitHub mission repository has not been configured."""

    default_user_message = (
        "The mission repository is not configured. An administrator must set "
        "GITHUB_MISSIONS_OWNER and GITHUB_MISSIONS_REPOSITORY."
    )


class ExternalServiceError(AppError):
    """An external service (GitHub, OpenAI, Arma server, ...) failed."""

    default_user_message = "An external service is currently unavailable. Please try again later."


class GitHubIntegrationError(ExternalServiceError):
    default_user_message = "The mission repository is currently unavailable."


class GitHubUnavailableError(GitHubIntegrationError):
    """GitHub could not be reached, or refused the request (auth/rate limit)."""

    default_user_message = (
        "The mission repository is temporarily unavailable. Please try again later."
    )


class GitHubFileNotFoundError(GitHubIntegrationError):
    """A specific path does not exist in the repository."""

    default_user_message = "That file does not exist in the mission repository."


class AIIntegrationError(ExternalServiceError):
    default_user_message = "The AI assistant is currently unavailable."
