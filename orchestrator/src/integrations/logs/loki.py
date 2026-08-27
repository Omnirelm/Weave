"""
Grafana Loki integration for log extraction and analysis.
"""
from datetime import datetime, timezone
import json
import logging
import base64
from typing import Dict, Any, List, Optional
from .base import LogExtractor, LogExtractorError, LogEntry, OAuthConfig, OAuthTokenManager, QueryGenerationError
from .parsers import detect_format, parse_json, parse_logfmt, extract_trace_id_span_id

logger = logging.getLogger(__name__)


class GrafanaLokiExtractor(LogExtractor):
    """Grafana Loki log exporter implementation"""
    
    def __init__(self, base_url: str, loki_org_id: Optional[str] = None, 
                 headers: Optional[Dict[str, str]] = None,
                 oauth_token_manager: Optional[OAuthTokenManager] = None):
        """
        Initialize Grafana Loki exporter.
        
        Args:
            base_url: Loki base URL (e.g., 'http://localhost:3100')
            loki_org_id: Optional Loki org ID for multi-tenancy
            headers: Optional headers dictionary (will be merged with tenant headers)
            oauth_token_manager: Optional OAuth token manager for OAuth authentication
        """
        # Set class attributes
        self.loki_org_id = loki_org_id
        
        # Start with provided headers or empty dict
        merged_headers = dict(headers) if headers else {}
        
        # Add tenant header if provided
        if loki_org_id:
            merged_headers['X-Scope-OrgID'] = loki_org_id
        
        # Pass oauth_token_manager to base class
        super().__init__(base_url, merged_headers, oauth_token_manager=oauth_token_manager)
    
    @classmethod
    def from_bearer_token(cls, base_url: str, token: str, loki_org_id: Optional[str] = None, 
                         headers: Optional[Dict[str, str]] = None) -> 'GrafanaLokiExtractor':
        """
        Create Grafana Loki extractor with Bearer token authentication.
        
        Args:
            base_url: Loki base URL (e.g., 'http://localhost:3100')
            token: Bearer token for authentication
            loki_org_id: Optional Loki org ID for multi-tenancy
            headers: Optional additional headers to merge with auth header
            
        Returns:
            GrafanaLokiExtractor instance configured with Bearer token authentication
        """
        auth_headers = {
            'Authorization': f'Bearer {token}'
        }
        
        # Merge with any additional headers
        if headers:
            auth_headers.update(headers)
        
        # Use standard __init__ with pre-built headers
        return cls(base_url, loki_org_id=loki_org_id, headers=auth_headers)
    
    @classmethod
    def from_basic_auth(cls, base_url: str, username: str, password: str, 
                       loki_org_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None) -> 'GrafanaLokiExtractor':
        """
        Create Grafana Loki extractor with Basic authentication.
        
        Args:
            base_url: Loki base URL (e.g., 'http://localhost:3100')
            username: Username for Basic authentication
            password: Password for Basic authentication
            loki_org_id: Optional Loki org ID for multi-tenancy
            headers: Optional additional headers to merge with auth header
            
        Returns:
            GrafanaLokiExtractor instance configured with Basic authentication
        """
        # Encode credentials for Basic auth
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        
        auth_headers = {
            'Authorization': f'Basic {credentials}'
        }
        
        # Merge with any additional headers
        if headers:
            auth_headers.update(headers)
        
        # Use standard __init__ with pre-built headers
        return cls(base_url, loki_org_id=loki_org_id, headers=auth_headers)
    
    @classmethod
    def from_api_key(cls, base_url: str, api_key: str, header_name: str = 'X-API-Key',
                    loki_org_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None) -> 'GrafanaLokiExtractor':
        """
        Create Grafana Loki extractor with API key authentication.
        
        Args:
            base_url: Loki base URL (e.g., 'http://localhost:3100')
            api_key: API key for authentication
            header_name: Header name to use for API key (default: 'X-API-Key')
            loki_org_id: Optional Loki org ID for multi-tenancy
            headers: Optional additional headers to merge with API key header
            
        Returns:
            GrafanaLokiExtractor instance configured with API key authentication
        """
        auth_headers = {
            header_name: api_key
        }
        
        # Merge with any additional headers
        if headers:
            auth_headers.update(headers)
        
        # Use standard __init__ with pre-built headers
        return cls(base_url, loki_org_id=loki_org_id, headers=auth_headers)
    
    @classmethod
    def from_oauth(cls, base_url: str, oauth_config: OAuthConfig,
                   loki_org_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None) -> 'GrafanaLokiExtractor':
        """
        Create Grafana Loki extractor with OAuth 2.0 Client Credentials authentication.
        
        Args:
            base_url: Loki base URL (e.g., 'http://localhost:3100')
            oauth_config: OAuth configuration (client_id, client_secret, token_url, etc.)
            loki_org_id: Optional Loki org ID for multi-tenancy
            headers: Optional additional headers to merge with auth header
            
        Returns:
            GrafanaLokiExtractor instance configured with OAuth authentication
        """
        # Create OAuth token manager
        token_manager = OAuthTokenManager(oauth_config)
        
        # Merge oauth_config.extra_headers (e.g. Consumer-Key) so they always
        # travel alongside the Bearer token added per-request by the token manager
        merged_headers = dict(headers) if headers else {}
        if oauth_config.extra_headers:
            merged_headers.update(oauth_config.extra_headers)
        
        # Use standard __init__ with OAuth token manager
        return cls(base_url, loki_org_id=loki_org_id, headers=merged_headers or None, oauth_token_manager=token_manager)
    
    @classmethod
    def from_oauth_params(cls, base_url: str, client_id: str, client_secret: str, token_url: str,
                          scope: Optional[str] = None, token_expiry_buffer: int = 60,
                          loki_org_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None) -> 'GrafanaLokiExtractor':
        """
        Create Grafana Loki extractor with OAuth 2.0 Client Credentials authentication using individual parameters.
        
        Args:
            base_url: Loki base URL (e.g., 'http://localhost:3100')
            client_id: OAuth client identifier
            client_secret: OAuth client secret
            token_url: OAuth token endpoint URL
            scope: Optional OAuth scopes (comma-separated string)
            token_expiry_buffer: Seconds before expiry to refresh token (default: 60)
            loki_org_id: Optional Loki org ID for multi-tenancy
            headers: Optional additional headers to merge with auth header
            
        Returns:
            GrafanaLokiExtractor instance configured with OAuth authentication
        """
        oauth_config = OAuthConfig(
            clientId=client_id,
            clientSecret=client_secret,
            tokenUrl=token_url,
            scope=scope,
            tokenExpiryBuffer=token_expiry_buffer
        )
        return cls.from_oauth(base_url, oauth_config, loki_org_id=loki_org_id, headers=headers)
    
    def get_log_aggregator_name(self) -> str:
        """
        Get the log aggregator name.
        
        Returns:
            Name of the log aggregator ('LOKI')
        """
        return "LOKI"
    
    def get_query_language(self) -> str:
        """
        Get the query language used by this extractor.
        
        Returns:
            Query language name ('LogQL')
        """
        return "LogQL"
    
    def get_index_name(self) -> str:
        """
        Get the index name (not applicable for Loki, returns empty string).
        
        Returns:
            Empty string (Loki doesn't use indexes)
        """
        return ""
    
    def get_label_names(self) -> List[str]:
        """
        Get available label names from Loki.
        
        Returns:
            List of available label names
        """
        return self.get_labels()
    
    def get_field_names(self) -> List[str]:
        """
        Get field names (Loki uses labels instead of fields).
        Returns label names for compatibility.
        
        Returns:
            List of label names (Loki's equivalent of fields)
        """
        return self.get_labels()

    def precheck(self) -> bool:
        """
        Verify labels are available from Loki. Required before running the query generator agent.
        """
        labels = self.get_label_names()
        if not labels:
            raise QueryGenerationError("Could not generate query: no labels found")
        return True
    
    def fetch_logs(self, query: str, start: Optional[datetime] = None, 
                  end: Optional[datetime] = None, limit: int = 20,
                  direction: str = "backward", **kwargs) -> List[LogEntry]:
        """
        Fetch logs from Grafana Loki using query_range endpoint.
        
        Args:
            query: LogQL query string (e.g., '{job="app"} |= "error"')
                  Note: LogQL queries don't include time ranges in the query string itself.
                  Time ranges are passed as separate parameters.
            start: Start time for query (always used as query parameter)
            end: End time for query (always used as query parameter)
            limit: Maximum number of entries to return
            direction: Sort order ('forward' or 'backward')
            **kwargs: Additional query parameters
            
        Returns:
            List of log entries with timestamp and line
            
        Raises:
            LogExtractorError: If fetching logs fails
        """
        url = f"{self.base_url}/loki/api/v1/query_range"
        
        # For Loki, LogQL queries don't include time in the query string itself.
        # Time ranges are always passed as query parameters.
        # The agent-generated query will be the LogQL query without time/limit.
        # We always use the provided start/end/limit as parameters.
        
        # Prepare query parameters
        params = {
            'query': query,
            'limit': limit,
            'direction': direction,
            **kwargs
        }
        
        # Handle time parameters (always add if provided)
        if start:
            params['start'] = int(start.timestamp() * 1e9)  # Convert to nanoseconds
        
        if end:
            params['end'] = int(end.timestamp() * 1e9)  # Convert to nanoseconds
        
        # Make the request
        logger.debug(f"Loki additional headers: {self.headers}")
        response = self._make_request('GET', url, params=params, headers=self.headers)
        
        logger.info(f"Loki query parameters: {params}")
        logger.info(f"Loki response status: {response.status_code}")
        
        try:
            data = response.json()
            
            if data.get('status') != 'success':
                error_msg = data.get('error', 'Unknown error')
                # Preserve HTTP status code if available from response
                status_code = response.status_code if hasattr(response, 'status_code') else None
                raise LogExtractorError(
                    f"Loki query failed: {error_msg}",
                    status_code=status_code,
                    response_text=response.text if hasattr(response, 'text') else None
                )
            
            # Extract logs from response
            logs = []
            result = data.get('data', {}).get('result', [])
            logger.info(f"Length of result: {len(result)} logs fetched")
            
            for stream in result:
                stream_labels = stream.get('stream', {})
                values = stream.get('values', [])
                
                for timestamp_str, log_line in values:
                    log_entry = self._parse_log_entry(timestamp_str, log_line, stream_labels)
                    logs.append(log_entry)
            
            return logs
            
        except json.JSONDecodeError as e:
            # JSON decode error means malformed response (server error)
            raise LogExtractorError(
                f"Failed to parse Loki response: {str(e)}",
                status_code=500,
                response_text=response.text if hasattr(response, 'text') else None
            )
        except LogExtractorError:
            # Re-raise LogExtractorError as-is
            raise
        except Exception as e:
            # Unexpected error
            raise LogExtractorError(
                f"Unexpected error fetching logs from Loki: {str(e)}",
                status_code=500
            ) from e
    
    def get_labels(self, start: Optional[datetime] = None, 
                   end: Optional[datetime] = None, query: Optional[str] = None) -> List[str]:
        """
        Get available labels from Loki.
        
        Args:
            start: Start time for label search
            end: End time for label search  
            query: Optional query to filter labels
            
        Returns:
            List of available label names
        """

        url = f"{self.base_url}/loki/api/v1/labels"
        
        params = {}
        if start:
            params['start'] = int(start.timestamp() * 1e9)
        if end:
            params['end'] = int(end.timestamp() * 1e9)
        if query:
            params['query'] = query
        
        response = self._make_request('GET', url, params=params, headers=self.headers)
        
        try:
            data = response.json()
            if data.get('status') != 'success':
                error_msg = data.get('error', 'Unknown error')
                status_code = response.status_code if hasattr(response, 'status_code') else None
                raise LogExtractorError(
                    f"Loki labels query failed: {error_msg}",
                    status_code=status_code,
                    response_text=response.text if hasattr(response, 'text') else None
                )
            
            return data.get('data', [])

        except json.JSONDecodeError as e:
            raise LogExtractorError(
                f"Failed to parse Loki response: {str(e)}",
                status_code=500,
                response_text=response.text if hasattr(response, 'text') else None
            )

    def validate_connection(self, timeout: float = 10.0) -> None:
        """Minimal connectivity check: GET /loki/api/v1/labels (validates URL and auth)."""
        self.get_labels()

    def get_label_values(self, label_name: str, start: Optional[datetime] = None,
                        end: Optional[datetime] = None, query: Optional[str] = None) -> List[str]:
        """
        Get available values for a specific label.
        
        Args:
            label_name: Name of the label
            start: Start time for value search
            end: End time for value search
            query: Optional query to filter values
            
        Returns:
            List of available values for the label
        """
        url = f"{self.base_url}/loki/api/v1/label/{label_name}/values"
        
        params = {}
        if start:
            params['start'] = int(start.timestamp() * 1e9)
        if end:
            params['end'] = int(end.timestamp() * 1e9)
        if query:
            params['query'] = query
        
        response = self._make_request('GET', url=url, params=params, headers=self.headers)
        
        try:
            data = response.json()
            if data.get('status') != 'success':
                error_msg = data.get('error', 'Unknown error')
                status_code = response.status_code if hasattr(response, 'status_code') else None
                raise LogExtractorError(
                    f"Loki label values query failed: {error_msg}",
                    status_code=status_code,
                    response_text=response.text if hasattr(response, 'text') else None
                )
            
            return data.get('data', [])
            
        except json.JSONDecodeError as e:
            raise LogExtractorError(
                f"Failed to parse Loki response: {str(e)}",
                status_code=500,
                response_text=response.text if hasattr(response, 'text') else None
            )
    
    def _parse_log_entry(self, timestamp_str: str, log_line: str, 
                        stream_labels: Dict[str, str]) -> LogEntry:
        """
        Parse a raw log entry from Loki into a standardized format.
        
        Args:
            timestamp_str: Nanosecond timestamp string from Loki
            log_line: Raw log line content
            stream_labels: Stream labels from Loki
            
        Returns:
            Standardized log entry dict with timestamp, message, level, labels, traceId, spanId
        """
        # Convert nanosecond timestamp to datetime (UTC)
        timestamp_ns = int(timestamp_str)
        timestamp_dt = datetime.fromtimestamp(timestamp_ns / 1e9, tz=timezone.utc)
        
        # Standardize timestamp to ISO format string (UTC)
        timestamp_iso = timestamp_dt.isoformat()
        
        # Detect log level from labels or log line
        level = None
        # Structured: Loki label 'level'
        if 'level' in stream_labels:
            level = stream_labels['level'].upper()
        else:
            # Unstructured: Parse from log line
            line_upper = log_line.upper()
            for candidate in ['ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE', 'CRITICAL', 'FATAL']:
                if candidate in line_upper:
                    level = candidate
                    break
        
        # Extract traceId/spanId
        trace_id = None
        span_id = None
        
        # Priority 1: Parse message field if it's structured (JSON/logfmt)
        if log_line and isinstance(log_line, str):
            format_type = detect_format(log_line)
            
            if format_type == 'json':
                parsed = parse_json(log_line)
                if parsed:
                    trace_id, span_id = extract_trace_id_span_id(parsed)
                    logger.debug(f"Extracted from JSON message: traceId={trace_id}, spanId={span_id}")
            
            elif format_type == 'logfmt':
                parsed = parse_logfmt(log_line)
                if parsed:
                    trace_id, span_id = extract_trace_id_span_id(parsed)
                    logger.debug(f"Extracted from logfmt message: traceId={trace_id}, spanId={span_id}")
        
        # Priority 2: Check labels dict
        if trace_id is None or span_id is None:
            if trace_id is None:
                trace_id, _ = extract_trace_id_span_id(stream_labels)
            if span_id is None:
                _, span_id = extract_trace_id_span_id(stream_labels)
        
        # Create standardized log entry format (consistent across all extractors)
        log_entry = LogEntry(
            timestamp=timestamp_iso,
            message=log_line,
            labels=stream_labels,
            level=level,
            traceId=trace_id,
            spanId=span_id,
        )
        
        return log_entry
