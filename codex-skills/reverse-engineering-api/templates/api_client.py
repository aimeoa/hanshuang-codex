#!/usr/bin/env python3
"""
API Client Template for Reverse Engineered APIs

This template provides a production-ready structure for API clients
generated from HAR file analysis.

Usage:
    1. Copy this template
    2. Update BASE_URL, headers, and authentication
    3. Add endpoint methods based on HAR analysis
    4. Test and refine
"""

import logging
import time
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class APIError(Exception):
    """Custom exception for API errors."""

    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class RateLimitError(APIError):
    """Exception for rate limit errors."""

    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class APIClient:
    """
    Production-ready API client.

    Features:
    - Automatic retry with exponential backoff
    - Session management for connection pooling
    - Configurable authentication
    - Rate limit handling
    - Comprehensive logging
    """

    # Update these based on HAR analysis
    BASE_URL = "https://api.example.com"
    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        access_token: str = None,
        session_cookie: str = None,
        timeout: int = None,
    ):
        """
        Initialize the API client.

        Args:
            base_url: Override the default base URL
            api_key: API key for X-API-Key authentication
            access_token: Bearer token for Authorization header
            session_cookie: Session cookie value
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or self.BASE_URL).rstrip('/')
        self.timeout = timeout or self.DEFAULT_TIMEOUT

        # Setup session with retry strategy
        self.session = requests.Session()

        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set default headers (update based on HAR analysis)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        })

        # Configure authentication
        if api_key:
            self.session.headers['X-API-Key'] = api_key
        if access_token:
            self.session.headers['Authorization'] = f'Bearer {access_token}'
        if session_cookie:
            self.session.cookies.set('session', session_cookie)

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint."""
        if endpoint.startswith('http'):
            return endpoint
        return urljoin(self.base_url + '/', endpoint.lstrip('/'))

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        Handle API response with error checking.

        Args:
            response: Response object from requests

        Returns:
            Parsed JSON response or empty dict

        Raises:
            RateLimitError: When rate limited
            APIError: For other API errors
        """
        # Log response details
        logger.debug(f"Response: {response.status_code} {response.url}")

        # Handle rate limiting
        if response.status_code == 429:
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    retry_after = int(retry_after)
                except ValueError:
                    retry_after = 60
            raise RateLimitError(
                "Rate limit exceeded",
                retry_after=retry_after
            )

        # Handle errors
        if not response.ok:
            try:
                error_body = response.json()
            except:
                error_body = {'message': response.text}

            raise APIError(
                f"API error: {response.status_code}",
                status_code=response.status_code,
                response=error_body
            )

        # Parse response
        if response.status_code == 204:
            return {}

        try:
            return response.json()
        except:
            return {'text': response.text}

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint path
            params: Query parameters
            data: Form data
            json_data: JSON body
            headers: Additional headers
            files: Files for multipart upload
            timeout: Request timeout override

        Returns:
            Parsed response data
        """
        url = self._build_url(endpoint)
        request_timeout = timeout or self.timeout

        logger.info(f"{method} {url}")

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=headers,
                files=files,
                timeout=request_timeout,
            )
            return self._handle_response(response)

        except RateLimitError:
            raise
        except APIError:
            raise
        except requests.Timeout:
            raise APIError(f"Request timeout after {request_timeout}s")
        except requests.ConnectionError as e:
            raise APIError(f"Connection error: {e}")
        except Exception as e:
            logger.exception("Unexpected error")
            raise APIError(f"Request failed: {e}")

    # Convenience methods
    def get(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a GET request."""
        return self._request('GET', endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a POST request."""
        return self._request('POST', endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a PUT request."""
        return self._request('PUT', endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a PATCH request."""
        return self._request('PATCH', endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a DELETE request."""
        return self._request('DELETE', endpoint, **kwargs)

    # =========================================================================
    # API Endpoints - Add methods here based on HAR analysis
    # =========================================================================

    # Example: List resources
    def list_resources(
        self,
        page: int = 1,
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        List resources with pagination.

        Args:
            page: Page number (1-indexed)
            limit: Items per page
            filters: Optional filter parameters

        Returns:
            Dict with 'items' list and pagination info
        """
        params = {
            'page': page,
            'limit': limit,
        }
        if filters:
            params.update(filters)

        return self.get('/api/resources', params=params)

    # Example: Get single resource
    def get_resource(self, resource_id: str) -> Dict[str, Any]:
        """
        Get a resource by ID.

        Args:
            resource_id: The resource identifier

        Returns:
            Resource data
        """
        return self.get(f'/api/resources/{resource_id}')

    # Example: Create resource
    def create_resource(
        self,
        name: str,
        description: Optional[str] = None,
        **extra_fields,
    ) -> Dict[str, Any]:
        """
        Create a new resource.

        Args:
            name: Resource name
            description: Optional description
            **extra_fields: Additional fields

        Returns:
            Created resource data
        """
        payload = {
            'name': name,
        }
        if description:
            payload['description'] = description
        payload.update(extra_fields)

        return self.post('/api/resources', json_data=payload)

    # Example: Update resource
    def update_resource(
        self,
        resource_id: str,
        **fields,
    ) -> Dict[str, Any]:
        """
        Update a resource.

        Args:
            resource_id: The resource identifier
            **fields: Fields to update

        Returns:
            Updated resource data
        """
        return self.patch(f'/api/resources/{resource_id}', json_data=fields)

    # Example: Delete resource
    def delete_resource(self, resource_id: str) -> bool:
        """
        Delete a resource.

        Args:
            resource_id: The resource identifier

        Returns:
            True if deleted successfully
        """
        self.delete(f'/api/resources/{resource_id}')
        return True

    # Example: Paginate through all resources
    def iter_all_resources(
        self,
        limit: int = 100,
        **filters,
    ):
        """
        Iterate through all resources with automatic pagination.

        Args:
            limit: Items per page
            **filters: Filter parameters

        Yields:
            Resource items one by one
        """
        page = 1
        while True:
            response = self.list_resources(page=page, limit=limit, filters=filters)

            items = response.get('items', response.get('data', []))
            if not items:
                break

            for item in items:
                yield item

            # Check if more pages
            total = response.get('total', 0)
            if page * limit >= total:
                break

            page += 1


class RateLimitHandler:
    """Helper class for handling rate limits with backoff."""

    def __init__(self, client: APIClient):
        self.client = client
        self.last_retry_after = 0

    def execute_with_retry(
        self,
        func,
        *args,
        max_retries: int = 3,
        **kwargs,
    ):
        """
        Execute a function with automatic rate limit retry.

        Args:
            func: Function to call (should be an API client method)
            *args: Arguments for the function
            max_retries: Maximum retry attempts
            **kwargs: Keyword arguments for the function

        Returns:
            Function result
        """
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except RateLimitError as e:
                if attempt == max_retries - 1:
                    raise

                wait_time = e.retry_after or (2 ** attempt * 10)
                self.last_retry_after = wait_time
                logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        raise APIError("Max retries exceeded")


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Initialize client
    client = APIClient(
        base_url="https://api.example.com",
        # api_key="your-api-key",
        # access_token="your-bearer-token",
    )

    try:
        # List resources
        print("Fetching resources...")
        response = client.list_resources(page=1, limit=10)
        print(f"Found {len(response.get('items', []))} resources")

        # Create a resource
        # new_resource = client.create_resource(
        #     name="Test Resource",
        #     description="Created via API client"
        # )
        # print(f"Created: {new_resource}")

        # Iterate all resources
        # for resource in client.iter_all_resources():
        #     print(f"Resource: {resource['id']} - {resource['name']}")

    except RateLimitError as e:
        print(f"Rate limited! Retry after {e.retry_after}s")
    except APIError as e:
        print(f"API Error: {e} (status: {e.status_code})")
    except Exception as e:
        print(f"Error: {e}")