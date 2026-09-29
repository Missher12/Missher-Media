"""Read the private, data-only exclusion plan produced by the controller."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

from .models import CollectionRequest


def _unique_object(pairs: list) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate exclusion key")
        value[key] = item
    return value


def apply_exclusions(path: Path, requests: list[CollectionRequest]) -> list[CollectionRequest]:
    """Never changes requested counts or enables browser actions."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_size > 2 * 1024 * 1024:
            raise ValueError("unsafe exclusion file")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = json.load(handle, object_pairs_hook=_unique_object)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, dict) or set(value) != {"schema", "platforms"} or type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("invalid exclusion schema")
    platforms = value["platforms"]
    if not isinstance(platforms, dict) or set(platforms) != {request.platform for request in requests} or any(not isinstance(ids, list) for ids in platforms.values()):
        raise ValueError("exclusion platforms do not match")
    return [replace(request, exclude_ids=tuple(platforms[request.platform])) for request in requests]
