"""
Xtremio Cache Service
=====================
TTL (Time-To-Live) cache implementation for key dataset types.
"""
from __future__ import annotations

import gc
import threading
import time
from typing import Any, Callable, Optional

from config import (
    CACHE_MAX_SIZE_CATALOG,
    CACHE_MAX_SIZE_CATEGORIES,
    CACHE_MAX_SIZE_EPG,
    CACHE_MAX_SIZE_MATCH,
    CACHE_MAX_SIZE_META,
    CACHE_TTL_CATALOG,
    CACHE_TTL_CATEGORIES,
    CACHE_TTL_EPG,
    CACHE_TTL_MATCH,
    CACHE_TTL_META,
    logger,
)


class TTLCache:
    """
    Thread-safe cache with per-entry Time-To-Live.
    """

    def __init__(self, maxsize: int = 128, ttl: int = 300, name: str = "default"):
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._maxsize = maxsize
        self._ttl = ttl
        self._name = name
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Gets value from cache if it exists and has not expired."""
        with self._lock:
            if key in self._cache:
                timestamp, value = self._cache[key]
                if time.time() - timestamp < self._ttl:
                    self._hits += 1
                    return value
                del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        """Adds or updates a value in the cache."""
        with self._lock:
            if len(self._cache) >= self._maxsize and key not in self._cache:
                self._evict_oldest()
            self._cache[key] = (time.time(), value)

    def get_or_fetch(self, key: str, fetch_fn: Callable[[], Any]) -> Any:
        """Gets item from cache or executes fetch_fn and caches the result."""
        cached = self.get(key)
        if cached is not None:
            return cached

        result = fetch_fn()
        if result is not None:
            self.set(key, result)
        return result

    def invalidate(self, key: str) -> None:
        """Removes a specific key from cache."""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Clears all entries from cache."""
        with self._lock:
            self._cache.clear()
            logger.debug("Cache '%s' cleared", self._name)

    def _evict_oldest(self) -> None:
        """Evicts the oldest entry in cache."""
        if not self._cache:
            return
        oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
        del self._cache[oldest_key]

    def cleanup_expired(self) -> int:
        """Removes all expired cache entries. Returns count of removed items."""
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, (ts, _) in self._cache.items()
                if now - ts >= self._ttl
            ]
            for key in expired_keys:
                del self._cache[key]
                removed += 1
        if removed:
            logger.debug("Cache '%s': %d expired entries removed", self._name, removed)
        return removed

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "name": self._name,
            "size": self.size,
            "maxsize": self._maxsize,
            "ttl": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{(self._hits / total * 100):.1f}%" if total > 0 else "N/A",
        }


# =============================================================================
# GLOBAL CACHE INSTANCES
# =============================================================================

category_cache = TTLCache(
    maxsize=CACHE_MAX_SIZE_CATEGORIES,
    ttl=CACHE_TTL_CATEGORIES,
    name="categories",
)

catalog_cache = TTLCache(
    maxsize=CACHE_MAX_SIZE_CATALOG,
    ttl=CACHE_TTL_CATALOG,
    name="catalog",
)

epg_cache = TTLCache(
    maxsize=CACHE_MAX_SIZE_EPG,
    ttl=CACHE_TTL_EPG,
    name="epg",
)

meta_cache = TTLCache(
    maxsize=CACHE_MAX_SIZE_META,
    ttl=CACHE_TTL_META,
    name="meta",
)

# Dedicated match caches — longer TTL for resolved lookups
imdb_match_cache = TTLCache(
    maxsize=CACHE_MAX_SIZE_MATCH,
    ttl=CACHE_TTL_MATCH,
    name="imdb_match",
)

stream_match_cache = TTLCache(
    maxsize=CACHE_MAX_SIZE_MATCH,
    ttl=CACHE_TTL_MATCH,
    name="stream_match",
)


def get_all_caches() -> list[TTLCache]:
    """Returns all cache instances."""
    return [
        category_cache, catalog_cache, epg_cache, meta_cache,
        imdb_match_cache, stream_match_cache,
    ]


def cleanup_all_caches() -> dict[str, int]:
    """Cleans up expired entries across all caches."""
    results = {}
    for cache in get_all_caches():
        removed = cache.cleanup_expired()
        results[cache._name] = removed
    return results


def get_cache_stats() -> list[dict[str, Any]]:
    """Returns cache statistics for all instances."""
    return [cache.stats for cache in get_all_caches()]


def cleanup_memory() -> None:
    """Triggers garbage collection and purges expired caches."""
    cleanup_all_caches()
    gc.collect()
