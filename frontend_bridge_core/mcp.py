"""Compatibility alias for MCP application use cases."""

import sys

from application import mcp as _module

sys.modules[__name__] = _module
