"""
Xtremio API Server — Application Factory
==========================================
Modular Flask server for interacting with Xtream servers.
Provides endpoints for configuration, manifests, metadata, catalogs, and playback streams.

Public Version: 1.0.2
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from flask import Flask, jsonify, render_template
from flask_compress import Compress
from flask_cors import CORS

from config import (
    IS_PRODUCTION,
    SECRET_KEY,
    TimeoutException,
    logger,
)
from services.cache import cleanup_all_caches, cleanup_memory


def create_app() -> Flask:
    """
    Application factory to build and configure the Flask application.

    Returns:
        Configured Flask instance.
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # ── Configuration ──
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # ── Extensions ──
    CORS(app)
    Compress(app)

    # ── Blueprints ──
    from routes.manifest import manifest_bp
    from routes.catalog import catalog_bp
    from routes.meta import meta_bp
    from routes.stream import stream_bp
    from routes.auth import auth_bp

    app.register_blueprint(manifest_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(meta_bp)
    app.register_blueprint(stream_bp)
    app.register_blueprint(auth_bp)

    # ── Health Checks ──
    @app.route("/health")
    def health_check() -> tuple[str, int, dict[str, str]]:
        """Minimal health check for Railway/Docker."""
        return '{"status":"ok"}', 200, {"Content-Type": "application/json"}

    @app.route("/ready")
    def ready_check() -> tuple[Any, int]:
        """Readiness check with details."""
        from services.cache import get_cache_stats

        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.2",
            "caches": get_cache_stats(),
        }), 200

    # ── Error Handlers ──
    @app.errorhandler(404)
    def page_not_found(e: Exception) -> tuple[str, int]:
        return render_template("404.html"), 404

    @app.errorhandler(TimeoutException)
    def handle_timeout(e: Exception) -> tuple[Any, int]:
        logger.error("Timeout exception: %s", e)
        cleanup_memory()
        return jsonify({
            "error": "The operation timed out. Please try again.",
        }), 504

    @app.errorhandler(MemoryError)
    def handle_memory_error(e: Exception) -> tuple[Any, int]:
        logger.critical("Memory error: %s", e)
        cleanup_memory()
        return jsonify({
            "error": "Memory error. Please try again in a few seconds.",
        }), 503

    @app.errorhandler(500)
    def handle_internal_error(e: Exception) -> tuple[Any, int]:
        logger.error("Internal server error: %s", e)
        cleanup_memory()
        return jsonify({
            "error": "Internal server error. Please try again.",
        }), 500

    # ── Middleware ──
    @app.after_request
    def after_request_cleanup(response: Any) -> Any:
        """Periodic cleanup of expired cache entries."""
        try:
            cleanup_all_caches()
        except Exception:
            pass
        return response

    logger.info("Xtremio app created successfully (v1.0.2)")
    return app


# Global instance for Gunicorn and WSGI runners
app = create_app()


if __name__ == "__main__":
    logger.info("Starting Xtremio API Server")
    cleanup_memory()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    debug = not IS_PRODUCTION

    logger.info("Server starting on %s:%d (debug=%s)", host, port, debug)
    app.run(host=host, port=port, debug=debug)
