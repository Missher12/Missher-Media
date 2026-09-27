"""The legacy single-request shape, extended with the versioned plan fields.

The controller-facing :class:`CollectionRequest` stays the one-request-per-
platform shape the four legacy collectors already consume. It now also carries
the frozen backend, the count mode, the bounded ``best_effort`` budget and an
optional :class:`~media_missher_runtime.contracts.CollectionPlan` so a caller
that has a plan can hand it over without a second bespoke structure.

Compatibility rules kept deliberately:

* ``browser_assist`` / ``screenshot_mode`` keep their stored values, but
  ``browser_assist="browserskill"`` is the deprecated CDP bridge. It is not a
  backend, so it is rejected with a fixed, model-safe reason instead of being
  silently remapped onto the BrowserSkill backend.
* ``platform`` is the shared tuple from :mod:`contracts`, so X is a first-class
  platform here and no local copy of the platform list can drift away from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .contracts import (
    BACKEND_SET,
    COUNT_MODE_BEST_EFFORT,
    COUNT_MODE_FIXED,
    COUNT_MODE_SET,
    DEFAULT_BACKEND,
    PLATFORMS,
    TASK_MODE_CREATOR,
    TASK_MODE_SEARCH,
    TASK_MODE_TOPIC,
    TOPIC_KINDS,
    TOPIC_KIND_STANDARD,
    CollectionPlan,
)
from .xhs_policy import MAX_BATCH_NOTES, MAX_BATCH_PAGES


#: The one shared platform list; the four legacy collectors plus X.
_PLATFORMS = frozenset(PLATFORMS)
#: Platforms that define topic tasks. Topics are a Weibo page contract only.
_TOPIC_PLATFORMS = frozenset({"weibo"})
_BROWSER_ASSIST_MODES = frozenset({"off"})
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
    exclude_ids: tuple[str, ...] = ()
    backend: str = DEFAULT_BACKEND
    count_mode: str = COUNT_MODE_FIXED
    best_effort_budget: int | None = None
    plan: CollectionPlan | None = None
    topic_kind: str | None = None
    topic: str | None = None
    batch_limit: int | None = None
    known_user_ids: tuple[str, ...] = ()
    continue_page: bool = False
    sort: str | None = None

    def __post_init__(self) -> None:
        if self.platform not in _PLATFORMS:
            raise ValueError("unsupported platform")
        if self.sort not in {None, "latest", "top"}:
            raise ValueError("unsupported search sort")
        if not isinstance(self.backend, str) or self.backend not in BACKEND_SET:
            raise ValueError(
                "automatic backend switching is not supported"
                if self.backend == "auto"
                else "unsupported backend"
            )
        if self.count_mode not in COUNT_MODE_SET:
            raise ValueError("unsupported count mode")
        if self.best_effort_budget is not None and (
            isinstance(self.best_effort_budget, bool)
            or not isinstance(self.best_effort_budget, int)
            or self.best_effort_budget < 1
        ):
            raise ValueError("best effort budget must be a positive integer")
        if self.batch_limit is not None and (type(self.batch_limit) is not int or self.batch_limit < 1):
            raise ValueError("batch limit must be a positive integer")
        if not isinstance(self.known_user_ids, tuple) or any(not isinstance(uid, str) or re.fullmatch(r"[0-9]{1,32}", uid) is None for uid in self.known_user_ids):
            raise ValueError("invalid known user ids")
        if self.count < 0:
            raise ValueError("count must be nonnegative")
        if self.comment_limit < 0:
            raise ValueError("comment_limit must be nonnegative")
        if self.comment_limit and (self.platform != "xhs" or (self.keyword is not None and self.screenshot_mode != "all")):
            raise ValueError("comments require Xiaohongshu creator collection or search with screenshot mode all")
        if not isinstance(self.exclude_ids, tuple) or len(self.exclude_ids) > 10000 or any(not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None for value in self.exclude_ids):
            raise ValueError("invalid continuation identifiers")
        if self.page_cap < 1:
            raise ValueError("page_cap must be at least 1")
        if self.platform == "xhs":
            object.__setattr__(self, "page_cap", min(self.page_cap, MAX_BATCH_PAGES))
        if self.browser_assist not in _BROWSER_ASSIST_MODES:
            raise ValueError("backend-retired-browserskill" if self.browser_assist == "browserskill" else "unsupported browser assist mode")
        # The retired assist bridge cannot construct a new runtime request.
        # Historical diagnostics remain readable without executing that path.
        if self.screenshot_mode not in _SCREENSHOT_MODES:
            raise ValueError("unsupported screenshot mode")
        if sum(
            value is not None for value in (self.uid, self.keyword, self.topic)
        ) != 1:
            raise ValueError("provide exactly one of uid, keyword or topic")
        if self.screenshot_mode == "all" and self.count == 0:
            raise ValueError("screenshot mode all requires a positive count")
        if (
            self.platform == "bilibili"
            and self.keyword is not None
            and (self.browser_assist != "off" or self.screenshot_mode != "off")
        ):
            raise ValueError("Bilibili search advanced modes are not supported")
        if self.topic is not None and self.platform not in _TOPIC_PLATFORMS:
            raise ValueError("topic collection is supported on weibo only")
        if self.topic_kind is not None and self.topic_kind not in TOPIC_KINDS:
            raise ValueError("unsupported topic kind")
        if self.topic is not None and self.topic_kind is None:
            # A bare topic name is a standard ``#话题#``; a super topic is a
            # different page contract and must always be declared explicitly.
            object.__setattr__(self, "topic_kind", TOPIC_KIND_STANDARD)
        if self.plan is not None:
            self._require_plan_consistency()

    def _require_plan_consistency(self) -> None:
        """A request that carries a plan must describe that same task."""

        plan = self.plan
        if not isinstance(plan, CollectionPlan):
            raise ValueError("collection plan does not match the request")
        if self.topic is not None:
            expected_mode = TASK_MODE_TOPIC
        elif self.keyword is not None:
            expected_mode = TASK_MODE_SEARCH
        else:
            expected_mode = TASK_MODE_CREATOR
        for target in plan.targets:
            if target.platform != self.platform or target.mode != expected_mode:
                raise ValueError("collection plan does not match the request")

    @property
    def target_count(self) -> int | None:
        if self.batch_limit is not None:
            return min(self.batch_limit, MAX_BATCH_NOTES) if self.platform == "xhs" else self.batch_limit
        if self.count_mode == COUNT_MODE_BEST_EFFORT:
            # ``best_effort`` has no fixed total: the finite limits are the
            # per-batch budget and the run deadline, not a record count.
            return None
        if self.platform == "xhs":
            return min(self.count or MAX_BATCH_NOTES, MAX_BATCH_NOTES)
        return None if self.count == 0 else self.count

    @property
    def mode(self) -> str:
        """The task mode this request describes, in plan vocabulary."""

        if self.topic is not None:
            return TASK_MODE_TOPIC
        if self.keyword is not None:
            return TASK_MODE_SEARCH
        return TASK_MODE_CREATOR


__all__ = ["CollectionRequest", "RunResult", "RuntimeStatus"]
