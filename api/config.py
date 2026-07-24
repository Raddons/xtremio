"""
Xtremio Configuration Module
=============================
Centralizes all constants, configuration options, and environment variables.
"""
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Optional


# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("xtremio")


# =============================================================================
# SECURITY — Environment Variables
# =============================================================================

def _require_env(key: str, default: Optional[str] = None, secret: bool = False) -> str:
    """
    Obtains an environment variable. Accepts insecure defaults with a warning in development.
    """
    value = os.environ.get(key, default)
    if not value:
        raise RuntimeError(
            f"Environment variable '{key}' is required. "
            f"Configure it before starting the server."
        )
    if value == default and secret:
        logger.warning(
            "⚠️  '%s' is using an insecure default value. Configure it via environment variables in production!",
            key,
        )
    return value


# Flask
SECRET_KEY: str = _require_env(
    "SECRET_KEY", "dev-secret-key-placeholder", secret=True
)
FLASK_ENV: str = os.environ.get("FLASK_ENV", "development")
IS_PRODUCTION: bool = FLASK_ENV == "production"

# Cryptography
FERNET_KEY: bytes = _require_env(
    "FERNET_KEY", "bm90X2FfZ29vZF9rZXlfY2hhbmdlX21lX3BsZWFzZV8=", secret=True
).encode()

# TMDB
TMDB_API_KEY: str = _require_env(
    "TMDB_API_KEY", "YOUR_TMDB_API_KEY_HERE", secret=True
)


# =============================================================================
# TIMEOUTS (seconds)
# =============================================================================

DEFAULT_TIMEOUT: int = int(os.environ.get("DEFAULT_TIMEOUT", "10"))
MAX_REQUEST_TIMEOUT: int = int(os.environ.get("MAX_REQUEST_TIMEOUT", "30"))
RAILWAY_TIMEOUT: int = 25
XTREAM_FAST_TIMEOUT: int = 5


# =============================================================================
# HTTP CONNECTION LIMITS
# =============================================================================

HTTP_MAX_KEEPALIVE: int = int(os.environ.get("HTTP_MAX_KEEPALIVE", "20"))
HTTP_MAX_CONNECTIONS: int = int(os.environ.get("HTTP_MAX_CONNECTIONS", "50"))


# =============================================================================
# CACHE
# =============================================================================

CACHE_TTL_CATEGORIES: int = 3600    # 1 hour
CACHE_TTL_CATALOG: int = 900        # 15 minutes
CACHE_TTL_EPG: int = 300            # 5 minutes
CACHE_TTL_META: int = 1800          # 30 minutes
CACHE_TTL_AUTH: int = 60            # 1 minute
CACHE_TTL_MATCH: int = 3600         # 1 hour — IMDb→TMDB and TMDB→streamId matches

CACHE_MAX_SIZE_CATEGORIES: int = 64
CACHE_MAX_SIZE_CATALOG: int = 256
CACHE_MAX_SIZE_EPG: int = 128
CACHE_MAX_SIZE_META: int = 256
CACHE_MAX_SIZE_MATCH: int = 512


# =============================================================================
# PAGINATION
# =============================================================================

DEFAULT_CATALOG_LIMIT: int = 50
MAX_CATALOG_LIMIT: int = 200
MAX_STREAMS_LIMIT: int = 5


# =============================================================================
# COMPILED REGEX PATTERNS
# =============================================================================

QUALITY_SUFFIX_PATTERN = re.compile(r"\b(SD|FHD|HD|4K|H265|Alt)\b", re.IGNORECASE)
NON_ALPHANUMERIC_PATTERN = re.compile(r"[^a-z0-9\s]")
MULTIPLE_SPACES_PATTERN = re.compile(r"\s+")
SEASON_EPISODE_PATTERN = re.compile(r"S0?(\d+)E0?(\d+)(?!\d)", re.IGNORECASE)


# =============================================================================
# MAPPINGS
# =============================================================================

CONTENT_TYPE_MAP: dict[str, str] = {
    "movie": "vod",
    "series": "series",
    "tv": "live",
}

TIMEZONE_LANGUAGE_MAP: dict[str, str] = {
    "America/Sao_Paulo": "pt-BR",
    "Europe/Lisbon": "pt-PT",
    "America/New_York": "en-US",
    "Europe/Berlin": "de-DE",
    "Asia/Tokyo": "ja-JP",
    "Australia/Sydney": "en-AU",
    "America/Mexico_City": "es-MX",
    "Europe/Madrid": "es-ES",
    "Europe/Paris": "fr-FR",
    "Asia/Shanghai": "zh-CN",
    "Asia/Seoul": "ko-KR",
    "Africa/Johannesburg": "en-ZA",
    "Europe/Moscow": "ru-RU",
    "Asia/Dubai": "ar-AE",
    "America/Argentina/Buenos_Aires": "es-AR",
}

ACCOUNT_STATUS_MAP: dict[str, str] = {
    "Active": "✅ Active",
    "Banned": "🚫 Banned",
    "Disabled": "⛔ Disabled",
    "Expired": "⏰ Expired",
}


# =============================================================================
# DEFAULT HEADERS
# =============================================================================

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json",
}


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class ServerConfig:
    """Configuration for an Xtream server."""

    base_url: str
    username: str
    password: str
    lang: str = "en-US"
    encrypted: bool = False
    name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerConfig":
        """Creates ServerConfig from a dictionary."""
        return cls(
            base_url=data.get("BaseURL", ""),
            username=data.get("username", ""),
            password=data.get("password", ""),
            lang=data.get("lang", "en-US"),
            encrypted=data.get("encrypted", False),
            name=data.get("name"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Converts to dictionary."""
        return {
            "BaseURL": self.base_url,
            "username": self.username,
            "password": self.password,
            "lang": self.lang,
            "encrypted": self.encrypted,
            "name": self.name,
        }


@dataclass
class XtreamUserInfo:
    """Xtream user information extracted from authentication."""

    username: str = ""
    status: str = ""
    exp_date: Optional[int] = None
    created_at: Optional[int] = None
    is_trial: bool = False
    max_connections: int = 1
    auth: int = 0
    active_connections: int = 0
    allowed_output_formats: list[str] = field(default_factory=list)

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "XtreamUserInfo":
        """Creates instance from Xtream API response."""
        user_info = data.get("user_info", {})
        if not isinstance(user_info, dict):
            return cls()
        return cls(
            username=user_info.get("username", ""),
            status=user_info.get("status", ""),
            exp_date=user_info.get("exp_date"),
            created_at=user_info.get("created_at"),
            is_trial=user_info.get("is_trial", "0") == "1",
            max_connections=int(user_info.get("max_connections", 1)),
            auth=user_info.get("auth", 0),
            active_connections=int(user_info.get("active_cons", 0)),
            allowed_output_formats=user_info.get("allowed_output_formats", []),
        )

    @property
    def is_authenticated(self) -> bool:
        return self.auth != 0

    @property
    def is_active(self) -> bool:
        return self.status == "Active"

    @property
    def status_display(self) -> str:
        return ACCOUNT_STATUS_MAP.get(self.status, f"❓ {self.status}")


@dataclass
class XtreamServerInfo:
    """Xtream server information extracted from authentication."""

    url: str = ""
    port: int = 0
    https_port: int = 0
    server_protocol: str = "http"
    rtmp_port: int = 0
    timezone: str = ""
    timestamp_now: int = 0
    time_now: str = ""

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "XtreamServerInfo":
        """Creates instance from Xtream API response."""
        server_info = data.get("server_info", {})
        if not isinstance(server_info, dict):
            return cls()
        return cls(
            url=server_info.get("url", ""),
            port=int(server_info.get("port", 0)),
            https_port=int(server_info.get("https_port", 0)),
            server_protocol=server_info.get("server_protocol", "http"),
            rtmp_port=int(server_info.get("rtmp_port", 0)),
            timezone=server_info.get("timezone", ""),
            timestamp_now=int(server_info.get("timestamp_now", 0)),
            time_now=server_info.get("time_now", ""),
        )


# =============================================================================
# EXCEPTIONS
# =============================================================================

class XtremioError(Exception):
    """Base exception for Xtremio."""


class TimeoutException(XtremioError):
    """Exception raised for operation timeouts."""


class InvalidHashError(XtremioError):
    """Exception raised for an invalid hash."""


class AuthenticationError(XtremioError):
    """Exception raised for authentication errors."""


class AccountExpiredError(AuthenticationError):
    """Account expired."""


class AccountBannedError(AuthenticationError):
    """Account banned."""


class ServerUnavailableError(XtremioError):
    """Xtream server unavailable."""
