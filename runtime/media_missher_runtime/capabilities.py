"""Chrome CDP capabilities by platform, task mode and evidence type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import (
    BACKEND_CDP,
    BACKEND_SET,
    EVIDENCE_PAGE,
    EVIDENCE_RESPONSE,
    LEGACY_PLATFORMS,
    PLATFORM_SET,
    PLATFORMS,
    TASK_MODES,
    TASK_MODE_CREATOR,
    TASK_MODE_SEARCH,
    TASK_MODE_TOPIC,
    TOPIC_KIND_STANDARD,
    TOPIC_KIND_SUPER,
)


class CapabilityError(RuntimeError):
    """Raised when a backend is asked for an operation it does not implement."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


#: Capability flags. ``absent`` means the backend has no such operation at all;
#: consumers must report ``unsupported`` rather than emulate it.
CAPABILITY_NAMES: tuple[str, ...] = (
    "list_records",
    "detail_records",
    "response_body",
    "page_observe",
    "target_html",
    "screenshots",
    "media_assets",
)

SUPPORT_FULL = "full"
SUPPORT_BASIC = "basic"
SUPPORT_ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class Capability:
    """One backend × platform × mode × capability cell."""

    backend: str
    platform: str
    mode: str
    name: str
    support: str
    evidence_level: str
    note: str = ""

    def __post_init__(self) -> None:
        if self.backend not in BACKEND_SET:
            raise ValueError("unsupported backend")
        if self.platform not in PLATFORM_SET:
            raise ValueError("unsupported platform")
        if self.mode not in TASK_MODES:
            raise ValueError("unsupported task mode")
        if self.name not in CAPABILITY_NAMES:
            raise ValueError("unsupported capability name")
        if self.support not in {SUPPORT_FULL, SUPPORT_BASIC, SUPPORT_ABSENT}:
            raise ValueError("unsupported capability level")
        if self.evidence_level not in {EVIDENCE_PAGE, EVIDENCE_RESPONSE}:
            raise ValueError("unsupported evidence level")

    def to_json(self) -> dict[str, str]:
        return {
            "backend": self.backend,
            "platform": self.platform,
            "mode": self.mode,
            "capability": self.name,
            "support": self.support,
            "evidence_level": self.evidence_level,
            "note": self.note,
        }


def _rows(
    backend: str,
    platform: str,
    mode: str,
    *,
    list_records: str,
    detail_records: str,
    response_body: str,
    page_observe: str,
    target_html: str,
    screenshots: str,
    media_assets: str,
    evidence_level: str,
    note: str = "",
) -> tuple[Capability, ...]:
    values = {
        "list_records": list_records,
        "detail_records": detail_records,
        "response_body": response_body,
        "page_observe": page_observe,
        "target_html": target_html,
        "screenshots": screenshots,
        "media_assets": media_assets,
    }
    return tuple(
        Capability(
            backend=backend,
            platform=platform,
            mode=mode,
            name=name,
            support=values[name],
            evidence_level=(
                EVIDENCE_RESPONSE
                if name == "response_body" and values[name] == SUPPORT_FULL
                else evidence_level
            ),
            note=note,
        )
        for name in CAPABILITY_NAMES
    )


def _cdp_rows() -> tuple[Capability, ...]:
    rows: list[Capability] = []
    for platform in LEGACY_PLATFORMS:
        for mode in (TASK_MODE_CREATOR, TASK_MODE_SEARCH):
            rows.extend(
                _rows(
                    BACKEND_CDP,
                    platform,
                    mode,
                    list_records=SUPPORT_FULL,
                    detail_records=SUPPORT_FULL,
                    response_body=SUPPORT_FULL,
                    page_observe=SUPPORT_FULL,
                    target_html=SUPPORT_BASIC,
                    screenshots=SUPPORT_FULL,
                    media_assets=SUPPORT_BASIC,
                    evidence_level=EVIDENCE_RESPONSE,
                    note="attached Playwright page with exact-request response observation",
                )
            )
        # weibo has a real topic row appended after the per-platform loop.
        if platform != "weibo":
            rows.extend(
                _rows(
                    BACKEND_CDP,
                    platform,
                    TASK_MODE_TOPIC,
                    list_records=SUPPORT_ABSENT,
                    detail_records=SUPPORT_ABSENT,
                    response_body=SUPPORT_ABSENT,
                    page_observe=SUPPORT_FULL,
                    target_html=SUPPORT_BASIC,
                    screenshots=SUPPORT_ABSENT,
                    media_assets=SUPPORT_ABSENT,
                    evidence_level=EVIDENCE_PAGE,
                    note="topics are defined for weibo only",
                )
            )
    for mode in (TASK_MODE_CREATOR, TASK_MODE_SEARCH, TASK_MODE_TOPIC):
        rows.extend(
            _rows(
                BACKEND_CDP,
                "x",
                mode,
                list_records=SUPPORT_FULL,
                detail_records=SUPPORT_FULL,
                response_body=SUPPORT_FULL,
                page_observe=SUPPORT_FULL,
                target_html=SUPPORT_BASIC,
                screenshots=SUPPORT_BASIC,
                media_assets=SUPPORT_BASIC,
                evidence_level=EVIDENCE_RESPONSE,
                note="response bodies are bound to the exact observed request only",
            )
        )
    rows.extend(
        _rows(
            BACKEND_CDP,
            "weibo",
            TASK_MODE_TOPIC,
            list_records=SUPPORT_FULL,
            detail_records=SUPPORT_FULL,
            response_body=SUPPORT_FULL,
            page_observe=SUPPORT_FULL,
            target_html=SUPPORT_BASIC,
            screenshots=SUPPORT_ABSENT,
            media_assets=SUPPORT_BASIC,
            evidence_level=EVIDENCE_RESPONSE,
            note="standard topic pages and public user homepages",
        )
    )
    return tuple(rows)





def _deduplicate(rows: tuple[Capability, ...]) -> tuple[Capability, ...]:
    """One cell per backend x platform x mode x capability.

    A duplicate would make :func:`capability` return whichever row happened to be
    appended first, so a conflicting definition fails loudly instead.
    """

    seen: dict[tuple[str, str, str, str], Capability] = {}
    for item in rows:
        key = (item.backend, item.platform, item.mode, item.name)
        existing = seen.get(key)
        if existing is not None and existing.support != item.support:
            raise ValueError(f"conflicting capability definition: {key}")
        seen[key] = item
    return tuple(seen.values())


_MATRIX: tuple[Capability, ...] = _deduplicate(_cdp_rows())

#: Topics that this build can actually execute per platform. Standard weibo
#: topics are supported; super topics need a different page contract.
SUPPORTED_TOPIC_KINDS: dict[str, frozenset[str]] = {
    "weibo": frozenset({TOPIC_KIND_STANDARD}),
}


def capability(
    backend: str, platform: str, mode: str, name: str
) -> Capability | None:
    for item in _MATRIX:
        if (
            item.backend == backend
            and item.platform == platform
            and item.mode == mode
            and item.name == name
        ):
            return item
    return None


def support_level(backend: str, platform: str, mode: str, name: str) -> str:
    item = capability(backend, platform, mode, name)
    return item.support if item is not None else SUPPORT_ABSENT


def supported(backend: str, platform: str, mode: str, name: str) -> bool:
    return support_level(backend, platform, mode, name) != SUPPORT_ABSENT


def evidence_level(backend: str, platform: str, mode: str) -> str:
    """Return the evidence level every record from this combination carries."""

    for item in _MATRIX:
        if item.backend == backend and item.platform == platform and item.mode == mode:
            if item.name == "response_body" and item.support == SUPPORT_FULL:
                return EVIDENCE_RESPONSE
            if item.name == "list_records" and item.support != SUPPORT_ABSENT:
                return item.evidence_level
    return EVIDENCE_PAGE


def require(backend: str, platform: str, mode: str, name: str) -> Capability:
    if backend not in BACKEND_SET:
        raise CapabilityError("unsupported-backend")
    if platform not in PLATFORM_SET:
        raise CapabilityError("unsupported-platform")
    if mode not in TASK_MODES:
        raise CapabilityError("unsupported-mode")
    item = capability(backend, platform, mode, name)
    if item is None or item.support == SUPPORT_ABSENT:
        raise CapabilityError(f"{backend}-{platform}-{mode}-{name}-unsupported")
    return item


def require_task(backend: str, platform: str, mode: str) -> Capability:
    """Reject a task the frozen backend cannot execute at all."""

    if mode == TASK_MODE_TOPIC:
        allowed = SUPPORTED_TOPIC_KINDS.get(platform, frozenset())
        if not allowed:
            raise CapabilityError("topic-unsupported-platform")
    return require(backend, platform, mode, "list_records")


def backend_capability_matrix(backend: str) -> tuple[dict[str, str], ...]:
    if backend not in BACKEND_SET:
        raise CapabilityError("unsupported-backend")
    return tuple(item.to_json() for item in _MATRIX if item.backend == backend)


def capability_matrix() -> tuple[dict[str, str], ...]:
    return tuple(item.to_json() for item in _MATRIX)


def platforms_for(backend: str, mode: str) -> tuple[str, ...]:
    return tuple(
        platform
        for platform in PLATFORMS
        if supported(backend, platform, mode, "list_records")
    )


def describe(backend: str, platform: str, mode: str) -> dict[str, str]:
    """Compact, model-safe summary of one capability cell."""

    level = evidence_level(backend, platform, mode)
    supported_names: Iterable[str] = (
        name
        for name in CAPABILITY_NAMES
        if supported(backend, platform, mode, name)
    )
    return {
        "backend": backend,
        "platform": platform,
        "mode": mode,
        "evidence_level": level,
        "capabilities": ",".join(sorted(supported_names)),
    }


__all__ = [
    "CAPABILITY_NAMES",
    "Capability",
    "CapabilityError",
    "SUPPORT_ABSENT",
    "SUPPORT_BASIC",
    "SUPPORT_FULL",
    "SUPPORTED_TOPIC_KINDS",
    "backend_capability_matrix",
    "capability",
    "capability_matrix",
    "describe",
    "evidence_level",
    "platforms_for",
    "require",
    "require_task",
    "support_level",
    "supported",
]
