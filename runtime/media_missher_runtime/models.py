from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


_PLATFORMS = frozenset({"bilibili", "xhs", "douyin", "weibo"})
_BROWSER_ASSIST_MODES = frozenset({"off", "browserskill"})
_SCREENSHOT_MODES = frozenset({"off", "opened", "all"})


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
    browser_assist: str = "off"
    screenshot_mode: str = "off"

    def __post_init__(self) -> None:
        if self.platform not in _PLATFORMS:
            raise ValueError("unsupported platform")
        if self.count < 0:
            raise ValueError("count must be nonnegative")
        if self.comment_limit < 0:
            raise ValueError("comment_limit must be nonnegative")
        if self.page_cap < 1:
            raise ValueError("page_cap must be at least 1")
        if self.browser_assist not in _BROWSER_ASSIST_MODES:
            raise ValueError("unsupported browser assist mode")
        if self.screenshot_mode not in _SCREENSHOT_MODES:
            raise ValueError("unsupported screenshot mode")
        if (self.uid is None) == (self.keyword is None):
            raise ValueError("provide exactly one of uid or keyword")
        if self.screenshot_mode == "all" and self.count == 0:
            raise ValueError("screenshot mode all requires a positive count")
        if (
            self.platform == "bilibili"
            and self.keyword is not None
            and (self.browser_assist != "off" or self.screenshot_mode != "off")
        ):
            raise ValueError("Bilibili search advanced modes are not supported")

    @property
    def target_count(self) -> int | None:
        return None if self.count == 0 else self.count
