"""
Catalog Routes
==============
Endpoints for movie, series, and live TV catalogs.
Supports genre filtering, search, and real pagination with skip.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from flask import Blueprint, jsonify
from urllib.parse import unquote

from config import (
    CONTENT_TYPE_MAP,
    DEFAULT_CATALOG_LIMIT,
    MAX_CATALOG_LIMIT,
    InvalidHashError,
    logger,
)
from services.crypto import decode_hash
from utils import (
    agroup_channels,
    convert_to_url,
    extract_xtr_from_url,
    format_date,
    normalize_string,
)
from xtream_client import XtreamClient

catalog_bp = Blueprint("catalog", __name__)


# =============================================================================
# CATALOG ROUTES
# =============================================================================


@catalog_bp.route("/<hash>/catalog/<type>/<xtr>/search=<search>.json")
@catalog_bp.route("/<hash>/catalog/<type>/<xtr>/genre=<genre>.json")
@catalog_bp.route("/<hash>/catalog/<type>/<xtr>/skip=<int:skip>.json")
@catalog_bp.route("/<hash>/catalog/<type>/<xtr>/genre=<genre>&skip=<int:skip>.json")
@catalog_bp.route("/<hash>/catalog/<type>/<xtr>.json")
def catalog(
    hash: str,
    type: str,
    xtr: str,
    genre: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
) -> tuple[Any, int]:
    """
    Returns content catalog supporting pagination.
    """
    logger.info(
        "Catalog request: type=%s, genre=%s, search=%s, skip=%d",
        type, genre, search, skip,
    )

    hash = unquote(hash)
    type = unquote(type)
    xtr = unquote(xtr)
    genre = unquote(genre).replace("genre=", "") if genre else None
    search = unquote(search).replace("search=", "") if search else None

    try:
        config = decode_hash(hash)
    except (InvalidHashError, Exception):
        return jsonify({"metas": []}), 200

    client = XtreamClient.from_config(config)
    expected_xtr = client.xtr

    if xtr != expected_xtr:
        logger.warning("XTR mismatch: %s != %s", xtr, expected_xtr)
        return jsonify({"metas": []}), 200

    content_type = CONTENT_TYPE_MAP.get(type)
    if not content_type:
        return jsonify({"metas": []}), 200

    items = _fetch_catalog_items(client, type, content_type, genre, search)

    if type != "tv":
        paginated = items[skip:skip + DEFAULT_CATALOG_LIMIT]
    else:
        paginated = items

    metas = _build_catalog_metas(paginated, type, xtr)

    logger.info("Catalog response with %d items (skip=%d)", len(metas), skip)
    return jsonify({"metas": metas}), 200


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _fetch_catalog_items(
    client: XtreamClient,
    type: str,
    content_type: str,
    genre: Optional[str],
    search: Optional[str],
) -> list[dict[str, Any]]:
    """Fetches catalog items using XtreamClient."""
    if genre:
        if content_type == "vod":
            categories = client.get_vod_categories()
        elif content_type == "series":
            categories = client.get_series_categories()
        else:
            categories = client.get_live_categories()

        category = next(
            (c for c in categories if c.get("category_name") == genre),
            None,
        )
        if not category:
            return []

        category_id = str(category["category_id"])

        if content_type == "vod":
            return client.get_vod_streams(category_id=category_id)
        elif content_type == "series":
            return client.get_series(category_id=category_id)
        else:
            return client.get_live_streams(category_id=category_id)

    elif search:
        if content_type == "vod":
            all_items = client.get_vod_streams()
        elif content_type == "series":
            all_items = client.get_series()
        else:
            all_items = client.get_live_streams()

        normalized_search = normalize_string(search)
        return [
            item for item in all_items
            if re.search(
                re.escape(normalized_search),
                normalize_string(item.get("name", "")),
            )
        ]

    else:
        if content_type == "vod":
            return client.get_vod_streams()
        elif content_type == "series":
            return client.get_series()
        else:
            return client.get_live_streams()


def _build_catalog_metas(
    items: list[dict[str, Any]], type: str, xtr: str
) -> list[dict[str, Any]]:
    """Builds meta items list for the catalog."""
    metas = []

    if type != "tv":
        for item in items:
            item_id = (
                item.get("series_id") if type == "series"
                else item.get("stream_id")
            )
            metas.append({
                "id": f"{xtr}:{item_id}",
                "name": item.get("name", ""),
                "poster": item.get("cover") or item.get("stream_icon", ""),
                "posterShape": "poster",
                "type": type,
                "releaseInfo": (
                    format_date(item["releasedate"])
                    if "releasedate" in item
                    else None
                ),
                "imdbRating": item.get("rating", ""),
            })
    else:
        grouped_names = agroup_channels(items)
        for group_key, group_data in grouped_names.items():
            metas.append({
                "id": f"{xtr}:ai:{group_data['id']}",
                "name": group_data["name"],
                "poster": group_data["logo"],
                "posterShape": "square",
                "type": "tv",
                "description": "\n".join(
                    i["name"] for i in group_data["list"]
                ),
            })

    return metas
