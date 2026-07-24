"""
Meta Routes
===========
Endpoints for movie, series, and live TV metadata.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify
from urllib.parse import unquote

from config import InvalidHashError, logger
from services.crypto import decode_hash
from utils import (
    agroup_channels,
    format_date,
    get_safe_value,
)
from xtream_client import XtreamClient

meta_bp = Blueprint("meta", __name__)


@meta_bp.route("/<hash>/meta/<type>/<id>.json")
def meta(hash: str, type: str, id: str) -> tuple[Any, int]:
    """Returns metadata for a specific content item."""
    logger.info("Processing meta request for type: %s, id: %s", type, id)
    hash = unquote(hash)
    type = unquote(type)
    id_decoded = unquote(id)

    if ":" in id_decoded:
        xtr, id = id_decoded.split(":", 1)
    else:
        xtr, id = id_decoded, id_decoded

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return jsonify({"meta": {}}), 200

    client = XtreamClient.from_config(config)
    cat_new = ":" in id
    if cat_new:
        id = id.split(":")[1]

    if "tt" in id:
        logger.debug("IMDB ID detected in meta request: %s", id)
        return jsonify({"meta": {}}), 200

    if xtr != client.xtr:
        logger.warning("XTR mismatch: %s != %s", xtr, client.xtr)
        return jsonify({"meta": {}}), 200

    if type == "series":
        return _get_series_meta(client, xtr, id)
    elif type == "movie":
        return _get_movie_meta(client, xtr, id)
    elif type == "tv":
        return _get_tv_meta(client, xtr, id, cat_new)

    return jsonify({"meta": {}}), 200


# =============================================================================
# HANDLERS BY TYPE
# =============================================================================


def _get_series_meta(
    client: XtreamClient, xtr: str, series_id: str
) -> tuple[Any, int]:
    """Retrieves metadata for a series."""
    program = client.get_series_info(series_id)

    if not program or "episodes" not in program:
        return jsonify({"meta": {}}), 200

    videos = []
    for season, episodes in program["episodes"].items():
        for episode in episodes:
            ep_info = episode.get("info", {})
            videos.append({
                "id": f"{xtr}:{series_id}:{season}:{episode['episode_num']}",
                "title": episode.get("title", ""),
                "episode": episode["episode_num"],
                "season": episode.get("season", season),
                "overview": ep_info.get("plot", ""),
                "released": format_date(
                    get_safe_value(ep_info, "releasedate", "releaseDate")
                ),
                "thumbnail": (
                    ep_info.get("movie_image")
                    or program["info"].get("cover", "")
                ),
            })

    info = program.get("info", {})
    meta_data = {
        "id": f"{xtr}:{series_id}",
        "name": info.get("name", ""),
        "poster": info.get("cover", ""),
        "background": (
            info.get("backdrop_path", [""])[0]
            if info.get("backdrop_path")
            else ""
        ),
        "description": info.get("plot", ""),
        "genre": info.get("genre", ""),
        "imdbRating": info.get("rating", ""),
        "released": format_date(
            get_safe_value(info, "releaseDate", "releasedate")
        ),
        "type": "series",
        "videos": videos,
    }

    return jsonify({"meta": meta_data}), 200


def _get_movie_meta(
    client: XtreamClient, xtr: str, movie_id: str
) -> tuple[Any, int]:
    """Retrieves metadata for a movie."""
    program = client.get_vod_info(movie_id)

    if not program or "info" not in program:
        return jsonify({"meta": {}}), 200

    info = program.get("info", {})
    movie_data = program.get("movie_data", {})

    name = info.get("name") or movie_data.get("name", "")
    poster = info.get("cover_big") or info.get("backdrop", "")

    meta_data = {
        "id": f"{xtr}:{movie_id}",
        "name": name,
        "poster": poster,
        "background": (
            info.get("backdrop_path", [""])[0]
            if info.get("backdrop_path")
            else ""
        ),
        "description": info.get("plot", ""),
        "genre": info.get("genre", ""),
        "imdbRating": info.get("rating", ""),
        "released": format_date(
            get_safe_value(info, "releasedate", "releaseDate")
        ),
        "type": "movie",
        "runtime": info.get("duration", ""),
        "director": info.get("director", ""),
        "cast": info.get("cast", ""),
    }

    if "youtube_trailer" in info and info["youtube_trailer"]:
        meta_data["trailer"] = {
            "source": info["youtube_trailer"],
            "type": "Trailer",
        }

    return jsonify({"meta": meta_data}), 200


def _get_tv_meta(
    client: XtreamClient, xtr: str, live_id: str, cat_new: bool
) -> tuple[Any, int]:
    """Retrieves metadata for a live TV channel, including EPG when available."""
    all_lives = client.get_live_streams()

    if not all_lives:
        return jsonify({"meta": {}}), 200

    if cat_new:
        grouped_names = agroup_channels(all_lives)
        for group_key, group_data in grouped_names.items():
            if group_data["id"] == live_id:
                epg_info = _get_epg_for_group(client, group_data)

                meta = {
                    "id": f"{xtr}:ai:{group_data['id']}",
                    "name": group_data["name"],
                    "background": group_data["logo"],
                    "type": "tv",
                }
                if epg_info:
                    meta["description"] = epg_info

                return jsonify({"meta": meta}), 200
    else:
        live_id_clean = live_id.replace("null", "")
        try:
            live_id_int = int(live_id_clean)
        except ValueError:
            return jsonify({"meta": {}}), 200

        lives_map = {live["stream_id"]: live for live in all_lives}
        if live_id_int in lives_map:
            live = lives_map[live_id_int]

            epg_data = client.get_short_epg(str(live_id_int))
            epg_desc = ""
            if epg_data:
                epg_lines = []
                for prog in epg_data[:4]:
                    title = prog.get("title", "")
                    start = prog.get("start", "")
                    if title:
                        epg_lines.append(f"📺 {start} - {title}")
                if epg_lines:
                    epg_desc = "\n".join(["", "📋 Schedule:"] + epg_lines)

            return jsonify({"meta": {
                "id": f"{xtr}:{live_id}",
                "name": live.get("name", ""),
                "poster": live.get("stream_icon", ""),
                "background": live.get("stream_icon", ""),
                "type": "tv",
                "description": epg_desc if epg_desc else None,
            }}), 200

    return jsonify({"meta": {}}), 200


def _get_epg_for_group(
    client: XtreamClient,
    group_data: dict[str, Any],
) -> str:
    """Retrieves EPG information for a channel group."""
    if not group_data.get("list"):
        return ""

    first_channel = group_data["list"][0]
    stream_id = str(first_channel.get("stream_id", ""))
    if not stream_id:
        return ""

    epg_data = client.get_short_epg(stream_id)
    if not epg_data:
        return ""

    lines = ["📋 Schedule:"]
    for prog in epg_data[:3]:
        title = prog.get("title", "")
        start = prog.get("start", "")
        if title:
            lines.append(f"📺 {start} - {title}")

    return "\n".join(lines) if len(lines) > 1 else ""
