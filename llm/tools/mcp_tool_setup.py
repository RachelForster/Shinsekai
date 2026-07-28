"""Compatibility alias for :mod:`ai.tools.mcp_tool_setup`."""

import sys
from ai.tools import mcp_tool_setup as _module

sys.modules[__name__] = _module
