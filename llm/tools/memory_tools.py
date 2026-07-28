"""Compatibility alias for :mod:`ai.tools.memory_tools`."""

import sys
from ai.tools import memory_tools as _module

sys.modules[__name__] = _module
