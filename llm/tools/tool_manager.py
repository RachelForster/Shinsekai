"""Compatibility alias for :mod:`ai.tools.tool_manager`."""

import sys
from ai.tools import tool_manager as _module

sys.modules[__name__] = _module
