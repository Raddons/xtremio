"""
Stream Routes
=============
Endpoints for resolving playback stream URLs.
Supports direct ID lookup and IMDB ID matching via TMDB.

Matching improvements:
- Year filtering to reduce false positives (±1 year tolerance)
- Original title fallback when localized name yields zero results
- Dedicated match caches (IMDb→TMDB 1h, TMDB→streamId 1h per provider)
- Category name in stream description (e.g. [Legendado], [Dublado])
"""
from __future__ import annotations

import re
from typing import Any, Optional

from flask import Blueprint, jsonify
from urllib.parse import unquote

from config import InvalidHashError, MAX_STREAMS_LIMIT, logger
from services.cache import stream_match_cache
from services.crypto import decode_hash
from services import tmdb as tmdb_service
from utils import (
    agroup_channels,
    format_date,
    get_safe_value,
    normalize_string,
)
from xtream_client import XtreamClient, http_get

stream_bp = Blueprint("stream", __name__)


@stream_bp.route("/<hash>/stream/<type>/<id>.json")
def stream(hash: str, type: str, id: str) -> tuple[Any, int]:
    """Returns available playback streams for a content item."""
    hash = unquote(hash)
    type = unquote(type)
    id = unquote(id)

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return jsonify({"streams": []}), 200

    client = XtreamClient.from_config(config)

    if not id.startswith("tt"):
        return _get_direct_stream(client, type, id)

    return _get_stream_by_imdb(client, type, id)


# =============================================================================
# EPG ENDPOINTS
# =============================================================================


@stream_bp.route("/<hash>/epg/<stream_id>.json")
def epg(hash: str, stream_id: str) -> tuple[Any, int]:
    """Returns short EPG (program guide) for a live TV channel."""
    hash = unquote(hash)

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return jsonify({"epg": []}), 200

    client = XtreamClient.from_config(config)
    epg_data = client.get_short_epg(stream_id)

    return jsonify({"epg": epg_data}), 200


@stream_bp.route("/<hash>/epg/<stream_id>/full.json")
def epg_full(hash: str, stream_id: str) -> tuple[Any, int]:
    """Returns full EPG for a live TV channel."""
    hash = unquote(hash)

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return jsonify({"epg": []}), 200

    client = XtreamClient.from_config(config)
    epg_data = client.get_full_epg(stream_id)

    return jsonify({"epg": epg_data}), 200


# =============================================================================
# XTREAM SERVER HEALTH CHECK
# =============================================================================


@stream_bp.route("/<hash>/health.json")
def server_health(hash: str) -> tuple[Any, int]:
    """Checks Xtream server connectivity and account status."""
    hash = unquote(hash)

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return jsonify({"error": "Invalid hash"}), 400

    client = XtreamClient.from_config(config)
    health = client.get_server_health()

    return jsonify(health), 200


# =============================================================================
# M3U PLAYLIST GENERATION
# =============================================================================


@stream_bp.route("/<hash>/playlist.m3u")
def generate_m3u(hash: str) -> tuple[str, int, dict[str, str]]:
    """Generates an M3U playlist file containing channels and movies."""
    from flask import request

    hash = unquote(hash)

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return "Invalid hash", 400, {"Content-Type": "text/plain"}

    client = XtreamClient.from_config(config)

    include_live = request.args.get("live", "1") == "1"
    include_vod = request.args.get("vod", "1") == "1"
    include_series = request.args.get("series", "0") == "1"

    m3u_content = client.generate_m3u(
        include_live=include_live,
        include_vod=include_vod,
        include_series=include_series,
    )

    return m3u_content, 200, {
        "Content-Type": "audio/x-mpegurl",
        "Content-Disposition": "attachment; filename=playlist.m3u",
    }


# =============================================================================
# DIRECT STREAM (by internal ID)
# =============================================================================


def _get_direct_stream(
    client: XtreamClient, type: str, id: str
) -> tuple[Any, int]:
    """Retrieves stream directly using internal ID."""
    xtr, id = id.split(":", 1)

    if type == "series":
        parts = id.split(":")
        if len(parts) < 3:
            return jsonify({"streams": []}), 200

        series_id, season, episode = parts[0], parts[1], parts[2]
        ep = client.find_episode(series_id, season, episode)

        if not ep:
            return jsonify({"streams": []}), 200

        ep_info = ep.get("info", {})
        ext = ep.get("container_extension", "mp4")
        result = {
            "streams": [{
                "name": ep.get("title", ""),
                "url": client.build_series_url(str(ep["id"]), ext),
                "description": ep_info.get("plot", ""),
                "released": format_date(
                    get_safe_value(ep_info, "releasedate", "releaseDate")
                ),
            }]
        }

    elif type == "movie":
        film = client.get_vod_info(id)

        if not film:
            return jsonify({"streams": []}), 200

        info = film.get("info", {})
        movie_data = film.get("movie_data", {})
        name = info.get("name") or movie_data.get("name", "")
        ext = movie_data.get("container_extension", "mp4")

        result = {
            "streams": [{
                "name": name,
                "url": client.build_movie_url(id, ext),
                "description": info.get("plot", ""),
                "released": format_date(
                    get_safe_value(info, "releasedate", "releaseDate")
                ),
            }]
        }

    elif type == "tv":
        lives = client.get_live_streams()

        if not lives:
            return jsonify({"streams": []}), 200

        if ":" in id:
            group_id = id.split(":")[1]
            grouped = agroup_channels(lives)
            for group_data in grouped.values():
                if group_data["id"] == group_id:
                    result = {
                        "streams": [
                            {
                                "name": ch["name"],
                                "url": client.build_live_url(
                                    str(ch["stream_id"])
                                ),
                            }
                            for ch in group_data["list"]
                        ]
                    }
                    break
            else:
                return jsonify({"streams": []}), 200
        else:
            live = next(
                (item for item in lives if item["stream_id"] == int(id)),
                None,
            )
            if not live:
                return jsonify({"streams": []}), 200

            result = {
                "streams": [{
                    "name": live["name"],
                    "url": client.build_live_url(id),
                }]
            }
    else:
        return jsonify({"streams": []}), 200

    response = jsonify(result)
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response, 200


# =============================================================================
# YEAR MATCHING HELPER
# =============================================================================


def _extract_year_from_item(item: dict[str, Any]) -> Optional[str]:
    """
    Extracts the release year from a provider item.
    Checks 'year', 'releasedate', 'releaseDate', 'added' fields.
    """
    # Direct year field
    year = item.get("year")
    if year:
        year_str = str(year).strip()
        if len(year_str) >= 4 and year_str[:4].isdigit():
            return year_str[:4]

    # From releasedate / releaseDate fields
    for key in ("releasedate", "releaseDate", "release_date"):
        date_str = item.get(key, "")
        if date_str and len(str(date_str)) >= 4:
            candidate = str(date_str)[:4]
            if candidate.isdigit():
                return candidate

    return None


def _year_matches(item_year: Optional[str], tmdb_year: Optional[str], tolerance: int = 1) -> bool:
    """
    Checks if the provider item year matches the TMDB year within ±tolerance.
    If either year is missing, returns True (permissive — don't filter out).
    """
    if not item_year or not tmdb_year:
        return True
    try:
        return abs(int(item_year) - int(tmdb_year)) <= tolerance
    except (ValueError, TypeError):
        return True


# =============================================================================
# CATEGORY DESCRIPTION HELPER
# =============================================================================


def _prepend_category(
    description: str,
    item: dict[str, Any],
    category_map: dict[str, str],
) -> str:
    """
    Prepends category name to the description string.
    E.g. '[Legendado] Original plot...'
    """
    cat_id = str(item.get("category_id", ""))
    cat_name = category_map.get(cat_id, "")
    if cat_name:
        prefix = f"[{cat_name}]"
        if description:
            return f"{prefix} {description}"
        return prefix
    return description


# =============================================================================
# STREAM BY IMDB (via TMDB) — with caching, year, original title fallback
# =============================================================================


def _get_stream_by_imdb(
    client: XtreamClient, type: str, imdb_id: str
) -> tuple[Any, int]:
    """
    Searches streams by IMDB ID using TMDB.
    Flow:
      1. Check stream_match_cache → hit? return immediately
      2. TMDB /find → get localized title, original title, year
      3. Search provider by localized title + year filter
      4. If zero results → retry with original title + year filter
      5. Prepend category name to description
      6. Cache result in stream_match_cache
    """
    if type == "series" and ":" in imdb_id:
        parts = imdb_id.split(":")
        imdb_id_clean, season, episode = parts[0], parts[1], parts[2]
    else:
        imdb_id_clean = imdb_id
        season = episode = None

    # 1. Check stream match cache
    match_cache_key = f"match:{client.base_url}:{client.username}:{type}:{imdb_id}"
    cached_streams = stream_match_cache.get(match_cache_key)
    if cached_streams is not None:
        logger.info("Stream match cache HIT for %s", imdb_id)
        response = jsonify({"streams": cached_streams})
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response, 200

    # 2. TMDB lookup
    program = tmdb_service.find_by_imdb(
        imdb_id_clean,
        language=client.lang,
        http_get_fn=http_get,
    )

    if not program:
        return jsonify({"streams": []}), 200

    streams: list[dict[str, Any]] = []

    if type == "series" and program.get("tv_results"):
        localized_name = tmdb_service.get_series_name(program)
        original_name = tmdb_service.get_series_original_name(program)
        year = tmdb_service.get_series_year(program)

        logger.info(
            "TMDB series match: localized='%s', original='%s', year=%s",
            localized_name, original_name, year,
        )

        # 3. Try localized name first
        if localized_name:
            streams = _search_series_streams(client, localized_name, season, episode, year)

        # 4. Fallback to original name if zero results
        if not streams and original_name and original_name != localized_name:
            logger.info("Retrying series search with original name: '%s'", original_name)
            streams = _search_series_streams(client, original_name, season, episode, year)

    elif type == "movie" and program.get("movie_results"):
        localized_name = tmdb_service.get_movie_name(program)
        original_name = tmdb_service.get_movie_original_title(program)
        tmdb_id = tmdb_service.get_movie_tmdb_id(program)
        year = tmdb_service.get_movie_year(program)

        logger.info(
            "TMDB movie match: localized='%s', original='%s', year=%s, tmdb_id=%s",
            localized_name, original_name, year, tmdb_id,
        )

        # 3. Try localized name first
        if localized_name:
            streams = _search_movie_streams(client, localized_name, tmdb_id, year)

        # 4. Fallback to original title if zero results
        if not streams and original_name and original_name != localized_name:
            logger.info("Retrying movie search with original title: '%s'", original_name)
            streams = _search_movie_streams(client, original_name, tmdb_id, year)

    # 6. Cache the match result (even if empty, to avoid repeated misses)
    if streams:
        stream_match_cache.set(match_cache_key, streams)
        logger.info("Cached %d stream(s) for %s", len(streams), imdb_id)

    response = jsonify({"streams": streams})
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response, 200


# =============================================================================
# SERIES SEARCH — with year filter + category in description
# =============================================================================


def _search_series_streams(
    client: XtreamClient,
    name: str,
    season: Optional[str],
    episode: Optional[str],
    year: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Searches series streams by title with year filtering.
    Appends category name to description.
    """
    similar_items = client.search_series_by_name(name)

    # Year filter: only keep items whose year matches TMDB ±1
    if year:
        year_filtered = [
            item for item in similar_items
            if _year_matches(_extract_year_from_item(item), year)
        ]
        # Only apply filter if it doesn't eliminate everything
        if year_filtered:
            similar_items = year_filtered
            logger.debug("Year filter kept %d/%d series", len(year_filtered), len(similar_items))

    # Build category map for descriptions
    category_map = client.get_series_category_map()

    streams = []
    for item in similar_items:
        ep = client.find_episode(
            str(item["series_id"]),
            season or "1",
            episode or "1",
        )
        if not ep:
            continue

        ep_info = ep.get("info", {})
        ext = ep.get("container_extension", "mp4")

        # Build description with category prefix
        plot = ep_info.get("plot", "")
        description = _prepend_category(plot, item, category_map)

        streams.append({
            "name": ep.get("title", ""),
            "url": client.build_series_url(str(ep["id"]), ext),
            "description": description,
            "released": format_date(
                get_safe_value(ep_info, "releasedate", "releaseDate")
            ),
            "behaviorHints": {
                "bingeGroup": f"{client.xtr}-{item['series_id']}"
            },
        })

    return streams


# =============================================================================
# MOVIE SEARCH — with year filter + category in description
# =============================================================================


def _search_movie_streams(
    client: XtreamClient,
    name: str,
    tmdb_id: Optional[int],
    year: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Searches movie streams by title with year filtering and TMDB ID validation.
    Appends category name to description.
    """
    similar_items = client.search_vod_by_name(name)

    # Year filter: only keep items whose year matches TMDB ±1
    if year:
        year_filtered = [
            item for item in similar_items
            if _year_matches(_extract_year_from_item(item), year)
        ]
        # Only apply filter if it doesn't eliminate everything
        if year_filtered:
            similar_items = year_filtered
            logger.debug("Year filter kept %d/%d movies", len(year_filtered), len(similar_items))

    # Build category map for descriptions
    category_map = client.get_vod_category_map()

    streams = []
    for item in similar_items:
        film = client.get_vod_info(str(item["stream_id"]))

        if not film:
            continue

        film_info = film.get("info", {})

        # TMDB ID cross-check (if both sides have it)
        if (
            tmdb_id
            and film_info.get("tmdb_id")
            and str(film_info["tmdb_id"]) != str(tmdb_id)
        ):
            continue

        ext = item.get("container_extension", "mp4")

        # Build description with category prefix
        plot = film_info.get("plot", "")
        description = _prepend_category(plot, item, category_map)

        streams.append({
            "name": item.get("name", ""),
            "url": client.build_movie_url(str(item["stream_id"]), ext),
            "description": description,
            "released": format_date(
                get_safe_value(film_info, "releasedate", "releaseDate")
            ),
        })

    return streams
