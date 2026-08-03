from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


_PLATFORMS = frozenset({"bilibili", "xhs", "douyin", "weibo"})


class RuntimeStatus(StrEnum):
    COMPLETE = "complete"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RuntimeStatus
    records: int = 0
    pages: int = 0
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    platform: str
    count: int
    page_cap: int = 20
    uid: str | None = None
    keyword: str | None = None
    complete: bool = False
    comment_limit: int = 0

    def __post_init__(self) -> None:
        if self.platform not in _PLATFORMS:
            raise ValueError("unsupported platform")
        if self.count < 0:
            raise ValueError("count must be nonnegative")
        if self.comment_limit < 0:
            raise ValueError("comment_limit must be nonnegative")
        if self.page_cap < 1:
            raise ValueError("page_cap must be at least 1")
        if (self.uid is None) == (self.keyword is None):
            raise ValueError("provide exactly one of uid or keyword")

    @property
    def target_count(self) -> int | None:
        return None if self.count == 0 else self.count
