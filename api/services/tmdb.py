"""
Xtremio TMDB Service
====================
The Movie Database (TMDB) integration for IMDB lookup.
Provides localized title, original title, and release year extraction.
"""
from __future__ import annotations

from typing import Any, Optional

from config import TMDB_API_KEY, logger
from services.cache import imdb_match_cache


def find_by_imdb(
    imdb_id: str,
    language: str = "en-US",
    http_get_fn=None,
) -> Optional[dict[str, Any]]:
    """
    Fetches information from TMDB using an IMDB ID.
    Uses imdb_match_cache (1h TTL) for longer-lived match results.

    Args:
        imdb_id: IMDB ID (e.g., tt1234567).
        language: Language code for response.
        http_get_fn: HTTP GET function.

    Returns:
        TMDB response dictionary or None.
    """
    cache_key = f"imdb:{imdb_id}:{language}"
    cached = imdb_match_cache.get(cache_key)
    if cached is not None:
        return cached

    if http_get_fn is None:
        return None

    try:
        result = http_get_fn(
            f"https://api.themoviedb.org/3/find/{imdb_id}",
            params={
                "api_key": TMDB_API_KEY,
                "external_source": "imdb_id",
                "language": language,
            },
        )
        if result:
            imdb_match_cache.set(cache_key, result)
        return result
    except Exception as e:
        logger.error("Error fetching TMDB for %s: %s", imdb_id, e)
        return None


# =============================================================================
# MOVIE HELPERS
# =============================================================================


def get_movie_name(tmdb_response: dict[str, Any]) -> Optional[str]:
    """Extracts localized movie title from TMDB response."""
    results = tmdb_response.get("movie_results", [])
    return results[0]["title"] if results else None


def get_movie_original_title(tmdb_response: dict[str, Any]) -> Optional[str]:
    """Extracts original (untranslated) movie title from TMDB response."""
    results = tmdb_response.get("movie_results", [])
    return results[0].get("original_title") if results else None


def get_movie_year(tmdb_response: dict[str, Any]) -> Optional[str]:
    """Extracts release year from TMDB movie response (e.g. '2024')."""
    results = tmdb_response.get("movie_results", [])
    if not results:
        return None
    release_date = results[0].get("release_date", "")
    if release_date and len(release_date) >= 4:
        return release_date[:4]
    return None


def get_movie_tmdb_id(tmdb_response: dict[str, Any]) -> Optional[int]:
    """Extracts movie TMDB ID from response."""
    results = tmdb_response.get("movie_results", [])
    return results[0]["id"] if results else None


# =============================================================================
# SERIES HELPERS
# =============================================================================


def get_series_name(tmdb_response: dict[str, Any]) -> Optional[str]:
    """Extracts localized series title from TMDB response."""
    results = tmdb_response.get("tv_results", [])
    return results[0]["name"] if results else None


def get_series_original_name(tmdb_response: dict[str, Any]) -> Optional[str]:
    """Extracts original (untranslated) series name from TMDB response."""
    results = tmdb_response.get("tv_results", [])
    return results[0].get("original_name") if results else None


def get_series_year(tmdb_response: dict[str, Any]) -> Optional[str]:
    """Extracts first air year from TMDB series response (e.g. '2024')."""
    results = tmdb_response.get("tv_results", [])
    if not results:
        return None
    first_air_date = results[0].get("first_air_date", "")
    if first_air_date and len(first_air_date) >= 4:
        return first_air_date[:4]
    return None


def get_series_tmdb_id(tmdb_response: dict[str, Any]) -> Optional[int]:
    """Extracts series TMDB ID from response."""
    results = tmdb_response.get("tv_results", [])
    return results[0]["id"] if results else None
