# Changelog

All notable changes to the Reverse Engineering API skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-12-31

### Added

- Initial release of the Reverse Engineering API skill
- Core SKILL.md with 4-phase workflow:
  - Phase 1: Browser Capture with HAR Recording
  - Phase 2: HAR Analysis
  - Phase 3: API Client Generation
  - Phase 4: Testing & Refinement
- Reference documentation:
  - `references/AUTH_PATTERNS.md` - 8 authentication patterns with code examples
  - `references/HAR_ANALYSIS.md` - HAR parsing and endpoint extraction guide
- Playwright MCP integration for browser control
- Support for HAR files at `~/.reverse-api/runs/har/{run_id}/`
- Decision tree for workflow routing
- Python API client generation templates
- Iteration protocol with up to 5 retry attempts
- Bot detection handling with Playwright fallback

### Dependencies

Scripts require:
- `aiohttp` - Async HTTP client (required for all scripts)
- `playwright` - Browser automation (required for mapper.py)
- `beautifulsoup4` - HTML parsing (optional for crawler.py, falls back to regex)
