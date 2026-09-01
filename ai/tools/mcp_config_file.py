"""Compatibility alias for :mod:`config.repository.mcp_config`."""

import sys

from config.repository import mcp_config as _module


sys.modules[__name__] = _module
