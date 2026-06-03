"""
Generic HTTP request tool for workflows and agents.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from google.adk.tools import FunctionTool

from src.core.tools.base import BaseTool


class HttpTool(BaseTool):
    """Perform an outbound HTTP request (sync)."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return "Perform an HTTP request and return status, headers, and response body text."

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        url = kwargs.get("url")
        if not url:
            raise TypeError("http_request requires url")
        method = str(kwargs.get("method", "GET")).upper()
        headers = kwargs.get("headers")
        body = kwargs.get("body")
        follow_redirects = bool(kwargs.get("follow_redirects", True))

        with httpx.Client(timeout=self._timeout) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                content=body.encode("utf-8") if isinstance(body, str) else body,
                follow_redirects=follow_redirects,
            )
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "text": response.text,
        }

    def as_function_tool(self) -> FunctionTool:
        timeout = self._timeout

        def http_request(
            url: str,
            method: str = "GET",
            headers: Optional[Dict[str, str]] = None,
            body: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Perform an HTTP request and return status, headers, and response body text.

            Args:
                url: Request URL
                method: HTTP method (default GET)
                headers: Optional request headers
                body: Optional string body
            """
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    content=body.encode("utf-8") if body is not None else None,
                )
            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "text": response.text,
            }

        return FunctionTool(func=http_request)
