# HAR File Analysis Reference

This document covers how to analyze HAR (HTTP Archive) files to extract API endpoints and patterns.

## HAR File Structure

```json
{
  "log": {
    "version": "1.2",
    "creator": { "name": "Browser", "version": "1.0" },
    "entries": [
      {
        "startedDateTime": "2025-01-01T12:00:00.000Z",
        "time": 150,
        "request": { ... },
        "response": { ... },
        "cache": {},
        "timings": { ... }
      }
    ]
  }
}
```

## Entry Structure

### Request Object
```json
{
  "method": "POST",
  "url": "https://api.example.com/v1/users",
  "httpVersion": "HTTP/2.0",
  "headers": [
    { "name": "Content-Type", "value": "application/json" },
    { "name": "Authorization", "value": "Bearer xxx" }
  ],
  "queryString": [
    { "name": "page", "value": "1" }
  ],
  "postData": {
    "mimeType": "application/json",
    "text": "{\"name\": \"John\"}"
  },
  "cookies": [
    { "name": "session", "value": "abc123" }
  ]
}
```

### Response Object
```json
{
  "status": 200,
  "statusText": "OK",
  "headers": [
    { "name": "Content-Type", "value": "application/json" }
  ],
  "content": {
    "size": 1024,
    "mimeType": "application/json",
    "text": "{\"id\": 1, \"name\": \"John\"}"
  }
}
```

## Filtering Entries

### URLs to Exclude

**Static Assets:**
- `.js`, `.css`, `.map`
- `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.ico`
- `.woff`, `.woff2`, `.ttf`, `.eot`
- `.mp4`, `.webm`, `.mp3`

**Analytics & Tracking:**
- `google-analytics.com`
- `googletagmanager.com`
- `segment.io`, `segment.com`
- `mixpanel.com`
- `hotjar.com`
- `facebook.com/tr`
- `doubleclick.net`
- `adsense`

**CDN Resources:**
- `cdn.`, `static.`, `assets.`
- `cloudflare.com`
- `cloudfront.net`
- `akamai`

### URLs to Focus On

**API Patterns:**
- `/api/`
- `/v1/`, `/v2/`, `/v3/`
- `/graphql`
- `/rest/`
- `/data/`

**Content Types:**
- `application/json`
- `application/xml`
- `text/plain` (sometimes API responses)

## Extracting Endpoints

### Step 1: Parse HAR
```python
import json
from urllib.parse import urlparse, parse_qs

def load_har(path: str) -> dict:
    with open(path) as f:
        return json.load(f)

har = load_har("capture.har")
entries = har["log"]["entries"]
```

### Step 2: Filter Relevant Entries
```python
SKIP_EXTENSIONS = {'.js', '.css', '.png', '.jpg', '.svg', '.woff', '.ico'}
SKIP_DOMAINS = {'google-analytics.com', 'facebook.com', 'segment.io'}

def is_relevant(entry: dict) -> bool:
    url = entry["request"]["url"]
    parsed = urlparse(url)
    
    # Skip static assets
    if any(parsed.path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    
    # Skip tracking
    if any(d in parsed.netloc for d in SKIP_DOMAINS):
        return False
    
    # Check for API patterns
    if any(p in parsed.path for p in ['/api/', '/v1/', '/graphql']):
        return True
    
    # Check content type
    response = entry["response"]
    content_type = next(
        (h["value"] for h in response["headers"] 
         if h["name"].lower() == "content-type"),
        ""
    )
    if "application/json" in content_type:
        return True
    
    return False

api_entries = [e for e in entries if is_relevant(e)]
```

### Step 3: Group by Endpoint
```python
from collections import defaultdict

endpoints = defaultdict(list)

for entry in api_entries:
    request = entry["request"]
    url = request["url"]
    parsed = urlparse(url)
    
    # Create endpoint key (method + path without query)
    method = request["method"]
    path = parsed.path
    key = f"{method} {path}"
    
    endpoints[key].append(entry)

# Analyze each endpoint
for key, entries in endpoints.items():
    print(f"\n{key}")
    print(f"  Calls: {len(entries)}")
    
    # Get unique query parameters
    all_params = set()
    for e in entries:
        for param in e["request"].get("queryString", []):
            all_params.add(param["name"])
    if all_params:
        print(f"  Query params: {', '.join(all_params)}")
```

### Step 4: Extract Request Schema
```python
def extract_request_schema(entries: list) -> dict:
    """Infer request body schema from multiple calls."""
    schemas = []
    
    for entry in entries:
        post_data = entry["request"].get("postData", {})
        if post_data.get("mimeType") == "application/json":
            try:
                body = json.loads(post_data.get("text", "{}"))
                schemas.append(body)
            except:
                pass
    
    if not schemas:
        return {}
    
    # Merge schemas to find common fields
    all_keys = set()
    for s in schemas:
        if isinstance(s, dict):
            all_keys.update(s.keys())
    
    return {
        "type": "object",
        "properties": {k: {"type": "unknown"} for k in all_keys}
    }
```

### Step 5: Extract Response Schema
```python
def extract_response_schema(entries: list) -> dict:
    """Infer response schema from multiple calls."""
    for entry in entries:
        content = entry["response"].get("content", {})
        if content.get("mimeType") == "application/json":
            try:
                text = content.get("text", "")
                if text:
                    data = json.loads(text)
                    return infer_schema(data)
            except:
                pass
    return {}

def infer_schema(data) -> dict:
    """Infer JSON schema from data."""
    if isinstance(data, dict):
        return {
            "type": "object",
            "properties": {k: infer_schema(v) for k, v in data.items()}
        }
    elif isinstance(data, list):
        if data:
            return {"type": "array", "items": infer_schema(data[0])}
        return {"type": "array", "items": {}}
    elif isinstance(data, bool):
        return {"type": "boolean"}
    elif isinstance(data, int):
        return {"type": "integer"}
    elif isinstance(data, float):
        return {"type": "number"}
    elif isinstance(data, str):
        return {"type": "string"}
    else:
        return {"type": "null"}
```

## Identifying Path Parameters

Look for patterns in paths:
```python
import re

def find_path_params(paths: list[str]) -> str:
    """Find path parameters by looking at variations."""
    # Example: ["/users/1", "/users/2", "/users/3"] -> "/users/{id}"
    
    # Split paths into segments
    segments_list = [p.strip("/").split("/") for p in paths]
    
    if not segments_list:
        return ""
    
    result = []
    num_segments = len(segments_list[0])
    
    for i in range(num_segments):
        values = set(s[i] for s in segments_list if len(s) > i)
        
        # If all values are the same, it's a static segment
        if len(values) == 1:
            result.append(values.pop())
        # If values look like IDs (numbers, UUIDs), it's a parameter
        elif all(v.isdigit() or is_uuid(v) for v in values):
            result.append("{id}")
        else:
            result.append("{param}")
    
    return "/" + "/".join(result)

def is_uuid(s: str) -> bool:
    pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    return bool(re.match(pattern, s, re.IGNORECASE))
```

## Extracting Headers

### Required vs Optional Headers
```python
def analyze_headers(entries: list) -> tuple[set, set]:
    """Determine required vs optional headers."""
    all_headers = []
    
    for entry in entries:
        headers = {h["name"].lower(): h["value"] 
                   for h in entry["request"]["headers"]}
        all_headers.append(headers)
    
    if not all_headers:
        return set(), set()
    
    # Headers present in ALL requests are required
    required = set(all_headers[0].keys())
    for h in all_headers[1:]:
        required &= set(h.keys())
    
    # Headers present in SOME requests are optional
    all_keys = set()
    for h in all_headers:
        all_keys.update(h.keys())
    optional = all_keys - required
    
    # Filter out browser-added headers
    browser_headers = {
        'accept', 'accept-encoding', 'accept-language', 
        'connection', 'host', 'user-agent', 'sec-ch-ua',
        'sec-ch-ua-mobile', 'sec-ch-ua-platform', 'sec-fetch-dest',
        'sec-fetch-mode', 'sec-fetch-site', 'referer', 'origin'
    }
    
    required -= browser_headers
    optional -= browser_headers
    
    return required, optional
```

## Common Patterns

### Pagination
Look for:
- Query params: `page`, `offset`, `limit`, `cursor`, `after`, `before`
- Response fields: `next`, `previous`, `total`, `has_more`, `next_cursor`

### Filtering
Look for:
- Query params: `filter`, `q`, `search`, `query`, `sort`, `order`

### GraphQL
Look for:
- POST to `/graphql`
- Body with `query` and `variables` fields
- Response with `data` and `errors` fields

## Output Format

After analysis, generate a summary:

```markdown
## API Summary

### Base URL
https://api.example.com

### Authentication
Bearer token in Authorization header

### Endpoints

#### GET /api/users
- Query params: page (int), limit (int)
- Response: Array of User objects

#### POST /api/users
- Body: { name: string, email: string }
- Response: User object

#### GET /api/users/{id}
- Path params: id (int)
- Response: User object
```
