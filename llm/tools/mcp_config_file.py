"""Compatibility alias for :mod:`config.mcp_config`."""

import sys

from config import mcp_config as _module

sys.modules[__name__] = _module
