"""Compatibility alias for :mod:`config.persistence.mcp_config`."""

import sys

from config.persistence import mcp_config as _module


sys.modules[__name__] = _module
