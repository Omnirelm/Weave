"""
Shared auth helper: build headers and optional OAuth from API auth dict.
Used by log and trace extractor factories to avoid duplicating auth branches.
"""
import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..logs.base import OAuthConfig, OAuthTokenManager


@dataclass
class AuthResult:
    """Result of parsing auth dict: headers to pass to extractors, optional OAuth."""

    headers: Dict[str, str]
    oauth_config: Optional[OAuthConfig] = None
    oauth_token_manager: Optional[OAuthTokenManager] = None


def build_headers_and_oauth_from_auth_dict(
    auth: Optional[Dict[str, Any]],
) -> AuthResult:
    """
    Build headers and optional OAuth from API auth mechanism dict.

    Args:
        auth: Dict with keys such as apiKey, bearer, basic, oauth (alias or snake_case).
              Same shape as API AuthMechanism.model_dump(by_alias=True).
              None or empty -> no auth.

    Returns:
        AuthResult with headers (API key + Authorization when bearer/basic),
        and optional oauth_config/oauth_token_manager when oauth is present.
    """
    if not auth or not isinstance(auth, dict):
        return AuthResult(headers={})

    headers: Dict[str, str] = {}

    # API key (can be combined with others)
    api_key = auth.get("apiKey") or auth.get("api_key")
    if isinstance(api_key, dict):
        key = api_key.get("apiKey") or api_key.get("api_key")
        if key:
            header_name = api_key.get("apiKeyHeaderName") or api_key.get("api_key_header_name") or "X-API-Key"
            headers[header_name] = key

    # OAuth: return config and token manager for extractors that support from_oauth
    oauth_block = auth.get("oauth")
    if isinstance(oauth_block, dict):
        oauth_cfg = oauth_block.get("oauthConfig") or oauth_block.get("oauth_config")
        if isinstance(oauth_cfg, dict):
            oauth_config = OAuthConfig.model_validate(oauth_cfg)
            # Merge extra_headers into headers dict for requests to the log source
            extra = oauth_cfg.get("extra_headers") or oauth_cfg.get("extraHeaders") or {}
            if isinstance(extra, dict):
                headers.update(extra)
            return AuthResult(
                headers=headers,
                oauth_config=oauth_config,
                oauth_token_manager=OAuthTokenManager(oauth_config),
            )

    # Bearer
    bearer = auth.get("bearer")
    if isinstance(bearer, dict) and bearer.get("token"):
        headers["Authorization"] = f"Bearer {bearer['token']}"
        return AuthResult(headers=headers)

    # Basic
    basic = auth.get("basic")
    if isinstance(basic, dict) and basic.get("username") and basic.get("password"):
        creds = base64.b64encode(
            f"{basic['username']}:{basic['password']}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {creds}"
        return AuthResult(headers=headers)

    return AuthResult(headers=headers)
