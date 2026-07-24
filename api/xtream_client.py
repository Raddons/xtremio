"""
Xtream Codes API Client
========================
Full client for Xtream Codes API supporting:
- Authentication & server details
- VOD (Movies), Series & Live TV
- EPG (Electronic Program Guide)
- Stream URL generation
- Intelligent caching with TTL
- Credential proxying (prevents exposing username/password in URLs)
"""
from __future__ import annotations

import re
from json import dumps
from typing import Any, Optional

from httpx import Client, Limits, RequestError

from config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    HTTP_MAX_CONNECTIONS,
    HTTP_MAX_KEEPALIVE,
    MAX_REQUEST_TIMEOUT,
    SEASON_EPISODE_PATTERN,
    ServerConfig,
    XtreamServerInfo,
    XtreamUserInfo,
    AuthenticationError,
    AccountExpiredError,
    AccountBannedError,
    ServerUnavailableError,
    logger,
)
from services.cache import (
    catalog_cache,
    category_cache,
    epg_cache,
    meta_cache,
)
from utils import convert_to_url, extract_xtr_from_url, normalize_string


# =============================================================================
# GLOBAL HTTP CONNECTION POOL
# =============================================================================

_http_pool = Client(
    follow_redirects=True,
    timeout=DEFAULT_TIMEOUT,
    limits=Limits(
        max_keepalive_connections=HTTP_MAX_KEEPALIVE,
        max_connections=HTTP_MAX_CONNECTIONS,
    ),
    headers=DEFAULT_HEADERS,
)


def get_http_pool() -> Client:
    """Returns global HTTP client pool."""
    return _http_pool


def http_get(
    url: str,
    params: Optional[dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[dict[str, Any]]:
    """
    Generic GET request helper with error handling.

    Args:
        url: Destination URL.
        params: Request parameters.
        timeout: Timeout in seconds.

    Returns:
        JSON response object or None on failure.
    """
    effective_timeout = min(timeout, MAX_REQUEST_TIMEOUT)
    try:
        response = _http_pool.get(
            url,
            params=params,
            timeout=effective_timeout,
        )
        response.raise_for_status()
        return response.json()
    except RequestError as e:
        logger.error("Request error for %s: %s", url, e)
    except ValueError as e:
        logger.error("JSON parse error for %s: %s", url, e)
    except Exception as e:
        logger.exception("Unexpected error requesting %s: %s", url, e)
    return None


# =============================================================================
# XTREAM CLIENT
# =============================================================================


class XtreamClient:
    """
    Client for Xtream Codes API supporting all core actions.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        lang: str = "en-US",
    ):
        self.base_url = convert_to_url(base_url)
        self.username = username
        self.password = password
        self.lang = lang
        self.xtr = extract_xtr_from_url(self.base_url)

        self._user_info: Optional[XtreamUserInfo] = None
        self._server_info: Optional[XtreamServerInfo] = None
        self._raw_auth: Optional[dict[str, Any]] = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "XtreamClient":
        """Creates XtreamClient instance from a configuration dictionary."""
        return cls(
            base_url=config.get("BaseURL", ""),
            username=config.get("username", ""),
            password=config.get("password", ""),
            lang=config.get("lang", "en-US"),
        )

    @classmethod
    def from_server_config(cls, config: ServerConfig) -> "XtreamClient":
        """Creates XtreamClient instance from a ServerConfig dataclass."""
        return cls(
            base_url=config.base_url,
            username=config.username,
            password=config.password,
            lang=config.lang,
        )

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def _base_params(self) -> dict[str, str]:
        """Base query parameters for all requests."""
        return {"username": self.username, "password": self.password}

    @property
    def user_info(self) -> Optional[XtreamUserInfo]:
        """User details (populated after authenticate())."""
        return self._user_info

    @property
    def server_info(self) -> Optional[XtreamServerInfo]:
        """Server details (populated after authenticate())."""
        return self._server_info

    @property
    def is_authenticated(self) -> bool:
        """Returns True if client successfully authenticated."""
        return self._user_info is not None and self._user_info.is_authenticated

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    def authenticate(self) -> bool:
        """
        Authenticates against the Xtream server and populates user/server details.

        Returns:
            True if authenticated successfully.

        Raises:
            AccountExpiredError: If account is expired.
            AccountBannedError: If account is banned.
            ServerUnavailableError: If server does not respond.
        """
        response = http_get(
            f"{self.base_url}/player_api.php",
            params=self._base_params,
        )

        if response is None:
            raise ServerUnavailableError(
                f"Server {self.base_url} did not respond"
            )

        self._raw_auth = response
        self._user_info = XtreamUserInfo.from_api_response(response)
        self._server_info = XtreamServerInfo.from_api_response(response)

        if not self._user_info.is_authenticated:
            raise AuthenticationError("Invalid credentials")

        status = self._user_info.status
        if status == "Expired":
            raise AccountExpiredError(f"Account expired for {self.username}")
        if status == "Banned":
            raise AccountBannedError(f"Account banned for {self.username}")

        logger.info(
            "Authenticated: user=%s, status=%s, server_tz=%s",
            self.username,
            self._user_info.status_display,
            self._server_info.timezone if self._server_info else "N/A",
        )
        return True

    def validate_auth_response(self, info: Optional[dict[str, Any]]) -> bool:
        """Validates auth response object."""
        if not info or not isinstance(info, dict):
            return False
        user_info = info.get("user_info", {})
        if not isinstance(user_info, dict):
            return False
        return user_info.get("auth") != 0

    # =========================================================================
    # INTERNAL API REQUESTS
    # =========================================================================

    def _api_request(
        self,
        action: str,
        extra_params: Optional[dict[str, str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Optional[Any]:
        """Generic Xtream API request helper."""
        params = {**self._base_params, "action": action}
        if extra_params:
            params.update(extra_params)

        return http_get(
            f"{self.base_url}/player_api.php",
            params=params,
            timeout=timeout,
        )

    def _cached_api_request(
        self,
        action: str,
        cache: Any,
        extra_params: Optional[dict[str, str]] = None,
        cache_key_suffix: str = "",
    ) -> Optional[Any]:
        """API request with automatic TTL caching."""
        key_parts = [self.base_url, self.username, action]
        if extra_params:
            key_parts.append(dumps(extra_params, sort_keys=True))
        if cache_key_suffix:
            key_parts.append(cache_key_suffix)
        cache_key = ":".join(key_parts)

        return cache.get_or_fetch(
            cache_key,
            lambda: self._api_request(action, extra_params),
        )

    # =========================================================================
    # VOD (MOVIES)
    # =========================================================================

    def get_vod_categories(self) -> list[dict[str, Any]]:
        """Retrieves movie categories."""
        result = self._cached_api_request("get_vod_categories", category_cache)
        return result if isinstance(result, list) else []

    def get_vod_streams(
        self, category_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Retrieves movie stream list, optionally filtered by category."""
        extra = {"category_id": category_id} if category_id else None
        result = self._cached_api_request(
            "get_vod_streams",
            catalog_cache,
            extra_params=extra,
        )
        return result if isinstance(result, list) else []

    def get_vod_info(self, vod_id: str) -> Optional[dict[str, Any]]:
        """Retrieves detailed information for a movie."""
        return self._cached_api_request(
            "get_vod_info",
            meta_cache,
            extra_params={"vod_id": vod_id},
        )

    # =========================================================================
    # SERIES
    # =========================================================================

    def get_series_categories(self) -> list[dict[str, Any]]:
        """Retrieves series categories."""
        result = self._cached_api_request("get_series_categories", category_cache)
        return result if isinstance(result, list) else []

    def get_series(
        self, category_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Retrieves series list, optionally filtered by category."""
        extra = {"category_id": category_id} if category_id else None
        result = self._cached_api_request(
            "get_series",
            catalog_cache,
            extra_params=extra,
        )
        return result if isinstance(result, list) else []

    def get_series_info(self, series_id: str) -> Optional[dict[str, Any]]:
        """Retrieves detailed series information including episodes."""
        return self._cached_api_request(
            "get_series_info",
            meta_cache,
            extra_params={"series_id": series_id},
        )

    # =========================================================================
    # LIVE TV
    # =========================================================================

    def get_live_categories(self) -> list[dict[str, Any]]:
        """Retrieves live TV categories."""
        result = self._cached_api_request("get_live_categories", category_cache)
        return result if isinstance(result, list) else []

    def get_live_streams(
        self, category_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Retrieves live TV streams, optionally filtered by category."""
        extra = {"category_id": category_id} if category_id else None
        result = self._cached_api_request(
            "get_live_streams",
            catalog_cache,
            extra_params=extra,
        )
        return result if isinstance(result, list) else []

    # =========================================================================
    # EPG (ELECTRONIC PROGRAM GUIDE)
    # =========================================================================

    def get_short_epg(
        self, stream_id: str, limit: int = 4
    ) -> list[dict[str, Any]]:
        """Retrieves short EPG listings for a live channel."""
        result = self._cached_api_request(
            "get_short_epg",
            epg_cache,
            extra_params={"stream_id": stream_id, "limit": str(limit)},
        )
        if not result or not isinstance(result, dict):
            return []

        epg_listings = result.get("epg_listings", [])
        return [
            {
                "title": prog.get("title", ""),
                "description": prog.get("description", ""),
                "start": prog.get("start", ""),
                "end": prog.get("end", ""),
                "start_timestamp": prog.get("start_timestamp", ""),
                "stop_timestamp": prog.get("stop_timestamp", ""),
                "channel_id": prog.get("channel_id", ""),
                "lang": prog.get("lang", ""),
            }
            for prog in epg_listings
        ]

    def get_full_epg(self, stream_id: str) -> list[dict[str, Any]]:
        """Retrieves full EPG listings for a channel."""
        result = self._cached_api_request(
            "get_simple_data_table",
            epg_cache,
            extra_params={"stream_id": stream_id},
        )
        if not result or not isinstance(result, dict):
            return []
        return result.get("epg_listings", [])

    # =========================================================================
    # STREAM URL GENERATION
    # =========================================================================

    def build_live_url(self, stream_id: str, ext: str = "m3u8") -> str:
        """Generates live stream URL."""
        return (
            f"{self.base_url}/live/"
            f"{self.username}/{self.password}/"
            f"{stream_id}.{ext}"
        )

    def build_movie_url(self, stream_id: str, ext: str = "mp4") -> str:
        """Generates movie stream URL."""
        return (
            f"{self.base_url}/movie/"
            f"{self.username}/{self.password}/"
            f"{stream_id}.{ext}"
        )

    def build_series_url(self, episode_id: str, ext: str = "mp4") -> str:
        """Generates series episode stream URL."""
        return (
            f"{self.base_url}/series/"
            f"{self.username}/{self.password}/"
            f"{episode_id}.{ext}"
        )

    def build_timeshift_url(
        self,
        stream_id: str,
        start: str,
        duration: int = 120,
    ) -> str:
        """Generates Catchup/Timeshift stream URL."""
        return (
            f"{self.base_url}/timeshift/"
            f"{self.username}/{self.password}/"
            f"{duration}/{start}/{stream_id}.ts"
        )

    # =========================================================================
    # SEARCH & MATCHING
    # =========================================================================

    def get_vod_category_map(self) -> dict[str, str]:
        """Returns {category_id: category_name} map for VOD categories."""
        return {
            str(cat["category_id"]): cat["category_name"]
            for cat in self.get_vod_categories()
        }

    def get_series_category_map(self) -> dict[str, str]:
        """Returns {category_id: category_name} map for series categories."""
        return {
            str(cat["category_id"]): cat["category_name"]
            for cat in self.get_series_categories()
        }

    def search_vod_by_name(self, name: str) -> list[dict[str, Any]]:
        """Searches movies by normalized name."""
        all_movies = self.get_vod_streams()
        normalized = normalize_string(name)
        return [
            item for item in all_movies
            if re.search(re.escape(normalized), normalize_string(item.get("name", "")))
        ]

    def search_series_by_name(self, name: str) -> list[dict[str, Any]]:
        """Searches series by normalized name."""
        all_series = self.get_series()
        normalized = normalize_string(name)
        return [
            item for item in all_series
            if re.search(re.escape(normalized), normalize_string(item.get("name", "")))
        ]

    def find_episode(
        self,
        series_id: str,
        season: str,
        episode: str,
    ) -> Optional[dict[str, Any]]:
        """Finds a specific episode in a series."""
        series_info = self.get_series_info(series_id)
        if not series_info or "episodes" not in series_info:
            return None

        episodes_by_season = series_info.get("episodes", {})
        if season not in episodes_by_season:
            return None

        season_episodes = episodes_by_season[season]
        ep_idx = int(episode) - 1

        if ep_idx < 0 or ep_idx >= len(season_episodes):
            return None

        pattern = re.compile(
            rf"S0?{int(season)}E0?{int(episode)}(?!\d)",
            re.IGNORECASE,
        )
        for ep in season_episodes:
            if pattern.search(ep.get("title", "")):
                return ep

        return season_episodes[ep_idx]

    # =========================================================================
    # M3U PLAYLIST GENERATION
    # =========================================================================

    def generate_m3u(
        self,
        include_live: bool = True,
        include_vod: bool = True,
        include_series: bool = False,
    ) -> str:
        """Generates an M3U playlist."""
        lines = ["#EXTM3U"]

        if include_live:
            categories = {
                cat["category_id"]: cat["category_name"]
                for cat in self.get_live_categories()
            }
            for channel in self.get_live_streams():
                cat_id = channel.get("category_id", "")
                group = categories.get(cat_id, "Uncategorized")
                name = channel.get("name", "Channel")
                logo = channel.get("stream_icon", "")
                stream_id = channel.get("stream_id", "")

                lines.append(
                    f'#EXTINF:-1 tvg-id="{stream_id}" '
                    f'tvg-name="{name}" '
                    f'tvg-logo="{logo}" '
                    f'group-title="{group}",{name}'
                )
                lines.append(self.build_live_url(str(stream_id)))

        if include_vod:
            categories = {
                cat["category_id"]: cat["category_name"]
                for cat in self.get_vod_categories()
            }
            for movie in self.get_vod_streams():
                cat_id = movie.get("category_id", "")
                group = categories.get(cat_id, "Uncategorized")
                name = movie.get("name", "Movie")
                logo = movie.get("stream_icon", "")
                stream_id = movie.get("stream_id", "")
                ext = movie.get("container_extension", "mp4")

                lines.append(
                    f'#EXTINF:-1 tvg-name="{name}" '
                    f'tvg-logo="{logo}" '
                    f'group-title="VOD - {group}",{name}'
                )
                lines.append(self.build_movie_url(str(stream_id), ext))

        if include_series:
            for serie in self.get_series():
                name = serie.get("name", "Series")
                logo = serie.get("cover", "")

                lines.append(
                    f'#EXTINF:-1 tvg-name="{name}" '
                    f'tvg-logo="{logo}" '
                    f'group-title="Series",{name}'
                )
                lines.append(f"# Series ID: {serie.get('series_id', '')}")

        lines.append("")
        return "\n".join(lines)

    # =========================================================================
    # SERVER HEALTH
    # =========================================================================

    def get_server_health(self) -> dict[str, Any]:
        """Checks Xtream server status and latency."""
        import time

        start = time.time()
        try:
            response = http_get(
                f"{self.base_url}/player_api.php",
                params=self._base_params,
            )
            latency_ms = round((time.time() - start) * 1000, 2)

            if response is None:
                return {
                    "status": "offline",
                    "latency_ms": latency_ms,
                    "error": "No response from server",
                }

            user_info = XtreamUserInfo.from_api_response(response)
            server_info = XtreamServerInfo.from_api_response(response)

            return {
                "status": "online" if user_info.is_authenticated else "auth_failed",
                "latency_ms": latency_ms,
                "user": {
                    "status": user_info.status_display,
                    "max_connections": user_info.max_connections,
                    "active_connections": user_info.active_connections,
                    "is_trial": user_info.is_trial,
                    "formats": user_info.allowed_output_formats,
                },
                "server": {
                    "timezone": server_info.timezone,
                    "protocol": server_info.server_protocol,
                    "time": server_info.time_now,
                },
            }
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 2)
            return {
                "status": "error",
                "latency_ms": latency_ms,
                "error": str(e),
            }
