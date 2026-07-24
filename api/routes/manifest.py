"""
Manifest Routes
===============
Endpoints for Stremio/Nuvio manifest generation.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, url_for
from urllib.parse import unquote

from config import InvalidHashError, logger
from services.crypto import decode_hash
from utils import format_timestamp
from xtream_client import XtreamClient

manifest_bp = Blueprint("manifest", __name__)


@manifest_bp.route("/manifest.json")
def manifest_default() -> tuple[Any, int]:
    """Returns default addon manifest (configuration page pointer)."""
    return jsonify({
        "id": "org.xtremio.config",
        "version": "1.0.2",
        "name": "Xtremio",
        "description": "Watch movies and series from your Xtream server",
        "logo": url_for("static", filename="logo.png", _external=True),
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie", "series", "tv"],
        "catalogs": [],
        "idPrefixes": ["tt"],
        "behaviorHints": {
            "configurable": True,
            "configurationRequired": True,
        },
    }), 200


@manifest_bp.route("/<hash>/manifest.json")
def manifest_with_hash(hash: str) -> tuple[Any, int]:
    """Generates personalized manifest for a configured server."""
    logger.info("Generating manifest for hash: %s...", hash[:20])
    hash = unquote(hash)

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return jsonify({"error": "Invalid hash"}), 400

    client = XtreamClient.from_config(config)
    xtr = client.xtr
    name = config.get("name") or f"{xtr} - Xtremio"

    # Authentication
    try:
        client.authenticate()
    except Exception as e:
        logger.warning("Auth failed for manifest: %s", e)
        return jsonify({"error": "Invalid credentials"}), 401

    user_info = client.user_info

    # Build catalogs using XtreamClient
    catalogs = []

    # Movies
    vod_categories = client.get_vod_categories()
    cat_names = [c["category_name"] for c in vod_categories]
    catalogs.append({
        "type": "movie",
        "id": xtr,
        "name": f"{name} - Movies",
        "extra": [
            {"name": "genre", "options": cat_names},
            {"name": "search"},
            {"name": "skip"},
        ],
    })

    # Series
    series_categories = client.get_series_categories()
    cat_names = [c["category_name"] for c in series_categories]
    catalogs.append({
        "type": "series",
        "id": xtr,
        "name": f"{name} - Series",
        "extra": [
            {"name": "genre", "options": cat_names},
            {"name": "search"},
            {"name": "skip"},
        ],
    })

    # Live TV
    live_categories = client.get_live_categories()
    cat_names = [c["category_name"] for c in live_categories]
    catalogs.append({
        "type": "tv",
        "id": xtr,
        "name": f"{name} - TV",
        "extra": [
            {"name": "genre", "options": cat_names},
            {"name": "search"},
            {"name": "skip"},
        ],
    })

    description = _build_user_description(
        client.username, user_info, client.server_info, client.base_url
    )

    response = jsonify({
        "id": f"org.xtremio.{xtr}",
        "version": "1.0.2",
        "name": name,
        "description": description,
        "logo": url_for("static", filename="logo.png", _external=True),
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie", "series", "tv"],
        "catalogs": catalogs,
        "idPrefixes": ["tt", xtr],
        "behaviorHints": {
            "configurable": True,
            "configurationRequired": False,
        },
    })
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


def _build_user_description(
    username: str,
    user_info: Any,
    server_info: Any,
    base_url: str,
) -> str:
    """Generates user description using user_info and server_info."""
    exp_str = format_timestamp(
        user_info.exp_date if user_info else None,
        "Account expiry date",
    )
    created_str = format_timestamp(
        user_info.created_at if user_info else None,
        "Account created at",
    )

    server_tz = ""
    if server_info and server_info.timezone:
        server_tz = f"\nServer timezone: {server_info.timezone}"

    return "\n".join([
        f"Hello {username}!",
        "You will be able to watch movies and series from your Xtream server",
        "",
        "Server info:",
        f"Server URL: {base_url}",
        f"Max connections: {user_info.max_connections if user_info else 'N/A'}",
        f"Active connections: {user_info.active_connections if user_info else 'N/A'}",
        f"Account status: {user_info.status_display if user_info else 'N/A'}",
        f"Trial account: {'Yes' if user_info and user_info.is_trial else 'No'}",
        exp_str,
        created_str,
        server_tz,
        "",
        "This addon is not an official addon from Stremio. It was made by the community.",
        "If you have any problem, please contact the developer of this addon.",
        "Enjoy it!",
    ])
