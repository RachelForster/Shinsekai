"""Compatibility alias for :mod:`ai.tools.mcp_bridge`."""

import sys
from ai.tools import mcp_bridge as _module

sys.modules[__name__] = _module
