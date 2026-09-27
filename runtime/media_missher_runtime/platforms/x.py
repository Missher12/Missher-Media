"""X (twitter) collection through Chrome CDP.

Two evidence routes feed one normalizer:

``response``
    The CDP backend registers its listener *before* the triggering page action,
    binds every candidate response to the exact host, GraphQL operation and the
    query/author identity of the current task, validates the HTTP status and the
    structured ``errors`` array, and only then reads the body. Private requests
    are never replayed and authentication material is never extracted.

``page``
    CDP may read rendered cards through its bounded DOM extractor.
    Page evidence is never reported as response-observed.

Both routes share :func:`normalize_post`, the identity and target binding rules,
the dedup key and the field-quality vocabulary. GraphQL operation paths are
treated as fixture-confirmed structure, never as a stable public API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import re
import json
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from ..capabilities import require_task
from ..contracts import (
    BACKEND_CDP,
    EVIDENCE_PAGE,
    EVIDENCE_RESPONSE,
    TASK_MODE_CREATOR,
    TASK_MODE_SEARCH,
    TASK_MODE_TOPIC,
    Target,
)
from ..browser import PreconditionError, publish_accepted
from ..extraction import as_items, as_mapping
from ..models import CollectionRequest
from ..safety import classify_response


X_HOSTS: tuple[str, ...] = ("x.com", "www.x.com", "twitter.com", "www.twitter.com")
CANONICAL_HOST = "x.com"
PARSER_VERSION = "x-parser-1"

#: GraphQL operation names this build binds to. The path is fixture-confirmed
#: structure, so an unknown operation is ignored instead of being parsed.
OPERATION_POSTS = "UserTweets"
OPERATION_SEARCH = "SearchTimeline"
OPERATION_TWEET_DETAIL = "TweetResultByRestId"
OPERATIONS: frozenset[str] = frozenset(
    {OPERATION_POSTS, OPERATION_SEARCH, OPERATION_TWEET_DETAIL}
)

_RISK_CODES = frozenset({403, 429})
#: X native identifiers are decimal strings. The legacy media entities still use
#: the short ``media_key`` alphabet, so both shapes are recognized explicitly.
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ORIGIN_ID = re.compile(r"[0-9]{1,32}")
_TWEET_ID = _ORIGIN_ID
_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
_OPERATION_PATH = re.compile(r"^/i/api/graphql/[A-Za-z0-9_-]+/([A-Za-z0-9_]+)$")
_MISSING = object()
_ABBREVIATED = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMB])\s*$", re.IGNORECASE)
_ABBREVIATION_FACTOR = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


class CollectionStopped(RuntimeError):
    """A platform risk signal requires collection to stop immediately."""


class SourceResponseError(RuntimeError):
    """An observed X response was not usable evidence."""


class CaptureTimeout(TimeoutError):
    """No usable X response arrived inside the bounded capture window."""

    def __init__(self, code: str = "x-capture-timeout", **observation: object) -> None:
        self.code = code
        self.observation = observation.get("observation", "unclassified")
        for key, value in observation.items():
            setattr(self, key, value)
        super().__init__(code)


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _identifier(value: object) -> str | None:
    """X user/author IDs are decimal native IDs, only ever exposed as strings."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value)
        return text if _ORIGIN_ID.fullmatch(text) else None
    text = _text(value)
    return text if text is not None and _ORIGIN_ID.fullmatch(text) else None


def _tweet_id(value: object) -> str | None:
    return _identifier(value)


def _handle(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    trimmed = text[1:] if text.startswith("@") else text
    return trimmed.lower() if _HANDLE.fullmatch(trimmed) else None


def _metric(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return None


def parse_display_metric(value: object) -> tuple[int | float | None, str]:
    """Parse one rendered metric string and report its precision.

    ``1.2K`` becomes ``(1200.0, "rounded")`` while keeping the original display
    text on the record. A value that was never displayed stays ``None``.
    """

    text = _text(value)
    if text is None:
        return None, "unknown"
    normalized = text.replace(",", "").replace("，", "").strip()
    match = _ABBREVIATED.match(normalized)
    if match is not None:
        base = float(match.group(1))
        factor = _ABBREVIATION_FACTOR[match.group(2).casefold()]
        return base * factor, "rounded"
    if re.fullmatch(r"[0-9]+", normalized):
        return int(normalized), "exact"
    digits = re.sub(r"[^0-9]", "", normalized)
    if digits:
        return None, "unknown"
    return None, "unknown"


def normalize_post(
    *,
    tweet_id: str | None,
    author_id: str | None,
    handle: str | None,
    author_name: str | None,
    text: str | None,
    text_complete: bool,
    published_at: str | None,
    date_text: str | None,
    observed_at: str,
    metric_values: Mapping[str, int | float | None],
    metric_display: Mapping[str, str] | None = None,
    relation: str = "post",
    referenced_tweet_ids: Sequence[str] = (),
    conversation_id: str | None = None,
    is_pinned: bool = False,
    is_repost: bool = False,
    language: str | None = None,
    media_kind: str | None = None,
    media_count: int | None = None,
    media_urls: Sequence[str] = (),
    media_width: int | None = None,
    media_height: int | None = None,
    quoted_tweet_id: str | None = None,
    source_url: str | None,
    query: str | None,
    backend: str,
    evidence_level: str,
    target_identity: str | None = None,
    in_reply_to_tweet_id: str | None = None,
    in_reply_to_handle: str | None = None,
    search_keyword: str | None = None,
) -> dict[str, Any]:
    """Build one X post record.

    Field rules enforced here:

    * unknown values are ``null`` and never written as zero;
    * an abbreviated display value keeps ``display`` text and a ``rounded``
      quality, and is never presented as an exact count;
    * ``comments`` is the reply count only and never claims reply bodies;
    * ``views`` is the post view count and is explicitly not a video play count;
    * ``bookmarks`` is the same-origin alias of the collected metric, not a
      second dimension;
    * a quoted inner post is a referenced identity, never a second record.
    """

    link = (
        f"https://{CANONICAL_HOST}/{handle}/status/{tweet_id}"
        if handle is not None and tweet_id is not None
        else None
    )
    quality: dict[str, str] = {}
    metric_display = metric_display or {}
    record: dict[str, Any] = {
        "platform": "x",
        "type": "post",
        "tweet_id": tweet_id,
        "id": tweet_id,
        "native_id": tweet_id,
        "author_id": author_id,
        "author_handle": handle,
        "handle": handle,
        "author": author_name or handle,
        "author_name": author_name,
        "title": (text or "")[:280] or None,
        "text": text,
        "text_complete": bool(text_complete),
        "link": link,
        "url": link,
        "date": date_text or published_at,
        "published_at": published_at,
        "observed_at": observed_at,
        "language": language,
        "liked": _metric(metric_values.get("liked")),
        "comments": _metric(metric_values.get("comments")),
        "shares": _metric(metric_values.get("shares")),
        "quotes": _metric(metric_values.get("quotes")),
        "views": _metric(metric_values.get("views")),
        "bookmarks": _metric(metric_values.get("bookmarks")),
        "collected": _metric(metric_values.get("bookmarks")),
        "relation": relation,
        "is_repost": bool(is_repost),
        "is_pinned": bool(is_pinned),
        "referenced_tweet_ids": [item for item in referenced_tweet_ids if item],
        "quoted_tweet_id": quoted_tweet_id,
        "conversation_id": conversation_id,
        "in_reply_to_tweet_id": in_reply_to_tweet_id,
        "in_reply_to_handle": in_reply_to_handle,
        "media_kind": media_kind,
        "media_count": media_count,
        "media_urls": list(media_urls),
        "media_width": media_width,
        "media_height": media_height,
        "search_keyword": search_keyword or query,
        "query": query,
        "source_url": source_url,
        "backend": backend,
        "evidence_level": evidence_level,
        "field_quality": quality,
        "parser_version": PARSER_VERSION,
    }
    for field, value in record.items():
        if field in {
            "platform",
            "type",
            "relation",
            "text_complete",
            "is_repost",
            "is_pinned",
            "backend",
            "evidence_level",
            "field_quality",
            "parser_version",
            "referenced_tweet_ids",
            "media_urls",
        }:
            continue
        if value is None:
            quality[field] = "unknown"
    for field in ("liked", "comments", "shares", "quotes", "views", "bookmarks"):
        display = metric_display.get(field)
        if display is None:
            continue
        parsed, precision = parse_display_metric(display)
        if parsed is None:
            quality[field] = "unknown"
            continue
        quality[field] = precision
        record[f"{field}_display"] = display
    if not text_complete:
        quality["text"] = "truncated"
    if target_identity is not None:
        record["target_identity"] = target_identity
    return record


# ---------------------------------------------------------------------------
# target URLs and response binding
# ---------------------------------------------------------------------------


def profile_url(handle: str) -> str:
    normalized = _handle(handle)
    if normalized is None:
        raise ValueError("invalid X handle")
    return f"https://{CANONICAL_HOST}/{normalized}"


def search_url(query: str, sort: str = "latest") -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("X search requires a query")
    if sort not in {"latest", "top"}:
        raise ValueError("X search sort must be latest or top")
    facet = "live" if sort == "latest" else "top"
    return f"https://{CANONICAL_HOST}/search?q={quote(query.strip(), safe='')}&src=typed_query&f={facet}"


def hashtag_url(topic: str, sort: str = "latest") -> str:
    tag = topic.strip().lstrip("#")
    if not tag:
        raise ValueError("X hashtag requires a topic")
    return search_url(f"#{tag}", sort)


def target_url(target: Target) -> str:
    if target.mode == TASK_MODE_CREATOR:
        if target.handle:
            return profile_url(target.handle)
        if target.homepage:
            parsed = urlparse(target.homepage)
            if parsed.hostname not in X_HOSTS:
                raise ValueError("X homepage must use the official host")
            return target.homepage
        raise ValueError("X creator target requires a handle or homepage")
    if target.mode == TASK_MODE_SEARCH:
        return search_url(target.keyword or "", target.sort or "latest")
    if target.mode == TASK_MODE_TOPIC:
        return hashtag_url(target.topic or "", target.sort or "latest")
    raise ValueError("unsupported X target mode")


def target_binding(target: Target) -> dict[str, str | None]:
    """The identity a response must match before its body may be read."""

    if target.mode == TASK_MODE_CREATOR:
        return {
            "kind": "creator",
            "handle": _handle(target.handle),
            "user_id": _identifier(target.uid),
            "operation": OPERATION_POSTS,
        }
    if target.mode in {TASK_MODE_SEARCH, TASK_MODE_TOPIC}:
        term = target.keyword if target.mode == TASK_MODE_SEARCH else f"#{target.topic}"
        return {"kind": "search", "query": term, "operation": OPERATION_SEARCH,
                "product": "Top" if target.sort == "top" else "Latest"}
    raise ValueError("unsupported X target mode")


def observed_operation(url: object) -> str | None:
    """Return the GraphQL operation name of an observed response, if known."""

    text = _text(url)
    if text is None:
        return None
    parsed = urlparse(text)
    if parsed.hostname not in X_HOSTS:
        return None
    match = _OPERATION_PATH.match(parsed.path)
    if match is None:
        return None
    operation = match.group(1)
    return operation if operation in OPERATIONS else None


def response_matches(
    *,
    url: object,
    binding: Mapping[str, str | None],
) -> bool:
    """Decide whether an observed response belongs to the current task.

    Binding is exact: the host, the GraphQL operation, and the request's own
    variable payload must all match the frozen target. A response for another
    query, another author or a recommendation timeline is ignored rather than
    parsed.
    """

    text = _text(url)
    if text is None:
        return False
    operation = observed_operation(text)
    if operation is None or operation != binding.get("operation"):
        return False
    query = parse_qs(urlparse(text).query, keep_blank_values=True)
    if len(query.get("variables", [])) != 1:
        return False
    variables_raw = query["variables"][0]
    if len(variables_raw) > 65536:
        return False
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate variable")
            result[key] = value
        return result
    try:
        variables = json.loads(variables_raw, object_pairs_hook=unique)
    except (ValueError, RecursionError):
        return False
    if not isinstance(variables, dict):
        return False
    if binding.get("kind") == "creator":
        expected_user = binding.get("user_id")
        expected_handle = binding.get("handle")
        user = variables.get("userId")
        handle = _handle(variables.get("screenName"))
        if expected_user is not None and user is not None and user != expected_user:
            return False
        if expected_handle is not None and handle is not None and handle != expected_handle:
            return False
        return (expected_user is not None and user == expected_user) or (expected_handle is not None and handle == expected_handle)
    expected_query = binding.get("query")
    if expected_query is None:
        return False
    return variables.get("rawQuery") == expected_query and variables.get("product") == binding.get("product")


async def response_payload(response: Any) -> Mapping[str, Any]:
    """Validate one bound response and return its JSON object."""

    status = getattr(response, "status", None)
    if isinstance(status, bool) or not isinstance(status, int):
        raise SourceResponseError("X source response has no numeric HTTP status")
    decision = classify_response(status=status)
    if decision.stop_all:
        raise CollectionStopped(decision.reason or f"http-{status}")
    if not 200 <= status < 300:
        raise SourceResponseError(f"X source returned http-{status}")
    try:
        payload = await response.json()
    except Exception as error:  # noqa: BLE001 - any decode failure is unusable evidence
        raise SourceResponseError("X source JSON decode failed") from error
    if not isinstance(payload, Mapping):
        raise SourceResponseError("X source returned a non-object JSON payload")
    errors = payload.get("errors")
    if errors is not None:
        if not isinstance(errors, Sequence) or isinstance(errors, (str, bytes, bytearray)):
            raise SourceResponseError("X source errors field is malformed")
        if errors:
            first = as_mapping(errors[0])
            code = _text(first.get("code")) or ""
            message = _text(first.get("message")) or ""
            if code in {"88", "RateLimitExceeded"} or _looks_like_risk(message):
                raise CollectionStopped("risk-signal")
            raise SourceResponseError("X source returned a structured error")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise SourceResponseError("X source payload has no data object")
    return payload


def _looks_like_risk(message: str) -> bool:
    lowered = message.casefold()
    return any(
        marker in lowered
        for marker in ("rate limit", "too many requests", "try again later", "suspicious", "locked")
    )


# ---------------------------------------------------------------------------
# response-route parsing
# ---------------------------------------------------------------------------


def _entry_items(payload: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """Walk the fixture-confirmed timeline envelope and yield (entry id, content)."""

    data = as_mapping(payload.get("data"))
    items: list[tuple[str, Mapping[str, Any]]] = []
    for container in ("user", "search_by_raw_query", "threaded_conversation_with_injections_v2"):
        node = as_mapping(data.get(container))
        if not node:
            continue
        result = as_mapping(node.get("result"))
        timeline = as_mapping(result.get("timeline")) or as_mapping(node.get("timeline"))
        instructions = timeline.get("instructions")
        if not isinstance(instructions, Sequence) or isinstance(
            instructions, (str, bytes, bytearray)
        ):
            continue
        for instruction in instructions:
            entry_list = as_mapping(instruction).get("entries")
            if not isinstance(entry_list, Sequence) or isinstance(
                entry_list, (str, bytes, bytearray)
            ):
                continue
            for entry in entry_list:
                content = as_mapping(as_mapping(entry).get("content"))
                item = content.get("itemContent")
                if isinstance(item, Mapping):
                    entry_id = as_mapping(entry).get("entryId")
                    items.append(
                        (
                            entry_id if isinstance(entry_id, str) else "",
                            item,
                        )
                    )
        if items:
            break
    return items


def _tweet_result(item: Mapping[str, Any]) -> Mapping[str, Any]:
    results = as_mapping(item.get("tweet_results"))
    root = as_mapping(results.get("result"))
    # A tweet that failed visibility checks is nested under ``tweet``.
    nested = as_mapping(root.get("tweet"))
    if nested:
        return nested
    return root


def _legacy(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return as_mapping(result.get("legacy"))


def _user_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the author node, keeping the outer ``rest_id`` alongside ``core``.

    The fixture-confirmed envelope nests the profile under ``core`` but keeps the
    numeric user id on the outer node, so the two must not be flattened away from
    each other.
    """

    core = as_mapping(result.get("core"))
    user_results = as_mapping(core.get("user_results"))
    user = as_mapping(user_results.get("result"))
    nested = as_mapping(user.get("core"))
    if not nested:
        return user
    merged = dict(nested)
    for key, value in user.items():
        # The inner node may carry a null placeholder for a field the outer node
        # actually provides, so only an absent or null key is filled in.
        if key not in merged or merged[key] is None:
            merged[key] = value
    return merged


def _note_tweet_text(result: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Long-form posts keep their expanded text in ``note_tweet``.

    When that node is absent the record must be marked truncated instead of
    presenting ``legacy.full_text`` as the whole post.
    """

    note = as_mapping(result.get("note_tweet"))
    note_results = as_mapping(note.get("note_tweet_results"))
    note_result = as_mapping(note_results.get("result"))
    text = _text(note_result.get("text"))
    if text is not None:
        return text, True
    return None, False


def _media_summary(legacy: Mapping[str, Any]) -> dict[str, Any]:
    entities = as_mapping(legacy.get("extended_entities"))
    media = entities.get("media")
    if not isinstance(media, Sequence) or isinstance(media, (str, bytes, bytearray)):
        media = as_mapping(legacy.get("entities")).get("media")
    items = as_items(media)
    if not items:
        return {
            "media_kind": None,
            "media_count": None,
            "media_urls": [],
            "media_width": None,
            "media_height": None,
        }
    kinds: list[str] = []
    urls: list[str] = []
    width: int | None = None
    height: int | None = None
    for raw in items:
        entry = as_mapping(raw)
        kind = _text(entry.get("type"))
        if kind is not None and kind not in kinds:
            kinds.append(kind)
        info = as_mapping(entry.get("original_info"))
        if width is None and isinstance(info.get("width"), int):
            width = info["width"]
        if height is None and isinstance(info.get("height"), int):
            height = info["height"]
        if kind == "video":
            variant = _best_variant(as_mapping(entry.get("video_info")))
            if variant is not None:
                urls.append(variant)
                continue
            # A video's preview image is not the video resource.
            preview = _text(entry.get("media_url_https"))
            if preview is not None:
                urls.append(preview)
            continue
        candidate = _text(entry.get("media_url_https"))
        if candidate is not None:
            urls.append(candidate)
    return {
        "media_kind": ",".join(kinds) or None,
        "media_count": len(items),
        "media_urls": urls[:16],
        "media_width": width,
        "media_height": height,
    }


def _best_variant(video_info: Mapping[str, Any]) -> str | None:
    variants = as_items(video_info.get("variants"))
    best: tuple[int, str] | None = None
    for raw in variants:
        entry = as_mapping(raw)
        url = _text(entry.get("url"))
        if url is None or _text(entry.get("content_type")) != "video/mp4":
            continue
        bitrate = entry.get("bitrate")
        score = bitrate if isinstance(bitrate, int) and not isinstance(bitrate, bool) else 0
        if best is None or score > best[0]:
            best = (score, url)
    return best[1] if best is not None else None


def _quoted_id(legacy: Mapping[str, Any]) -> str | None:
    quoted = as_mapping(legacy.get("quoted_status_result"))
    result = as_mapping(quoted.get("result"))
    if not result:
        return None
    return _tweet_id(_legacy(result).get("id_str")) or _tweet_id(result.get("rest_id"))


def normalize_response_item(
    item: Mapping[str, Any],
    *,
    backend: str,
    evidence_level: str,
    observed_at: str,
    query: str | None = None,
    target_identity: str | None = None,
    source_url: str | None = None,
    entry_id: str = "",
) -> dict[str, Any] | None:
    """Convert one timeline entry into a normalized post record."""

    result = _tweet_result(item)
    if not result:
        return None
    legacy = _legacy(result)
    rest_id = _tweet_id(result.get("rest_id")) or _tweet_id(legacy.get("id_str"))
    if rest_id is None:
        return None
    user = _user_result(result)
    user_legacy = as_mapping(user.get("legacy"))
    handle = _handle(as_mapping(user.get("core")).get("screen_name")) or _handle(
        user_legacy.get("screen_name")
    )
    author_id = _identifier(user.get("rest_id")) or _identifier(
        user_legacy.get("id_str")
    )
    author_name = _text(as_mapping(user.get("core")).get("name")) or _text(
        user_legacy.get("name")
    )
    note_text, note_complete = _note_tweet_text(result)
    legacy_text = _text(legacy.get("full_text"))
    if note_text is not None:
        text_value, text_complete = note_text, True
    elif legacy_text is not None:
        text_value, text_complete = legacy_text, False
    else:
        text_value, text_complete = None, False
    retweeted = as_mapping(legacy.get("retweeted_status_result"))
    is_repost = bool(retweeted)
    reply_to_id = _tweet_id(legacy.get("in_reply_to_status_id_str"))
    reply_to_handle = _handle(legacy.get("in_reply_to_screen_name"))
    if is_repost:
        relation = "repost"
    elif reply_to_id is not None:
        relation = "reply"
    elif _quoted_id(legacy) is not None:
        relation = "quote"
    else:
        relation = "post"
    referenced: list[str] = []
    quoted = _quoted_id(legacy)
    if quoted is not None:
        referenced.append(quoted)
    if is_repost:
        inner = _legacy(as_mapping(as_mapping(retweeted).get("result")))
        inner_id = _tweet_id(inner.get("id_str"))
        if inner_id is not None:
            referenced.append(inner_id)
    media = _media_summary(legacy)
    metric_display: dict[str, str] = {}
    metric_values: dict[str, int | float | None] = {}
    counts = as_mapping(result.get("views"))
    for field, key in (
        ("liked", "favorite_count"),
        ("comments", "reply_count"),
        ("shares", "retweet_count"),
        ("quotes", "quote_count"),
        ("bookmarks", "bookmark_count"),
    ):
        raw = legacy.get(key)
        metric_values[field] = _metric(raw)
        if raw is None:
            metric_display[field] = ""
    views = counts.get("count")
    metric_values["views"] = _metric(_text(views) and int(views) if isinstance(views, str) and views.isdigit() else views)
    return normalize_post(
        tweet_id=rest_id,
        author_id=author_id,
        handle=handle,
        author_name=author_name,
        text=text_value,
        text_complete=text_complete,
        published_at=_iso_datetime(_text(legacy.get("created_at"))),
        date_text=_text(legacy.get("created_at")),
        observed_at=observed_at,
        metric_values=metric_values,
        metric_display=metric_display,
        relation=relation,
        referenced_tweet_ids=referenced,
        conversation_id=_tweet_id(legacy.get("conversation_id_str")),
        is_repost=is_repost,
        is_pinned="cursor-top" in entry_id,
        language=_text(legacy.get("lang")),
        quoted_tweet_id=quoted,
        source_url=source_url,
        query=query,
        backend=backend,
        evidence_level=evidence_level,
        target_identity=target_identity,
        in_reply_to_tweet_id=reply_to_id,
        in_reply_to_handle=reply_to_handle,
        search_keyword=query,
        **media,
    )


def _iso_datetime(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None
    return parsed.astimezone(UTC).isoformat()


def normalize_response_payload(
    payload: Mapping[str, Any],
    *,
    backend: str = BACKEND_CDP,
    evidence_level: str = EVIDENCE_RESPONSE,
    observed_at: str,
    query: str | None = None,
    target_identity: str | None = None,
    source_url: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for entry_id, item in _entry_items(payload):
        record = normalize_response_item(
            item,
            backend=backend,
            evidence_level=evidence_level,
            observed_at=observed_at,
            query=query,
            target_identity=target_identity,
            source_url=source_url,
            entry_id=entry_id,
        )
        if record is not None:
            records.append(record)
        if limit is not None and len(records) >= limit:
            break
    return records


# ---------------------------------------------------------------------------
# page-route parsing
# ---------------------------------------------------------------------------


def normalize_page_payload(
    payload: Mapping[str, Any],
    *,
    query: str | None,
    target_identity: str | None,
    observed_at: str,
    source_url: str | None,
    expected_handle: str | None = None,
    backend: str = BACKEND_CDP,
) -> list[dict[str, Any]]:
    """Convert the shared DOM extractor output into normalized post records.

    Cards from another author, promoted cards and reference-card authors are
    refused so a profile task cannot be contaminated by recommendations.
    """

    records: list[dict[str, Any]] = []
    for raw in as_items(payload.get("posts")):
        card = as_mapping(raw)
        handle = _handle(card.get("handle"))
        if expected_handle is not None and handle != expected_handle:
            continue
        if card.get("promoted") is True and card.get("permalink") is None:
            continue
        permalink = _text(card.get("permalink"))
        tweet_id = _tweet_from_permalink(permalink)
        if tweet_id is None:
            continue
        if card.get("has_quoted_text") and card.get("has_social_proof") and not card.get("text"):
            # A reference card renders another post's body only; it is not this
            # author's post.
            continue
        metric_values: dict[str, int | float | None] = {}
        metric_display: dict[str, str] = {}
        for field, key in (
            ("liked", "like_metric"),
            ("comments", "reply_metric"),
            ("shares", "repost_metric"),
            ("views", "view_metric"),
            ("bookmarks", "bookmark_metric"),
        ):
            value = card.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                metric_values[field] = value
                metric_display[field] = str(value)
            else:
                metric_values[field] = None
        social_context = _text(card.get("social_context"))
        is_repost = bool(social_context and "reposted" in social_context.casefold())
        text_value = _text(card.get("text"))
        media_urls = [
            url for url in as_items(card.get("image_urls")) if isinstance(url, str)
        ]
        video_count = card.get("video_count")
        media_kind = (
            "video" if isinstance(video_count, int) and video_count > 0
            else "photo" if media_urls
            else None
        )
        records.append(
            normalize_post(
                tweet_id=tweet_id,
                author_id=None,
                handle=handle,
                author_name=_text(card.get("author_name")),
                text=text_value,
                # A rendered card may clip a long post; the page route cannot
                # prove the full text without expanding it.
                text_complete=False,
                published_at=_iso_datetime(_text(card.get("datetime"))[-30:])
                if isinstance(card.get("datetime"), str)
                else None,
                date_text=_text(card.get("datetime")),
                observed_at=observed_at,
                metric_values=metric_values,
                metric_display=metric_display,
                relation="repost" if is_repost else "post",
                is_repost=is_repost,
                source_url=source_url or permalink,
                query=query,
                backend=backend,
                evidence_level=EVIDENCE_PAGE,
                target_identity=target_identity,
                search_keyword=query,
                media_kind=media_kind,
                media_count=len(media_urls) or (video_count if isinstance(video_count, int) else None),
                media_urls=media_urls,
            )
        )
    return records


def _tweet_from_permalink(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.hostname not in X_HOSTS:
        return None
    match = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/status/([0-9]{1,32})", parsed.path)
    if match is None:
        return None
    return match.group(2)


def parse_iso(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def observed_now() -> str:
    return datetime.now(UTC).isoformat()


def dedup_key(record: Mapping[str, Any]) -> str | None:
    """Dedup key: platform plus native post identity, never the display label."""

    tweet_id = record.get("tweet_id")
    if isinstance(tweet_id, str) and tweet_id:
        return f"x:post:{tweet_id}"
    return None


def require_x_capability(backend: str, mode: str) -> None:
    require_task(backend, "x", mode)


# ---------------------------------------------------------------------------
# collection loop
# ---------------------------------------------------------------------------

#: A bounded wait for the platform's own response after a page action. It is a
#: ceiling, never a guarantee that a response will arrive.
CAPTURE_TIMEOUT_MS = 12_000
_SCROLL_SETTLE_MS = 900


@dataclass(slots=True)
class XCollector:
    """Collect one X target with whichever evidence route the session supports.

    The two routes are chosen from the session's real capabilities, never from a
    guess:

    * a session that can observe the page's own responses (the CDP backend) binds
      a listener to the exact operation and target identity before the page
      action, then reads only the responses that action produced;
    * a CDP page without response observation reads the post cards the
      current tab actually renders through the shared bounded extractor.

    Both routes feed the same normalizer, so identity, field quality, dedup and
    output stay identical; only ``evidence_level`` and the field coverage differ.
    """

    request: CollectionRequest
    browser: Any

    def _target(self) -> Target:
        request = self.request
        if request.keyword is not None:
            return Target(
                platform="x",
                mode=TASK_MODE_SEARCH,
                keyword=request.keyword,
                sort=request.sort,
            )
        if request.uid is None:
            raise ValueError("X creator collection requires a handle or user id")
        handle = _handle(request.uid)
        if handle is None:
            raise ValueError("X creator collection requires a valid handle")
        return Target(
            platform="x",
            mode=TASK_MODE_CREATOR,
            handle=handle,
            uid=request.uid if _ORIGIN_ID.fullmatch(request.uid) else None,
        )

    def _page(self) -> Any:
        page = self.browser.require_page("x")
        return page

    async def collect(self) -> list[dict[str, Any]]:
        target = self._target()
        require_x_capability(self.request.backend, target.mode)
        page = self._page()
        if self._can_observe_responses(page):
            return await self._collect_by_response(target, page)
        return await self._collect_by_page(target, page)

    @staticmethod
    def _can_observe_responses(page: Any) -> bool:
        """Response bodies exist only where the session can watch its own page."""

        observer = getattr(page, "expect_response", None)
        return getattr(page, "supports_response_bodies", True) is not False and callable(observer)

    # -- response route ----------------------------------------------------

    async def _collect_by_response(self, target: Target, page: Any) -> list[dict[str, Any]]:
        binding = target_binding(target)
        url = target_url(target)
        records: list[dict[str, Any]] = []
        seen: set[str] = set(self.request.exclude_ids)
        target_identity = target.identity
        observed_at = observed_now()
        navigate = self._navigator(target, page)
        for page_number in range(self.request.page_cap):
            if hasattr(self.browser, "last_pages"):
                self.browser.last_pages += 1
            observation: dict[str, Any] = {"payload": None, "url": None}

            def capture(response: Any, observation: dict[str, Any] = observation) -> bool:
                # Binding happens before the body is read, so a response for
                # another query, author or recommendation timeline is refused.
                if not response_matches(url=getattr(response, "url", None), binding=binding):
                    return False
                observation["url"] = getattr(response, "url", None)
                return True

            async def action(page_number: int = page_number) -> None:
                if page_number == 0:
                    if self.request.continue_page and page.url == url:
                        await _raise_for_page_risk(page)
                        await self._scroll(page)
                        await self._settle(page)
                    else:
                        await navigate(url)
                else:
                    await self._scroll(page)
                    await self._settle(page)

            response = await self._capture_while(page, capture, action)
            if response is None:
                if hasattr(self.browser, "last_stop_reason"):
                    self.browser.last_stop_reason = "timeout"
                break
            payload = await response_payload(response)
            page_records = normalize_response_payload(
                payload,
                backend=self.request.backend,
                evidence_level=EVIDENCE_RESPONSE,
                observed_at=observed_at,
                query=target.keyword if target.mode != TASK_MODE_CREATOR else None,
                target_identity=target_identity,
                source_url=observation["url"],
            )
            added = _append(records, seen, page_records)
            publish_accepted(self.browser, "x", records)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 and page_number > 0:
                break
        return records

    async def _capture_while(self, page: Any, predicate: Any, action: Any) -> Any:
        try:
            async with page.expect_response(predicate, timeout=CAPTURE_TIMEOUT_MS) as info:
                await action()
        except Exception as error:  # noqa: BLE001 - a timeout is an empty batch, not a crash
            if type(error).__name__ in {"TimeoutError", "PlaywrightTimeoutError"}:
                return None
            raise
        return await info.value

    # -- page route --------------------------------------------------------

    async def _collect_by_page(self, target: Target, page: Any) -> list[dict[str, Any]]:
        from ..extraction import x_posts_expression
        expected_handle = _handle(target.handle) if target.mode == TASK_MODE_CREATOR else None
        url = target_url(target)
        observed_at = observed_now()
        records: list[dict[str, Any]] = []
        seen: set[str] = set(self.request.exclude_ids)
        navigate = self._navigator(target, page)
        expression = x_posts_expression()
        for page_number in range(self.request.page_cap):
            if hasattr(self.browser, "last_pages"):
                self.browser.last_pages += 1
            if page_number == 0:
                if not self.request.continue_page:
                    await navigate(url)
                else:
                    _require_open_target(page, url)
            else:
                await self._scroll(page)
                await self._settle(page)
            payload = await page.evaluate(expression)
            if not isinstance(payload, Mapping):
                raise SourceResponseError("X page observation returned no object")
            page_records = normalize_page_payload(
                payload,
                query=target.keyword,
                target_identity=target.identity,
                observed_at=observed_at,
                source_url=getattr(page, "url", None) or url,
                expected_handle=expected_handle,
                backend=self.request.backend,
            )
            added = _append(records, seen, page_records)
            publish_accepted(self.browser, "x", records)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 and page_number > 0:
                break
        return records

    # -- shared page helpers ----------------------------------------------

    def _navigator(self, target: Target, page: Any) -> Any:
        url = target_url(target)
        allowed = X_HOSTS
        if getattr(self.browser, "allow_navigation", False):
            async def navigate(requested: str, page: Any = page, allowed: tuple[str, ...] = allowed) -> Any:
                await _raise_for_page_risk(page)
                response = await self.browser.navigate(page, requested, allowed_hosts=allowed)
                status = getattr(response, "status", None)
                if isinstance(status, int) and not isinstance(status, bool):
                    if status in {403, 429}:
                        raise CollectionStopped(f"http-{status}")
                    if not 200 <= status < 300:
                        raise SourceResponseError(f"X navigation returned http-{status}")
                await self._settle(page)
                await _raise_for_page_risk(page)
                return response

            return navigate
        _require_open_target(page, url)

        async def reload_only(requested: str, page: Any = page) -> None:
            # Without navigation authorization the exact target page must already
            # be open; collection then only reads what the page already shows.
            _require_open_target(page, requested)
            await self._settle(page)
            await _raise_for_page_risk(page)

        return reload_only

    @staticmethod
    async def _settle(page: Any) -> None:
        waiter = getattr(page, "wait_for_timeout", None)
        if callable(waiter):
            await waiter(_SCROLL_SETTLE_MS)

    @staticmethod
    async def _scroll(page: Any) -> None:
        await page.evaluate(
            "() => { window.scrollTo(0, document.documentElement.scrollHeight); return true; }"
        )


def _append(
    records: list[dict[str, Any]], seen: set[str], candidates: Sequence[Mapping[str, Any]]
) -> int:
    added = 0
    for record in candidates:
        key = dedup_key(record)
        if key is None or key in seen:
            continue
        seen.add(key)
        records.append(dict(record))
        added += 1
    return added


def _require_open_target(page: Any, url: str) -> None:
    actual = urlparse(getattr(page, "url", "") or "")
    expected = urlparse(url)
    if actual.scheme != "https" or actual.hostname not in X_HOSTS:
        raise PreconditionError("matching X page is required when navigation is disabled")
    if expected.path.startswith("/search"):
        actual_query = parse_qs(actual.query, keep_blank_values=True)
        expected_query = parse_qs(expected.query, keep_blank_values=True)
        if not actual.path.startswith("/search") or actual_query.get("q") != expected_query.get("q"):
            raise PreconditionError("matching X search page is required when navigation is disabled")
        return
    if actual.path.rstrip("/") != expected.path.rstrip("/"):
        raise PreconditionError("matching X profile page is required when navigation is disabled")


async def _raise_for_page_risk(page: Any) -> None:
    from ..extraction import risk_expression
    probe = getattr(page, "evaluate", None)
    if not callable(probe):
        raise PreconditionError("risk observation unavailable")
    observation = await probe(risk_expression())
    if isinstance(observation, Mapping) and observation.get("risk") is True:
        raise CollectionStopped("challenge")


async def collect_creator(request: CollectionRequest, browser: Any) -> list[dict[str, Any]]:
    return await XCollector(request, browser).collect()


async def collect_search(request: CollectionRequest, browser: Any) -> list[dict[str, Any]]:
    return await XCollector(request, browser).collect()


__all__ = [
    "CAPTURE_TIMEOUT_MS",
    "CANONICAL_HOST",
    "CaptureTimeout",
    "CollectionStopped",
    "OPERATIONS",
    "OPERATION_POSTS",
    "OPERATION_SEARCH",
    "PARSER_VERSION",
    "SourceResponseError",
    "XCollector",
    "X_HOSTS",
    "collect_creator",
    "collect_search",
    "dedup_key",
    "hashtag_url",
    "normalize_page_payload",
    "normalize_post",
    "normalize_response_item",
    "normalize_response_payload",
    "observed_now",
    "observed_operation",
    "parse_display_metric",
    "parse_iso",
    "profile_url",
    "require_x_capability",
    "response_matches",
    "response_payload",
    "search_url",
    "target_binding",
    "target_url",
]
