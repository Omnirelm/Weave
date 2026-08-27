"""OAuth and authentication handling for MCP servers."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default expiry buffer: refresh token 60 seconds before expiry
DEFAULT_EXPIRY_BUFFER = 60


@dataclass
class CachedToken:
    """Cached OAuth access token with expiry."""

    access_token: str
    expires_at: float  # Unix timestamp


@dataclass
class McpAuthHandler:
    """Handles authentication for MCP servers, including OAuth token management.

    Supports:
    - Basic authentication (username/password)
    - Bearer token (static)
    - OAuth 2.0 Client Credentials flow (with token caching and refresh)
    - API Key authentication

    Token cache is in-memory and scoped to this handler instance.
    """

    _token_cache: dict[str, CachedToken] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_auth_headers(
        self, auth_mechanism: dict[str, Any] | None
    ) -> dict[str, str]:
        """Generate authentication headers based on the auth mechanism.

        Args:
            auth_mechanism: Auth config dict with one of: basic, bearer, oauth, api_key

        Returns:
            Headers dict to merge with request headers
        """
        if not auth_mechanism:
            return {}

        if auth_mechanism.get("basic"):
            return self._get_basic_headers(auth_mechanism["basic"])

        if auth_mechanism.get("bearer"):
            return self._get_bearer_headers(auth_mechanism["bearer"])

        if auth_mechanism.get("oauth"):
            return await self._get_oauth_headers(auth_mechanism["oauth"])

        if auth_mechanism.get("api_key"):
            return self._get_api_key_headers(auth_mechanism["api_key"])

        return {}

    def _get_basic_headers(self, basic: dict[str, Any]) -> dict[str, str]:
        """Generate Basic auth header."""
        username = basic.get("username", "")
        password = basic.get("password", "")
        credentials = f"{username}:{password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def _get_bearer_headers(self, bearer: dict[str, Any]) -> dict[str, str]:
        """Generate Bearer token header."""
        token = bearer.get("token", "")
        return {"Authorization": f"Bearer {token}"}

    def _get_api_key_headers(self, api_key: dict[str, Any]) -> dict[str, str]:
        """Generate API key header."""
        key = api_key.get("api_key", "")
        header_name = api_key.get("api_key_header_name", "X-API-Key")
        return {header_name: key}

    async def _get_oauth_headers(self, oauth: dict[str, Any]) -> dict[str, str]:
        """Get OAuth Bearer header, fetching/refreshing token as needed."""
        oauth_config = oauth.get("oauth_config", {})
        token_url = oauth_config.get("token_url", "")

        if not token_url:
            logger.warning("OAuth configured but token_url is missing")
            return {}

        # Create cache key from token URL + client_id
        client_id = oauth_config.get("client_id", "")
        cache_key = f"{token_url}:{client_id}"

        # Check cached token
        async with self._lock:
            cached = self._token_cache.get(cache_key)
            expiry_buffer = oauth_config.get("token_expiry_buffer", DEFAULT_EXPIRY_BUFFER)

            if cached and time.time() < (cached.expires_at - expiry_buffer):
                return {"Authorization": f"Bearer {cached.access_token}"}

            # Fetch new token
            try:
                token_data = await self._fetch_oauth_token(oauth_config)
                access_token = token_data.get("access_token", "")
                expires_in = token_data.get("expires_in", 3600)  # Default 1 hour

                if access_token:
                    self._token_cache[cache_key] = CachedToken(
                        access_token=access_token,
                        expires_at=time.time() + expires_in,
                    )
                    return {"Authorization": f"Bearer {access_token}"}
                else:
                    logger.error("OAuth token response missing access_token")
                    return {}

            except Exception:
                logger.exception("Failed to fetch OAuth token from %s", token_url)
                return {}

    async def _fetch_oauth_token(self, oauth_config: dict[str, Any]) -> dict[str, Any]:
        """Fetch OAuth token using Client Credentials flow."""
        token_url = oauth_config.get("token_url", "")
        client_id = oauth_config.get("client_id", "")
        client_secret = oauth_config.get("client_secret", "")
        scope = oauth_config.get("scope", "")
        extra_headers = oauth_config.get("extra_headers") or {}

        # Build token request
        data = {
            "grant_type": "client_credentials",
        }
        if client_id:
            data["client_id"] = client_id
        if client_secret:
            data["client_secret"] = client_secret
        if scope:
            data["scope"] = scope

        # Build headers, merging extra_headers
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if isinstance(extra_headers, dict):
            headers.update(extra_headers)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                token_url,
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()


# Global auth handler instance (singleton pattern for token cache sharing)
_auth_handler: McpAuthHandler | None = None


def get_auth_handler() -> McpAuthHandler:
    """Get or create the global auth handler instance."""
    global _auth_handler
    if _auth_handler is None:
        _auth_handler = McpAuthHandler()
    return _auth_handler
