"""Validate Chrome CDP requests before importing or starting a browser."""

from __future__ import annotations

from .capabilities import CapabilityError, require_task
from .contracts import ContractError, normalize_backend


class PreconditionLikeError(RuntimeError):
    """A fixed precondition code with no private request or platform text."""

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("precondition code must be a non-empty string")
        self.code = code
        super().__init__(code)


def backend_for(
    request_or_plan: object = None,
    profile: object = None,
    *,
    legacy_assist: object = None,
) -> str:
    """Accept CDP only, preserving request precedence and retirement errors."""

    explicit = getattr(request_or_plan, "backend", None)
    preference = profile.get("backend") if isinstance(profile, dict) else profile
    try:
        return normalize_backend(explicit, preference=preference, legacy_assist=legacy_assist)
    except ContractError as error:
        raise ValueError(str(error)) from error


def ensure_supported(backend: str, platform: str, mode: str) -> None:
    """Reject unsupported CDP platform/mode combinations before browser actions."""

    try:
        require_task(backend, platform, mode)
    except CapabilityError as error:
        raise PreconditionLikeError(error.code) from error
