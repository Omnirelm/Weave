"""
OpenSearch integration for log extraction and analysis.
"""
from datetime import datetime, timezone
import json
import logging
import base64
import re
from typing import Dict, Any, List, Optional
from .base import LogExtractor, LogExtractorError, LogEntry, OAuthConfig, OAuthTokenManager, QueryGenerationError
from .parsers import detect_format, parse_json, parse_logfmt, extract_trace_id_span_id

logger = logging.getLogger(__name__)


class OpenSearchExtractor(LogExtractor):
    """OpenSearch log extractor implementation"""
    
    def __init__(self, base_url: str, index_pattern: str = "logs-*",
                 headers: Optional[Dict[str, str]] = None,
                 oauth_token_manager: Optional[OAuthTokenManager] = None):
        """
        Initialize OpenSearch extractor.
        
        Args:
            base_url: OpenSearch base URL (e.g., 'http://localhost:9200')
            index_pattern: Index pattern to search (default: 'logs-*')
            headers: Optional headers dictionary
            oauth_token_manager: Optional OAuth token manager for OAuth authentication
        """
        self.index_pattern = index_pattern
        
        merged_headers = {
            'Content-Type': 'application/json',
        }
        
        # Merge with any additional headers
        if headers:
            merged_headers.update(headers)
        
        # Pass oauth_token_manager to base class
        super().__init__(base_url, merged_headers, oauth_token_manager=oauth_token_manager)
    
    @classmethod
    def from_bearer_token(cls, base_url: str, token: str, 
                          index_pattern: str = "logs-*",
                          headers: Optional[Dict[str, str]] = None) -> 'OpenSearchExtractor':
        """
        Create OpenSearch extractor with Bearer token authentication.
        
        Args:
            base_url: OpenSearch base URL (e.g., 'http://localhost:9200')
            token: Bearer token for authentication
            index_pattern: Index pattern to search (default: 'logs-*')
            headers: Optional additional headers to merge with auth header
            
        Returns:
            OpenSearchExtractor instance configured with Bearer token authentication
        """
        auth_headers = {
            'Authorization': f'Bearer {token}'
        }
        
        # Merge with any additional headers
        if headers:
            auth_headers.update(headers)
        
        # Use standard __init__ with pre-built headers
        return cls(base_url, index_pattern=index_pattern, headers=auth_headers)
    
    @classmethod
    def from_basic_auth(cls, base_url: str, username: str, password: str,
                       index_pattern: str = "logs-*",
                       headers: Optional[Dict[str, str]] = None) -> 'OpenSearchExtractor':
        """
        Create OpenSearch extractor with Basic authentication.
        
        Args:
            base_url: OpenSearch base URL (e.g., 'http://localhost:9200')
            username: Username for Basic authentication
            password: Password for Basic authentication
            index_pattern: Index pattern to search (default: 'logs-*')
            headers: Optional additional headers to merge with auth header
            
        Returns:
            OpenSearchExtractor instance configured with Basic authentication
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
        return cls(base_url, index_pattern=index_pattern, headers=auth_headers)
    
    @classmethod
    def from_oauth(cls, base_url: str, oauth_config: OAuthConfig,
                   index_pattern: str = "logs-*",
                   headers: Optional[Dict[str, str]] = None) -> 'OpenSearchExtractor':
        """
        Create OpenSearch extractor with OAuth 2.0 Client Credentials authentication.
        
        Args:
            base_url: OpenSearch base URL (e.g., 'http://localhost:9200')
            oauth_config: OAuth configuration (client_id, client_secret, token_url, etc.)
            index_pattern: Index pattern to search (default: 'logs-*')
            headers: Optional additional headers to merge with auth header
            
        Returns:
            OpenSearchExtractor instance configured with OAuth authentication
        """
        # Create OAuth token manager
        token_manager = OAuthTokenManager(oauth_config)
        
        # Merge oauth_config.extra_headers (e.g. Consumer-Key) so they always
        # travel alongside the Bearer token added per-request by the token manager
        merged_headers = dict(headers) if headers else {}
        if oauth_config.extra_headers:
            merged_headers.update(oauth_config.extra_headers)
        
        # Use standard __init__ with OAuth token manager
        return cls(base_url, index_pattern=index_pattern, headers=merged_headers or None, oauth_token_manager=token_manager)
    
    @classmethod
    def from_oauth_params(cls, base_url: str, client_id: str, client_secret: str, token_url: str,
                          scope: Optional[str] = None, token_expiry_buffer: int = 60,
                          index_pattern: str = "logs-*",
                          headers: Optional[Dict[str, str]] = None) -> 'OpenSearchExtractor':
        """
        Create OpenSearch extractor with OAuth 2.0 Client Credentials authentication using individual parameters.
        
        Args:
            base_url: OpenSearch base URL (e.g., 'http://localhost:9200')
            client_id: OAuth client identifier
            client_secret: OAuth client secret
            token_url: OAuth token endpoint URL
            scope: Optional OAuth scopes (comma-separated string)
            token_expiry_buffer: Seconds before expiry to refresh token (default: 60)
            index_pattern: Index pattern to search (default: 'logs-*')
            headers: Optional additional headers to merge with auth header
            
        Returns:
            OpenSearchExtractor instance configured with OAuth authentication
        """
        oauth_config = OAuthConfig(
            clientId=client_id,
            clientSecret=client_secret,
            tokenUrl=token_url,
            scope=scope,
            tokenExpiryBuffer=token_expiry_buffer
        )
        return cls.from_oauth(base_url, oauth_config, index_pattern=index_pattern, headers=headers)
    
    def get_log_aggregator_name(self) -> str:
        """
        Get the log aggregator name.
        
        Returns:
            Name of the log aggregator ('OPENSEARCH')
        """
        return "OPENSEARCH"
    
    def get_query_language(self) -> str:
        """
        Get the query language used by this extractor.
        
        Returns:
            Query language name ('PPL')
        """
        return "PPL"
    
    def get_index_name(self) -> str:
        """
        Get the index name/pattern from the log extractor.
        
        Returns:
            Index pattern (e.g., 'otel-logs-*' or 'logs-*')
        """
        return self.index_pattern
    
    def get_label_names(self) -> List[str]:
        """
        Get label names (not applicable for OpenSearch, returns empty list).
        
        Returns:
            Empty list (OpenSearch uses fields, not labels)
        """
        return []

    def get_field_names(self, index: Optional[str] = None) -> List[str]:
        """
        Get available field names from the index mapping.
        
        Args:
            index: Specific index to query (defaults to index_pattern)
            
        Returns:
            List of field names
        """
        target_index = index or self.index_pattern
        url = f"{self.base_url}/{target_index}/_mapping"
        
        try:
            response = self._make_request(method='GET', url=url, headers=self.headers)
            data = response.json()
            
            # Extract field names from mapping
            fields = set()
            for index_name, index_data in data.items():
                mappings = index_data.get('mappings', {})
                properties = mappings.get('properties', {})
                
                def extract_fields(props, prefix=''):
                    for field_name, field_config in props.items():
                        full_name = f"{prefix}{field_name}" if prefix else field_name
                        fields.add(full_name)
                        
                        # Recursively extract nested fields
                        if 'properties' in field_config:
                            extract_fields(field_config['properties'], f"{full_name}.")
                
                extract_fields(properties)
            
            return sorted(list(fields))
            
        except Exception as e:
            raise LogExtractorError(f"Failed to get field names: {str(e)}")

    def validate_connection(self, timeout: float = 10.0) -> None:
        """Minimal connectivity check: GET _cluster/health (validates URL and auth)."""
        url = f"{self.base_url}/_cluster/health"
        response = self._make_request(method="GET", url=url, headers=self.headers, timeout=timeout)
        data = response.json()
        status = data.get("status")
        if status not in ("green", "yellow", "red"):
            raise LogExtractorError(
                f"OpenSearch cluster health check failed: unexpected status {status}",
                status_code=response.status_code,
                response_text=response.text,
            )

    def precheck(self) -> bool:
        """
        Verify index and field names are available from OpenSearch. Required before running the query generator agent.
        """
        index = self.get_index_name()
        if not index:
            raise QueryGenerationError("Could not generate query: no index name found")
        fields = self.get_field_names(index)
        if not fields:
            raise QueryGenerationError("Could not generate query: no field names found")
        return True
    
    def fetch_logs(self, query: str, start: Optional[datetime] = None, 
                  end: Optional[datetime] = None, limit: int = 100,
                  sort_order: str = "desc", timestamp_field: str = "@timestamp",
                  **kwargs) -> List[LogEntry]:
        """
        Fetch logs from OpenSearch using PPL (Piped Processing Language).
        
        Args:
            query: PPL query string (e.g., 'search source=otel-logs-* | where ... | head 100')
                  Agent-generated PPL queries typically include time filters and limit
            start: Start time for query (optional, may be embedded in PPL query)
            end: End time for query (optional, may be embedded in PPL query)
            limit: Maximum number of entries to return (optional, may be embedded in PPL query)
            sort_order: Sort order ('asc' or 'desc') - not used for PPL queries
            timestamp_field: Name of the timestamp field (default: '@timestamp')
            **kwargs: Additional query parameters
            
        Returns:
            List of log entries with timestamp and source data
            
        Raises:
            LogExtractorError: If fetching logs fails or query is not a PPL query
        """
        # Verify that query is a PPL query (must start with "search source=")
        query_stripped = query.strip()
        is_ppl_query = query_stripped.lower().startswith('search source=')
        
        if not is_ppl_query:
            raise LogExtractorError(
                f"Query must be a PPL query starting with 'search source='. "
                f"Received: {query[:100]}..."
            )
        
        # For PPL queries, the query string typically contains everything (time, limit)
        # So we don't need to pass start/end/limit - they're embedded in the query
        return self._fetch_logs_ppl(query, timestamp_field=timestamp_field, **kwargs)

    @staticmethod
    def _normalize_ppl_query(ppl_query: str) -> str:
        """Fix common agent mistakes before sending PPL to OpenSearch."""
        query = ppl_query.strip()
        # OpenSearch PPL rejects quoted index patterns: search source="idx" | ...
        query = re.sub(
            r'(?i)\bsearch\s+source\s*=\s*"([^"]+)"',
            r"search source=\1",
            query,
        )
        query = re.sub(
            r"(?i)\bsearch\s+source\s*=\s*'([^']+)'",
            r"search source=\1",
            query,
        )
        return query
    
    def _fetch_logs_ppl(self, ppl_query: str, 
                       timestamp_field: str = "@timestamp", **kwargs) -> List[LogEntry]:
        """
        Fetch logs using PPL (Piped Processing Language) query.
        
        Args:
            ppl_query: PPL query string (e.g., 'search source=otel-logs-* | where ... | head 100')
                      Agent-generated queries include time filters and limit in the query string
            timestamp_field: Name of the timestamp field (used for parsing, default: '@timestamp')
            **kwargs: Additional parameters
            
        Returns:
            List of log entries
        """
        url = f"{self.base_url}/_plugins/_ppl"
        
        final_ppl_query = self._normalize_ppl_query(ppl_query)
        if final_ppl_query != ppl_query.strip():
            logger.debug("Normalized PPL query: %r -> %r", ppl_query, final_ppl_query)
        
        logger.debug(f"Executing PPL Query: {final_ppl_query}")
        
        try:
            response = self._make_request(
                method='POST', 
                url=url, 
                headers=self.headers,
                json={'query': final_ppl_query}
            )
            
            data = response.json()
            
            # Extract logs from PPL response
            logs = []
            schema = data.get('schema', [])
            datarows = data.get('datarows', [])
            
            # Build field name mapping
            field_indices = {field['name']: idx for idx, field in enumerate(schema)}
            
            for row in datarows:
                log_entry = self._parse_log_entry(row, schema, field_indices, timestamp_field)
                logs.append(log_entry)
            logger.info("--------------------------------")    
            logger.info(f"Fetched {len(logs)} logs")
            logger.info("--------------------------------")    
            return logs
            
        except Exception as e:
            raise LogExtractorError(f"Failed to fetch logs with PPL: {str(e)}")
    
    def _parse_log_entry(self, row: List[Any], schema: List[Dict[str, Any]], 
                        field_indices: Dict[str, int], timestamp_field: str) -> LogEntry:
        """
        Parse a raw log entry from OpenSearch PPL response into a standardized format.
        
        Args:
            row: Raw row data from PPL response
            schema: Schema definition from PPL response
            field_indices: Mapping of field names to indices
            timestamp_field: Name of the timestamp field to use
            
        Returns:
            Standardized log entry dict with timestamp, message, level, source, traceId, spanId
        """
        # Extract timestamp
        timestamp = None
        if timestamp_field in field_indices:
            timestamp = row[field_indices[timestamp_field]]
        elif '@timestamp' in field_indices:
            timestamp = row[field_indices['@timestamp']]
        elif 'observedTimestamp' in field_indices:
            timestamp = row[field_indices['observedTimestamp']]
        
        # Parse timestamp and standardize to UTC timezone-aware datetime
        timestamp_dt = None
        timestamp_iso = None
        if isinstance(timestamp, str):
            try:
                # Parse ISO format, ensure timezone-aware (UTC)
                timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if timestamp_dt.tzinfo is None:
                    timestamp_dt = timestamp_dt.replace(tzinfo=timezone.utc)
                timestamp_iso = timestamp_dt.isoformat()
            except ValueError:
                # If parsing fails, use original string
                timestamp_iso = timestamp
        elif isinstance(timestamp, (int, float)):
            # Handle epoch timestamps
            try:
                timestamp_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                timestamp_iso = timestamp_dt.isoformat()
            except (ValueError, OSError):
                timestamp_iso = str(timestamp)
        elif timestamp is not None:
            # Fallback: convert to string
            timestamp_iso = str(timestamp)
        
        # Extract log level
        level = None
        if 'SeverityText' in field_indices:
            level = str(row[field_indices['SeverityText']]).upper() if row[field_indices['SeverityText']] else None
        elif 'severity.text' in field_indices:
            level = str(row[field_indices['severity.text']]).upper() if row[field_indices['severity.text']] else None
        elif 'level' in field_indices:
            level = str(row[field_indices['level']]).upper() if row[field_indices['level']] else None
        
        # Extract message
        message = ''
        if 'Body' in field_indices:
            message = row[field_indices['Body']] or ''
        elif 'body' in field_indices:
            message = row[field_indices['body']] or ''
        elif 'message' in field_indices:
            message = row[field_indices['message']] or ''
        
        # Build source dict from all fields (rename to 'labels' for consistency)
        source = {schema[i]['name']: row[i] for i in range(len(schema))}
        
        # Extract traceId/spanId
        trace_id = None
        span_id = None
        
        # Priority 1: Parse message field if it's structured (JSON/logfmt)
        if message and isinstance(message, str):
            format_type = detect_format(message)
            
            if format_type == 'json':
                parsed = parse_json(message)
                if parsed:
                    trace_id, span_id = extract_trace_id_span_id(parsed)
                    logger.debug(f"Extracted from JSON message: traceId={trace_id}, spanId={span_id}")
            
            elif format_type == 'logfmt':
                parsed = parse_logfmt(message)
                if parsed:
                    trace_id, span_id = extract_trace_id_span_id(parsed)
                    logger.debug(f"Extracted from logfmt message: traceId={trace_id}, spanId={span_id}")
        
        # Priority 2: Check source dict
        if trace_id is None or span_id is None:
            if trace_id is None:
                trace_id, _ = extract_trace_id_span_id(source)
            if span_id is None:
                _, span_id = extract_trace_id_span_id(source)
        
        log_entry = LogEntry(
            timestamp=timestamp_iso if timestamp_iso else None,
            message=message,
            level=level,
            labels=source,
            traceId=trace_id,
            spanId=span_id,
        )
        
        return log_entry
    