"""Versioned Chrome CDP collection contracts and historical record formats.

The controller-facing :class:`~media_missher_runtime.models.CollectionRequest`
stays the single-request shape used by the legacy four-platform collectors.
This module adds the versioned multi-target plan, the task/record/evidence
vocabulary, the backend selection rules and the bounded ``best_effort``
budget contract described by DEEPSEEK_V4_PROMPT.md sections 4, 6 and 7.
"""

from __future__ import annotations

from urllib.parse import urlparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .xhs_policy import MAX_BATCH_NOTES, MAX_BATCH_PAGES


SCHEMA_VERSION = 1  # Export/record schema retained independently.
PLAN_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = 3
OBSERVATION_SCHEMA_VERSION = 1

PLATFORMS: tuple[str, ...] = ("bilibili", "xhs", "douyin", "weibo", "x")
LEGACY_PLATFORMS: tuple[str, ...] = ("bilibili", "xhs", "douyin", "weibo")
PLATFORM_SET = frozenset(PLATFORMS)

BACKEND_CDP = "cdp"
BACKEND_BROWSERSKILL = "browserskill"
BACKEND_COMPUTER_USE = "computer_use"  # Historical records only.
BACKENDS: tuple[str, ...] = (BACKEND_CDP,)
HISTORICAL_BACKENDS = frozenset((*BACKENDS, BACKEND_BROWSERSKILL, BACKEND_COMPUTER_USE))
BACKEND_SET = frozenset(BACKENDS)
DEFAULT_BACKEND = BACKEND_CDP

COUNT_MODE_FIXED = "fixed"
COUNT_MODE_BEST_EFFORT = "best_effort"
COUNT_MODES: tuple[str, ...] = (COUNT_MODE_FIXED, COUNT_MODE_BEST_EFFORT)
COUNT_MODE_SET = frozenset(COUNT_MODES)

TASK_MODE_CREATOR = "creator"
TASK_MODE_SEARCH = "search"
TASK_MODE_TOPIC = "topic"
TASK_MODES: tuple[str, ...] = (TASK_MODE_CREATOR, TASK_MODE_SEARCH, TASK_MODE_TOPIC)
TASK_MODE_SET = frozenset(TASK_MODES)

TOPIC_KIND_STANDARD = "topic"
TOPIC_KIND_SUPER = "super"
TOPIC_KINDS: tuple[str, ...] = (TOPIC_KIND_STANDARD, TOPIC_KIND_SUPER)

RECORD_KIND_POSTS = "posts"
RECORD_KIND_TOPIC_PARTICIPANTS = "topic_participants"
RECORD_KIND_USER_PROFILES = "user_profiles"
RECORD_KINDS: tuple[str, ...] = (
    RECORD_KIND_POSTS,
    RECORD_KIND_TOPIC_PARTICIPANTS,
    RECORD_KIND_USER_PROFILES,
)
RECORD_KIND_SET = frozenset(RECORD_KINDS)

EXPORT_FORMATS: tuple[str, ...] = ("xlsx", "csv", "json", "jsonl", "sqlite")
EXPORT_FORMAT_SET = frozenset(EXPORT_FORMATS)

#: Field quality vocabulary. ``exact`` is the only level that may be counted as
#: a complete value; ``rounded`` keeps the original display string, ``unknown``
#: means the page never showed the value, ``truncated`` means visible text was
#: clipped and must not be presented as the whole value.
FIELD_QUALITY_LEVELS: tuple[str, ...] = ("exact", "rounded", "unknown", "truncated")
FIELD_QUALITY_SET = frozenset(FIELD_QUALITY_LEVELS)

#: Evidence levels a backend may report for one observation. The controller
#: freezes the requested level per task so a page-observed record can never be
#: reported as a response-observed (``complete``) record.
EVIDENCE_PAGE = "page"
EVIDENCE_RESPONSE = "response"
EVIDENCE_LEVELS: tuple[str, ...] = (EVIDENCE_PAGE, EVIDENCE_RESPONSE)

STOP_REASON_NATURAL_END = "natural-end"
STOP_REASON_NO_NEW = "no-new-records"
STOP_REASON_BUDGET = "budget-exhausted"
STOP_REASON_DEADLINE = "run-deadline"
STOP_REASON_COUNT_REACHED = "count-reached"
STOP_REASON_NOT_LOGGED_IN = "not-logged-in"
STOP_REASON_PERMISSION = "permission-denied"
STOP_REASON_RISK = "risk-stopped"
STOP_REASON_TIMEOUT = "timeout"
STOP_REASON_CANCELLED = "cancelled"
STOP_REASON_EMPTY = "empty-results"
STOP_REASON_TARGET_CHANGED = "target-changed"
STOP_REASON_SESSION_LOST = "session-lost"
STOP_REASON_UNSUPPORTED = "unsupported"
STOP_REASON_ERROR = "error"
STOP_REASONS: tuple[str, ...] = (
    STOP_REASON_NATURAL_END,
    STOP_REASON_NO_NEW,
    STOP_REASON_BUDGET,
    STOP_REASON_DEADLINE,
    STOP_REASON_COUNT_REACHED,
    STOP_REASON_NOT_LOGGED_IN,
    STOP_REASON_PERMISSION,
    STOP_REASON_RISK,
    STOP_REASON_TIMEOUT,
    STOP_REASON_CANCELLED,
    STOP_REASON_EMPTY,
    STOP_REASON_TARGET_CHANGED,
    STOP_REASON_SESSION_LOST,
    STOP_REASON_UNSUPPORTED,
    STOP_REASON_ERROR,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_RUN_ID_RE = re.compile(r"run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class ContractError(ValueError):
    """Raised when a plan, target or selection violates the versioned schema."""


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise ContractError(f"{label} must be a safe identifier")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, label)


def _deadline(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a finite positive number of seconds")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ContractError(f"{label} must be a finite positive number of seconds")
    return parsed


def normalize_backend(
    explicit: object,
    *,
    preference: object = None,
    legacy_assist: object = None,
) -> str:
    """Resolve the frozen backend for one run.

    Priority: this run's explicit ``--backend`` > the saved profile preference
    > legacy configuration. A missing preference falls back to ``cdp``. The
    deprecated ``browser-assist`` bridge is not a backend and is rejected
    instead of being silently remapped.
    """

    if legacy_assist not in (None, "off"):
        raise ContractError("browser-assist-replaced")
    for candidate in (explicit, preference):
        if candidate is None:
            continue
        if not isinstance(candidate, str):
            raise ContractError("backend must be a string")
        lowered = candidate.strip().casefold()
        if lowered == "":
            continue
        if lowered == "browserskill":
            raise ContractError("backend-retired-browserskill")
        if lowered == "computer_use":
            raise ContractError("backend-retired-computer-use")
        if lowered == "auto":
            raise ContractError("automatic backend switching is not supported")
        if lowered not in BACKEND_SET:
            raise ContractError("unsupported backend")
        return lowered
    return DEFAULT_BACKEND


@dataclass(frozen=True, slots=True)
class Target:
    """One collection target bound to a stable platform identity."""

    platform: str
    mode: str
    label: str = ""
    uid: str | None = None
    handle: str | None = None
    homepage: str | None = None
    keyword: str | None = None
    topic: str | None = None
    topic_kind: str | None = None
    sort: str | None = None
    source_row: int | None = None

    def __post_init__(self) -> None:
        if self.platform not in PLATFORM_SET:
            raise ContractError("unsupported platform")
        if self.mode not in TASK_MODE_SET:
            raise ContractError("unsupported task mode")
        if self.label and (
            not isinstance(self.label, str) or len(self.label) > 256
        ):
            raise ContractError("target label is invalid")
        for name in ("uid", "handle", "homepage", "keyword", "topic"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"target {name} must be a non-empty string")
            if len(value) > 2048:
                raise ContractError(f"target {name} is too long")
        if self.topic_kind is not None and self.topic_kind not in TOPIC_KINDS:
            raise ContractError("unsupported topic kind")
        if self.sort is not None and self.sort not in {"latest", "top"}:
            raise ContractError("unsupported search sort")
        if self.platform == "x" and self.handle is not None:
            handle = self.handle.removeprefix("@").lower()
            if re.fullmatch(r"[a-z0-9_]{1,15}", handle) is None:
                raise ContractError("invalid X handle")
            object.__setattr__(self, "handle", handle)
        if self.source_row is not None:
            _positive_int(self.source_row, "target source row")
        if self.mode == TASK_MODE_CREATOR and self.homepage:
            parsed = urlparse(self.homepage)
            rules = {
                "weibo": ({"weibo.com", "www.weibo.com"}, r"/(?:u/)?([0-9]{1,32})/?"),
                "bilibili": ({"space.bilibili.com"}, r"/([0-9]{1,32})(?:/dynamic)?/?"),
                "xhs": ({"www.xiaohongshu.com", "xiaohongshu.com"}, r"/user/profile/([a-fA-F0-9]{24})/?"),
                "douyin": ({"www.douyin.com", "douyin.com"}, r"/user/([A-Za-z0-9._-]{1,256})/?"),
                "x": ({"x.com", "www.x.com", "twitter.com", "www.twitter.com"}, r"/([A-Za-z0-9_]{1,15})/?"),
            }
            hosts, pattern = rules[self.platform]
            match = re.fullmatch(pattern, parsed.path)
            if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in {None, 443} or match is None:
                raise ContractError("creator homepage is not an exact supported profile")
            native = match[1].lower() if self.platform in {"x", "xhs"} else match[1]
            field_name = "handle" if self.platform == "x" else "uid"
            existing = getattr(self, field_name)
            if existing is not None and existing.lstrip("@").lower() != native.lower():
                raise ContractError("creator homepage identity conflicts with target")
            if self.platform == "x" and native in {"home", "search", "explore", "settings", "login", "logout", "i"}:
                raise ContractError("X homepage is not an account")
            object.__setattr__(self, field_name, native)
            object.__setattr__(self, "homepage", f"https://{parsed.hostname}{parsed.path}")
        if self.mode == TASK_MODE_CREATOR and not (self.uid or self.handle or self.homepage):
            raise ContractError("creator target requires a uid, handle or homepage")
        if self.mode == TASK_MODE_SEARCH and not self.keyword:
            raise ContractError("search target requires a keyword")
        if self.mode == TASK_MODE_TOPIC:
            if self.platform != "weibo":
                raise ContractError("topic tasks are supported on weibo only")
            if not self.topic:
                raise ContractError("topic target requires a topic")
            if self.topic_kind is None:
                raise ContractError("topic target requires an explicit topic kind")

    @property
    def identity(self) -> str:
        """Stable per-run dedup identity; display labels are never used."""

        if self.mode == TASK_MODE_CREATOR:
            native = self.uid or self.handle or self.homepage or ""
            return f"{self.platform}:creator:{native}"
        if self.mode == TASK_MODE_SEARCH:
            return f"{self.platform}:search:{self.sort or 'latest'}:{self.keyword}"
        return f"{self.platform}:topic:{self.topic_kind}:{self.topic}"

    def to_json(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "mode": self.mode,
            "label": self.label,
            "uid": self.uid,
            "handle": self.handle,
            "homepage": self.homepage,
            "keyword": self.keyword,
            "topic": self.topic,
            "topic_kind": self.topic_kind,
            "sort": self.sort,
        }


def target_from_legacy(
    platform: str,
    *,
    uid: str | None = None,
    keyword: str | None = None,
    label: str = "",
) -> Target:
    """Adapt the legacy one-target-per-platform request into a :class:`Target`."""

    if uid is not None and keyword is not None:
        raise ContractError("a legacy target has exactly one of uid or keyword")
    if keyword is not None:
        return Target(platform=platform, mode=TASK_MODE_SEARCH, keyword=keyword, label=label)
    if uid is not None:
        return Target(platform=platform, mode=TASK_MODE_CREATOR, uid=uid, label=label)
    raise ContractError("a legacy target requires a uid or keyword")


@dataclass(frozen=True, slots=True)
class CollectionPlan:
    """Versioned multi-target plan frozen at the start of one run."""

    targets: tuple[Target, ...]
    backend: str = DEFAULT_BACKEND
    count_mode: str = COUNT_MODE_FIXED
    count: int = 15
    per_target_counts: Mapping[str, int] = field(default_factory=dict)
    per_target_budget: int | None = None
    batch_pages: int = 3
    batch_records: int | None = None
    batch_interval_seconds: float = 0.0
    run_deadline_seconds: float = 900.0
    stall_limit: int = 2
    field_groups: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    allow_navigation: bool = False
    collect_active_platforms: bool = False
    bilibili_complete: bool = False
    xhs_comments: int = 0
    screenshot_mode: str = "off"

    def __post_init__(self) -> None:
        if not isinstance(self.targets, tuple) or not self.targets:
            raise ContractError("a collection plan requires at least one target")
        if not all(isinstance(item, Target) for item in self.targets):
            raise ContractError("collection plan targets must be Target values")
        identities = [item.identity for item in self.targets]
        if len(set(identities)) != len(identities):
            raise ContractError("collection plan contains a duplicate target")
        normalize_backend(self.backend)
        if self.count_mode not in COUNT_MODE_SET:
            raise ContractError("unsupported count mode")
        count = self.count
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ContractError("count must be a non-negative integer")
        if self.count_mode == COUNT_MODE_FIXED and count == 0:
            raise ContractError("fixed count mode requires a positive count")
        normalized_counts: dict[str, int] = {}
        for key, value in self.per_target_counts.items():
            if key not in identities:
                raise ContractError("per-target count requires a plan target")
            normalized_counts[key] = _positive_int(value, "per-target count")
        object.__setattr__(self, "per_target_counts", normalized_counts)
        _optional_positive_int(self.per_target_budget, "per-target budget")
        pages = _positive_int(self.batch_pages, "batch pages")
        if self.targets and any(item.platform == "xhs" for item in self.targets):
            pages = min(pages, MAX_BATCH_PAGES)
        object.__setattr__(self, "batch_pages", pages)
        _optional_positive_int(self.batch_records, "batch records")
        interval = self.batch_interval_seconds
        if isinstance(interval, bool) or not isinstance(interval, (int, float)):
            raise ContractError("batch interval must be a finite non-negative number")
        interval_value = float(interval)
        if not math.isfinite(interval_value) or interval_value < 0:
            raise ContractError("batch interval must be a finite non-negative number")
        object.__setattr__(self, "batch_interval_seconds", interval_value)
        deadline = _deadline(self.run_deadline_seconds, "run deadline")
        object.__setattr__(self, "run_deadline_seconds", deadline)
        _positive_int(self.stall_limit, "stall limit")
        if not isinstance(self.field_groups, tuple) or not isinstance(
            self.required_fields, tuple
        ):
            raise ContractError("field requirements must be tuples")
        for values in (self.field_groups, self.required_fields):
            if len(values) > 64 or any(not isinstance(value, str) or not value or len(value) > 64 for value in values) or len(set(values)) != len(values):
                raise ContractError("invalid or duplicate field requirements")
        for target in self.targets:
            if any(group not in default_field_groups(target.platform) for group in self.field_groups):
                raise ContractError("unsupported field group for target")
        known_fields = {name for platform in PLATFORMS for fields in default_field_groups(platform).values() for name in fields}
        known_fields.update({"dynamic_id", "bvid", "note_id", "aweme_id", "mblog_id", "uid", "description", "body", "complete", "comment_items", "screenshot", "screenshot_status", "engagement_scope", "engagement_observations", "metric_display", "field_sources"})
        if any(name not in known_fields for name in self.required_fields):
            raise ContractError("unsupported required field")
        if not isinstance(self.allow_navigation, bool):
            raise ContractError("navigation authorization must be explicit")
        if not isinstance(self.collect_active_platforms, bool):
            raise ContractError("collect_active_platforms must be an explicit boolean")
        if type(self.bilibili_complete) is not bool:
            raise ContractError("bilibili complete must be boolean")
        if self.bilibili_complete and not any(t.platform == "bilibili" and t.mode == TASK_MODE_CREATOR for t in self.targets):
            raise ContractError("bilibili complete requires a creator target")
        if type(self.xhs_comments) is not int or not 0 <= self.xhs_comments <= 100:
            raise ContractError("invalid xhs comment limit")
        if self.xhs_comments and (not any(t.platform == "xhs" for t in self.targets) or any(t.platform == "xhs" and t.mode != TASK_MODE_CREATOR and self.screenshot_mode != "all" for t in self.targets)):
            raise ContractError("comments require XHS creator or search screenshot all")
        if self.screenshot_mode not in {"off", "opened", "all"}:
            raise ContractError("invalid screenshot mode")
        if self.screenshot_mode == "all" and any(self.count_for(t) == 0 for t in self.targets):
            raise ContractError("screenshot all requires positive counts")
        if self.screenshot_mode != "off" and (not self.allow_navigation or any(t.platform not in {"bilibili", "xhs"} or (t.platform == "bilibili" and t.mode != TASK_MODE_CREATOR) for t in self.targets)):
            raise ContractError("screenshots require authorized supported targets")

    @property
    def platforms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.platform for item in self.targets))

    def count_for(self, target: Target) -> int:
        return self.per_target_counts.get(target.identity, self.count)

    def budget_for(self, target: Target) -> int | None:
        if self.count_mode == COUNT_MODE_FIXED:
            return self.count_for(target)
        return self.per_target_budget

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "backend": self.backend,
            "count_mode": self.count_mode,
            "count": self.count,
            "per_target_counts": dict(self.per_target_counts),
            "per_target_budget": self.per_target_budget,
            "batch_pages": self.batch_pages,
            "batch_records": self.batch_records,
            "batch_interval_seconds": self.batch_interval_seconds,
            "run_deadline_seconds": self.run_deadline_seconds,
            "stall_limit": self.stall_limit,
            "field_groups": list(self.field_groups),
            "required_fields": list(self.required_fields),
            "allow_navigation": self.allow_navigation,
            "collect_active_platforms": self.collect_active_platforms,
            "bilibili_complete": self.bilibili_complete,
            "xhs_comments": self.xhs_comments,
            "screenshot_mode": self.screenshot_mode,
            "targets": [item.to_json() for item in self.targets],
        }

    @classmethod
    def from_json(cls, value: object) -> "CollectionPlan":
        if not isinstance(value, Mapping):
            raise ContractError("collection plan must be a JSON object")
        version = value.get("schema_version", SCHEMA_VERSION)
        if type(version) is not int or version not in {1, PLAN_SCHEMA_VERSION}:
            raise ContractError("unsupported collection plan schema version")
        raw_targets = value.get("targets")
        if not isinstance(raw_targets, Sequence) or isinstance(
            raw_targets, (str, bytes, bytearray)
        ):
            raise ContractError("collection plan targets must be an array")
        targets: list[Target] = []
        for raw in raw_targets:
            if not isinstance(raw, Mapping):
                raise ContractError("collection plan target must be a JSON object")
            unknown = set(raw) - {
                "platform",
                "mode",
                "label",
                "uid",
                "handle",
                "homepage",
                "keyword",
                "topic",
                "topic_kind",
                "sort",
            }
            if unknown:
                raise ContractError("collection plan target has unknown fields")
            targets.append(
                Target(
                    platform=raw.get("platform"),
                    mode=raw.get("mode"),
                    label=raw.get("label") or "",
                    uid=raw.get("uid"),
                    handle=raw.get("handle"),
                    homepage=raw.get("homepage"),
                    keyword=raw.get("keyword"),
                    topic=raw.get("topic"),
                    topic_kind=raw.get("topic_kind"),
                    sort=raw.get("sort"),
                )
            )
        return cls(
            targets=tuple(targets),
            backend=value.get("backend", DEFAULT_BACKEND),
            count_mode=value.get("count_mode", COUNT_MODE_FIXED),
            count=value.get("count", 15),
            per_target_counts=dict(value.get("per_target_counts") or {}),
            per_target_budget=value.get("per_target_budget"),
            batch_pages=value.get("batch_pages", 3),
            batch_records=value.get("batch_records"),
            batch_interval_seconds=value.get("batch_interval_seconds", 0.0),
            run_deadline_seconds=value.get("run_deadline_seconds", 900.0),
            stall_limit=value.get("stall_limit", 2),
            field_groups=tuple(value.get("field_groups") or ()),
            required_fields=tuple(value.get("required_fields") or ()),
            allow_navigation=value.get("allow_navigation", False),
            collect_active_platforms=value.get("collect_active_platforms", False),
            bilibili_complete=value.get("bilibili_complete", False),
            xhs_comments=value.get("xhs_comments", 0),
            screenshot_mode=value.get("screenshot_mode", "off"),
        )


@dataclass(slots=True)
class TaskState:
    """Mutable progress for one plan target."""

    target: Target
    phase: str = "pending"
    stop_reason: str | None = None
    posts: int = 0
    unique_posts: int = 0
    users: int = 0
    pages: int = 0
    batches: int = 0
    profiles_complete: int = 0
    profiles_failed: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    next_batch_at: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target.to_json(),
            "target_identity": self.target.identity,
            "phase": self.phase,
            "stop_reason": self.stop_reason,
            "posts": self.posts,
            "unique_posts": self.unique_posts,
            "users": self.users,
            "pages": self.pages,
            "batches": self.batches,
            "profiles_complete": self.profiles_complete,
            "profiles_failed": self.profiles_failed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "next_batch_at": self.next_batch_at,
            "checkpoint": dict(self.checkpoint),
        }


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Run-level summary written next to the private per-platform artifacts."""

    run_id: str
    schema_version: int
    backend: str
    status: str
    plan: CollectionPlan
    tasks: tuple[Mapping[str, Any], ...]
    counts: Mapping[str, int]
    record_kinds: Mapping[str, int]
    evidence_paths: tuple[str, ...]
    observed_at: str
    started_at: str
    finished_at: str

    def __post_init__(self) -> None:
        if _RUN_ID_RE.fullmatch(self.run_id) is None:
            raise ContractError("manifest run id is invalid")
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ContractError("unsupported manifest schema version")
        if self.backend not in BACKEND_SET:
            raise ContractError("unsupported manifest backend")
        if self.status not in {
            "complete",
            "failed",
            "risk-stopped",
            "partial",
            "cancelled",
        }:
            raise ContractError("unsupported manifest status")
        if self.observed_at != self.finished_at:
            raise ContractError("manifest observation time must match its finish time")

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "backend": self.backend,
            "status": self.status,
            "plan": self.plan.to_json(),
            "tasks": [dict(item) for item in self.tasks],
            "counts": dict(self.counts),
            "record_kinds": dict(self.record_kinds),
            "evidence_paths": list(self.evidence_paths),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "observed_at": self.observed_at,
        }


def default_field_groups(platform: str) -> dict[str, tuple[str, ...]]:
    """Named, user-facing field groups for one platform's export selection."""

    common = ("platform", "type", "native_id", "title", "link", "date", "author", "observed_at")
    metric = ("liked", "comments", "shares", "collected")
    if platform == "x":
        return {
            "identity": ("platform", "type", "tweet_id", "author_id", "handle", "native_id"),
            "content": ("title", "text", "link", "date", "published_at", "observed_at", "text_complete", "language"),
            "metrics": ("liked", "comments", "shares", "quotes", "views", "bookmarks"),
            "author": ("author", "author_handle", "author_name"),
            "relations": ("relation", "referenced_tweet_ids", "conversation_id", "is_pinned", "is_repost"),
            "media": ("media_kind", "media_count", "media_urls", "media_width", "media_height"),
            "evidence": ("backend", "evidence_level", "source_url", "query", "field_quality", "parser_version"),
        }
    if platform == "weibo":
        return {
            "identity": common,
            "metrics": metric,
            "media": ("pic_ids", "pics", "pic_num"),
            "evidence": ("backend", "evidence_level", "source_url", "observed_at"),
        }
    return {"core": common, "metrics": metric, "evidence": ("backend", "evidence_level")}


__all__ = [
    "BACKENDS",
    "BACKEND_BROWSERSKILL",
    "BACKEND_CDP",
    "BACKEND_SET",
    "COUNT_MODES",
    "COUNT_MODE_BEST_EFFORT",
    "COUNT_MODE_FIXED",
    "CollectionPlan",
    "ContractError",
    "DEFAULT_BACKEND",
    "EVIDENCE_LEVELS",
    "EVIDENCE_PAGE",
    "EVIDENCE_RESPONSE",
    "EXPORT_FORMATS",
    "EXPORT_FORMAT_SET",
    "FIELD_QUALITY_LEVELS",
    "FIELD_QUALITY_SET",
    "LEGACY_PLATFORMS",
    "PLATFORMS",
    "PLATFORM_SET",
    "RECORD_KINDS",
    "RECORD_KIND_POSTS",
    "RECORD_KIND_SET",
    "RECORD_KIND_TOPIC_PARTICIPANTS",
    "RECORD_KIND_USER_PROFILES",
    "RunManifest",
    "SCHEMA_VERSION",
    "STOP_REASONS",
    "STOP_REASON_BUDGET",
    "STOP_REASON_CANCELLED",
    "STOP_REASON_COUNT_REACHED",
    "STOP_REASON_DEADLINE",
    "STOP_REASON_EMPTY",
    "STOP_REASON_ERROR",
    "STOP_REASON_NATURAL_END",
    "STOP_REASON_NO_NEW",
    "STOP_REASON_NOT_LOGGED_IN",
    "STOP_REASON_PERMISSION",
    "STOP_REASON_RISK",
    "STOP_REASON_SESSION_LOST",
    "STOP_REASON_TARGET_CHANGED",
    "STOP_REASON_TIMEOUT",
    "STOP_REASON_UNSUPPORTED",
    "TASK_MODES",
    "TASK_MODE_CREATOR",
    "TASK_MODE_SEARCH",
    "TASK_MODE_SET",
    "TASK_MODE_TOPIC",
    "TOPIC_KINDS",
    "TOPIC_KIND_STANDARD",
    "TOPIC_KIND_SUPER",
    "Target",
    "TaskState",
    "default_field_groups",
    "normalize_backend",
    "target_from_legacy",
]
