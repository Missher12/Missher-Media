"""Platform collectors built on top of the safe browser runtime."""

from .bilibili import BilibiliCollector, CollectionStopped, collect_creator, search

__all__ = ["BilibiliCollector", "CollectionStopped", "collect_creator", "search"]
