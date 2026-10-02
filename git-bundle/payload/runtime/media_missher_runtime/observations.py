"""Conservative enrichment of repeated observations of the same native entity.

Callers establish the platform/kind/native-ID key before merging. Existing
nonempty values, identity and completion claims are retained. A duplicate can
add verified missing fields without becoming a new record or proving progress.
"""
from copy import deepcopy

_IDENTITY = frozenset({"platform", "type", "native_id", "dynamic_id", "bvid", "note_id",
                       "aweme_id", "mblog_id", "tweet_id", "uid", "author_id"})
_METRICS = frozenset({"liked", "comments", "shares", "collected", "views", "quotes", "bookmarks"})
_CLAIMS = frozenset({"complete", "text_complete", "profile_status", "evidence_level",
                    "backend", "observed_at", "source_url", "source", "engagement_scope"})


def missing(value):
    return value is None or value == "" or value == [] or value == {}


def merge_observation(existing, incoming):
    """Fill gaps in-place, keeping independent Bilibili metric scopes apart."""
    if any(not missing(existing.get(key)) and not missing(incoming.get(key))
           and existing[key] != incoming[key] for key in _IDENTITY):
        return
    same_scope = existing.get("engagement_scope") == incoming.get("engagement_scope")
    sources = dict(existing.get("field_sources") or {})
    accepted = set()
    for key, value in incoming.items():
        if key in _IDENTITY | _CLAIMS or key in {"field_sources", "field_quality", "metric_display", "target_identity", "target_identities"} or missing(value):
            continue
        if key in _METRICS and not same_scope:
            continue
        if key == "engagement_observations":
            target = existing.setdefault(key, {})
            if isinstance(target, dict) and isinstance(value, dict):
                for scope, observation in value.items():
                    if scope not in target:
                        target[scope] = deepcopy(observation)
            continue
        if missing(existing.get(key)):
            existing[key] = deepcopy(value)
            accepted.add(key)
            sources[key] = {name: incoming[name] for name in ("observed_at", "source_url", "source", "evidence_level") if not missing(incoming.get(name))}
            if isinstance(incoming.get("field_sources"), dict) and key in incoming["field_sources"]:
                sources[key] = deepcopy(incoming["field_sources"][key])
    # Metadata belongs to the accepted value, never to the duplicate as a whole.
    for name in ("metric_display", "field_quality"):
        metadata = incoming.get(name)
        if isinstance(metadata, dict):
            selected = {key: deepcopy(value) for key, value in metadata.items() if key in accepted}
            if selected:
                if not isinstance(existing.get(name), dict):
                    existing[name] = {}
                existing[name].update(selected)
    if sources:
        existing["field_sources"] = sources
