"""
Base classes for log extraction integrations.
"""
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)


class LogEntry(BaseModel):
    """
    Standardized log entry type used by all extractors.
    
    All extractors return log entries conforming to this structure.
    """
    timestamp: Optional[str] = Field(None, description="ISO format timestamp string (UTC)")
    message: str = Field(..., description="Log message content")
    level: Optional[str] = Field(None, description="Log level (INFO, ERROR, WARN, DEBUG, etc.)")
    labels: Dict[str, Any] = Field(default_factory=dict, description="Labels/metadata (source, filename, etc.)")
    traceId: Optional[str] = Field(None, description="Distributed trace ID")
    spanId: Optional[str] = Field(None, description="Span ID within trace")
    
    model_config = ConfigDict(
        # Allow extra fields for backward compatibility
        extra="allow",
        # Use enum values instead of enum names
        use_enum_values=True
    )


class DedupedLogEntry(BaseModel):
    """One row per unique template: representative log (normalized message), count of log lines, and traces."""

    log_entry: LogEntry = Field(..., description="Representative log (first occurrence) with message set to the normalized template")
    count: int = Field(..., description="Number of log lines that matched this template")
    traces: Set[str] = Field(..., description="Trace IDs associated with this template")


class DedupedLogsResult(BaseModel):
    """Result of de-duplicating logs by template: list of per-template entries."""

    entries: List[DedupedLogEntry] = Field(..., description="One entry per unique template (log_entry with normalized message, count, traces)")


class LogExtractorError(Exception): 
    """Base exception for log extractor errors"""
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class QueryGenerationError(LogExtractorError):
    """Exception raised when query generation fails (agent/LLM errors)"""
    pass


class LogDedupeError(LogExtractorError):
    """Exception raised when log deduplication fails (e.g. template miner not set)"""
    pass


class OAuthConfig(BaseModel):
    """
    Configuration for OAuth 2.0 Client Credentials flow.
    
    Attributes:
        client_id: OAuth client identifier
        client_secret: OAuth client secret
        token_url: OAuth token endpoint URL
        scope: Optional OAuth scopes (comma-separated string)
        token_expiry_buffer: Seconds before expiry to refresh token (default: 60)
        extra_headers: Additional headers to include with every request
    """
    client_id: str = Field(None, alias="clientId", description="OAuth client identifier")
    client_secret: str = Field(None, alias="clientSecret", description="OAuth client secret")
    token_url: str = Field(None, alias="tokenUrl", description="OAuth token endpoint URL")
    scope: Optional[str] = Field(None, alias="scope", description="Optional OAuth scopes (comma-separated string)")
    token_expiry_buffer: int = Field(60, alias="tokenExpiryBuffer", description="Seconds before expiry to refresh token")
    extra_headers: Optional[Dict[str, str]] = Field(None, alias="extraHeaders", description="Additional headers to include with every request")
    
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class OAuthTokenManager:
    """
    Thread-safe OAuth token manager for Client Credentials flow.
    
    Handles token acquisition, caching, and automatic refresh.
    Can be used by any log extractor that needs OAuth authentication.
    """
    
    def __init__(self, config: OAuthConfig):
        """
        Initialize OAuth token manager.
        
        Args:
            config: OAuth configuration
        """
        self.config = config
        self._token: Optional[str] = None
        self._token_expires_at: Optional[float] = None
        self._lock = threading.Lock()
    
    def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.
        
        Returns:
            Valid access token string
            
        Raises:
            LogExtractorError: If token acquisition fails
        """
        with self._lock:
            if self._is_token_valid():
                return self._token
            
            # Token expired or missing, acquire new one
            logger.debug("OAuth token expired or missing, acquiring new token")
            token_data = self._acquire_token()
            
            self._token = token_data.get('access_token')
            if not self._token:
                raise LogExtractorError("OAuth token response missing access_token")
            
            # Calculate expiry time
            expires_in = token_data.get('expires_in', 3600)  # Default to 1 hour
            self._token_expires_at = time.time() + expires_in - self.config.token_expiry_buffer
            
            logger.debug(f"OAuth token acquired, expires in {expires_in} seconds")
            return self._token
    
    def _is_token_valid(self) -> bool:
        """
        Check if current token is valid and not expired.
        
        Returns:
            True if token is valid, False otherwise
        """
        if not self._token or not self._token_expires_at:
            return False
        
        return time.time() < self._token_expires_at
    
    def _acquire_token(self) -> Dict[str, Any]:
        """
        Acquire a new OAuth token using Client Credentials flow.
        
        Returns:
            Token response dictionary with access_token and expires_in
            
        Raises:
            LogExtractorError: If token acquisition fails
        """
        # Prepare token request
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.config.client_id,
            'client_secret': self.config.client_secret,
        }
        
        if self.config.scope:
            data['scope'] = self.config.scope
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        # Merge extra_headers if provided
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        
        try:
            response = requests.post(
                self.config.token_url,
                data=data,
                headers=headers,
                timeout=30.0
            )
            
            if not response.ok:
                raise LogExtractorError(
                    f"OAuth token request failed: HTTP {response.status_code}: {response.reason}",
                    status_code=response.status_code,
                    response_text=response.text
                )
            
            token_data = response.json()
            
            if 'error' in token_data:
                error_description = token_data.get('error_description', token_data.get('error', 'Unknown error'))
                raise LogExtractorError(f"OAuth token request failed: {error_description}")
            
            return token_data
            
        except requests.exceptions.RequestException as e:
            raise LogExtractorError(f"OAuth token request failed: {str(e)}") from e

class LogExtractor(ABC):
    """Abstract base class for log exporters"""
    
    def __init__(self, base_url: str, headers: Optional[Dict[str, str]] = None,
                 oauth_token_manager: Optional[OAuthTokenManager] = None):
        """
        Initialize the log extractor.
        
        Args:
            base_url: Base URL for the log service API (or dummy URL for non-HTTP extractors)
            headers: Optional default headers for HTTP requests
            oauth_token_manager: Optional OAuth token manager for OAuth authentication
        """
        self.base_url = base_url.rstrip('/')
        self.headers = headers or {}
        self._oauth_token_manager = oauth_token_manager
    
    @abstractmethod
    def get_log_aggregator_name(self) -> str:
        """
       Get the name of the log aggregator service.
       
       Returns:
           Name of the log aggregator (e.g., 'LOKI', 'OPENSEARCH', 'LOCAL_FILE')
       """
        pass
    
    @abstractmethod
    def get_query_language(self) -> str:
        """
        Get the query language used by this extractor.
        
        Returns:
            Query language name (e.g., 'LogQL', 'PPL', 'REGEX')
        """
        pass

    @abstractmethod
    def get_index_name(self) -> str:
        """
        Get the index name from the log extractor.
        """
        pass
    
    @abstractmethod
    def fetch_logs(self, query: str, **kwargs) -> List[LogEntry]:
        """
        Fetch logs based on a query.
        
        Args:
            query: Query string to filter logs
            **kwargs: Additional parameters specific to the implementation
            
        Returns:
            List of standardized log entries (LogEntry)
            
        Raises:
            LogExtractorError: If fetching logs fails
        """
        pass
    
    @abstractmethod
    def get_label_names(self) -> List[str]:
        """
        Get the label names from the log extractor.
        """
        pass
    
    @abstractmethod
    def get_field_names(self) -> List[str]:
        """
        Get the field names from the log extractor.
        """
        pass

    def precheck(self) -> bool:
        """
        Verify the extractor can provide schema (labels or index/fields) needed for query generation.
        Override in Loki and OpenSearch; unsupported extractors hit this default.

        Returns:
            True if labels or index/fields are available.

        Raises:
            QueryGenerationError: If precheck is not implemented for this aggregator, or if
                no labels (Loki) or no index/field names (OpenSearch) are found.
        """
        raise QueryGenerationError(
            f"precheck not implemented for {self.get_log_aggregator_name()}"
        )

    def validate_connection(self, timeout: float = 10.0) -> None:
        """
        Perform a minimal connectivity check (URL + auth). Override in Loki and OpenSearch.
        Raises LogExtractorError if the connection or credentials are invalid.
        """
        raise LogExtractorError(
            f"validate_connection not implemented for {self.get_log_aggregator_name()}"
        )

    def _make_request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None, 
                     headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = 30.0, **kwargs: Any) -> requests.Response:
        """
        Make HTTP request with error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            params: Query parameters
            headers: Request headers
            timeout: Request timeout in seconds (default: 30.0)
            **kwargs: Additional requests parameters
            
        Returns:
            requests.Response object
            
        Raises:
            LogExtractorError: If request fails
        """
        # Validate method
        if not method or not isinstance(method, str):
            raise LogExtractorError(f"Invalid HTTP method: {method}")
        method = method.upper().strip()
        valid_methods = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'}
        if method not in valid_methods:
            raise LogExtractorError(f"Invalid HTTP method: {method}. Must be one of {valid_methods}")
        
        # Validate URL
        if not url or not isinstance(url, str):
            raise LogExtractorError(f"Invalid URL: {url}")
        url = url.strip()
        if not url:
            raise LogExtractorError("URL cannot be empty")
        
        # Validate URL format
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                raise LogExtractorError(f"Invalid URL format: {url}")
        except Exception as e:
            raise LogExtractorError(f"Invalid URL format: {url} - {str(e)}")
        
        # If OAuth token manager is present, get access token and inject it
        if self._oauth_token_manager:
            try:
                access_token = self._oauth_token_manager.get_access_token()
                # Merge OAuth token into headers (OAuth takes precedence)
                oauth_headers = {'Authorization': f'Bearer {access_token}'}
                if headers:
                    headers = {**oauth_headers, **headers}
                else:
                    headers = oauth_headers
            except Exception as e:
                raise LogExtractorError(f"Failed to get OAuth access token: {str(e)}") from e
        
        request_headers = {**self.headers, **(headers or {})}
        
        # Ensure timeout is set (use default if not provided in kwargs)
        if 'timeout' not in kwargs:
            kwargs['timeout'] = timeout
        
        try:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                headers=request_headers,
                **kwargs
            )
            
            if not response.ok:
                # Include response body in error (may be JSON string or plain text)
                error_message = f"HTTP {response.status_code}: {response.reason} - {response.text}"
                response_text = response.text
                
                raise LogExtractorError(
                    error_message,
                    status_code=response.status_code,
                    response_text=response_text
                )
            
            return response
            
        except requests.exceptions.Timeout as e:
            raise LogExtractorError(f"Request timeout after {kwargs.get('timeout', timeout)}s: {str(e)}") from e
        except requests.exceptions.RequestException as e:
            raise LogExtractorError(f"Request failed: {str(e)}") from e


    def _clean_query_string(self, query: str) -> str:
        """
        Clean the query string by removing markdown code blocks, newlines, and extra whitespace.
        
        Args:
            query: Raw query string that may contain markdown formatting
            
        Returns:
            Cleaned query string ready for API calls
        """
        if not query:
            return ""
        
        # Remove markdown code blocks (``` at start/end)
        query = re.sub(r'^```[\w]*\n?', '', query, flags=re.MULTILINE)
        query = re.sub(r'\n?```$', '', query, flags=re.MULTILINE)
        
        # Remove all newline characters and replace with spaces
        query = query.replace('\n', ' ')
        
        # Remove extra whitespace (multiple spaces, tabs, etc.)
        query = re.sub(r'\s+', ' ', query)
        
        # Strip leading/trailing whitespace
        query = query.strip()
        
        return query