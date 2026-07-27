"""Compatibility alias for :mod:`ai.tools.mcp_config_file`."""

import sys
from ai.tools import mcp_config_file as _module

sys.modules[__name__] = _module
