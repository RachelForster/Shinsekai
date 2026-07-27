"""Compatibility alias for :mod:`ai.tools.tool_search`."""

import sys
from ai.tools import tool_search as _module

sys.modules[__name__] = _module
