"""Compatibility alias for :mod:`ai.tools.tool_executor`."""

import sys
from ai.tools import tool_executor as _module

sys.modules[__name__] = _module
