"""
Auth & Public Interface Routes
===============================
Public configuration endpoints, utilities, and server info pages.
"""
from __future__ import annotations

from typing import Any

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from config import InvalidHashError, logger
from services.crypto import decode_hash, encode_hash
from xtream_client import XtreamClient

auth_bp = Blueprint("auth", __name__)


def get_client_ip() -> str:
    """Gets client IP address considering proxy headers."""
    return (
        request.environ.get("HTTP_X_FORWARDED_FOR", request.remote_addr)
        or "unknown"
    )


# =============================================================================
# PUBLIC CONFIGURATION ROUTES
# =============================================================================


@auth_bp.route("/")
@auth_bp.route("/configure")
def index() -> str:
    """Main configuration page."""
    return render_template("config.html", config={})


@auth_bp.route("/<hash>/configure")
def config(hash: str) -> str:
    """Configuration page with pre-loaded hash."""
    try:
        config_data = decode_hash(hash)
    except (InvalidHashError, Exception):
        return "Invalid hash", 400

    return render_template("config.html", config=config_data)


@auth_bp.route("/<hash>/data")
def show_data(hash: str) -> str:
    """Displays server data and connection status."""
    try:
        config_data = decode_hash(hash)
    except Exception:
        return "Invalid hash", 400

    return render_template("show_data.html", config=config_data)


@auth_bp.route("/ip")
def ip() -> tuple[Any, int]:
    """Endpoint for retrieving client IP information."""
    client_ip = get_client_ip()
    return jsonify({"status": "success", "query": client_ip}), 200


@auth_bp.route("/favicon.ico")
def favicon() -> Any:
    """Serves the favicon."""
    from flask import current_app
    return send_from_directory(current_app.static_folder or "static", "favicon.ico")


@auth_bp.route("/encrypt", methods=["POST"])
def encrypt() -> tuple[Any, int]:
    """Endpoint for encrypting server configurations using Fernet or Base64."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Empty request body"}), 400

        use_fernet = data.pop("encrypted", False)
        encrypted = encode_hash(data, use_fernet=bool(use_fernet))
        return jsonify({"hash": encrypted}), 200
    except ValueError as e:
        logger.warning("Error encrypting configuration: %s", e)
        return jsonify({"error": str(e)}), 400
