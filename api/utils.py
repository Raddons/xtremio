"""
Xtremio Utility Functions
=========================
Utility functions for string normalization, date formatting, and general helpers.
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from idna import encode as idna_encode

from config import (
    MULTIPLE_SPACES_PATTERN,
    NON_ALPHANUMERIC_PATTERN,
    QUALITY_SUFFIX_PATTERN,
    logger,
)


# =============================================================================
# STRING NORMALIZATION
# =============================================================================


def normalize_string(s: Any) -> str:
    """
    Normalizes a string by removing accents, converting to lowercase,
    and stripping special non-alphanumeric characters.

    Args:
        s: String to normalize.

    Returns:
        Normalized string or empty string if input is invalid.
    """
    if not isinstance(s, str):
        return ""
    normalized = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower()
    normalized = NON_ALPHANUMERIC_PATTERN.sub(" ", normalized)
    normalized = MULTIPLE_SPACES_PATTERN.sub(" ", normalized)
    return normalized.strip()


# =============================================================================
# DATE FORMATTING
# =============================================================================


def format_date(date_str: Optional[str]) -> str:
    """
    Formats a date string in ISO 8601 format with 'Z' suffix.

    Args:
        date_str: Date string in YYYY-MM-DD format or empty string.

    Returns:
        Formatted date string in ISO 8601 or current timestamp.
    """
    if not date_str or not date_str.strip():
        return datetime.now().isoformat() + "Z"

    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").isoformat() + "Z"
    except ValueError as e:
        logger.debug("Invalid date '%s': %s", date_str, e)
        return date_str


def format_timestamp(timestamp: Optional[int], label: str) -> str:
    """Formats a Unix timestamp to human-readable string."""
    if not timestamp:
        return f"{label}: Not available"
    try:
        return f"{label}: {datetime.fromtimestamp(int(timestamp))}"
    except (ValueError, TypeError):
        return f"{label}: Not available"


# =============================================================================
# URL MANIPULATION
# =============================================================================


@lru_cache(maxsize=64)
def convert_to_url(url: str) -> str:
    """
    Converts a URL to IDNA format (Unicode-safe).

    Args:
        url: Original URL.

    Returns:
        Converted URL or original URL on error.
    """
    try:
        parsed_url = urlparse(url)
        netloc_parts = parsed_url.netloc.split(":")
        encoded_netloc = idna_encode(netloc_parts[0]).decode("utf-8")

        if len(netloc_parts) > 1:
            encoded_netloc = f"{encoded_netloc}:{netloc_parts[1]}"

        return urlunparse(parsed_url._replace(netloc=encoded_netloc))
    except Exception as e:
        logger.warning("Error converting URL '%s': %s", url, e)
        return url


def extract_xtr_from_url(base_url: str) -> str:
    """Extracts XTR identifier from the base URL."""
    return base_url.split("//")[1].split(".")[0] if "//" in base_url else ""


# =============================================================================
# DATA HELPERS
# =============================================================================


def get_safe_value(
    data: dict[str, Any],
    *keys: str,
    default: Any = "",
) -> Any:
    """
    Safely retrieves a value from a dictionary attempting multiple keys in order.

    Args:
        data: Data dictionary.
        *keys: Keys to try sequentially.
        default: Default fallback value if no key is found.

    Returns:
        Found value or default.
    """
    for key in keys:
        if key in data and data[key]:
            return data[key]
    return default


def agroup_channels(channels: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Groups channels by normalized name (ignoring quality suffixes like HD, FHD, 4K).

    Args:
        channels: List of channel data dictionaries.

    Returns:
        Dictionary with channels grouped by normalized name.
    """
    grouped_names: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"list": [], "id": "", "logo": "", "name": ""}
    )

    for channel in channels:
        name = QUALITY_SUFFIX_PATTERN.sub("", channel.get("name", "")).strip()
        name = MULTIPLE_SPACES_PATTERN.sub(" ", name).replace("[]", "").strip()

        keywords = name.split()
        group_key = normalize_string(" ".join(keywords[:2])) if keywords else ""
        if not group_key:
            continue

        grouped_names[group_key]["list"].append(channel)
        grouped_names[group_key]["id"] = hashlib.md5(group_key.encode()).hexdigest()

        if not grouped_names[group_key]["logo"] and channel.get("stream_icon"):
            grouped_names[group_key]["logo"] = channel["stream_icon"]

        if not grouped_names[group_key]["name"]:
            grouped_names[group_key]["name"] = name

    return grouped_names


def guess_language_from_timezone(timezone: Optional[str]) -> str:
    """Returns language code based on timezone."""
    from config import TIMEZONE_LANGUAGE_MAP
    return TIMEZONE_LANGUAGE_MAP.get(timezone or "", "en-US")
