"""Compatibility alias for :mod:`ai.tools.file_tools`."""

import sys
from ai.tools import file_tools as _module

sys.modules[__name__] = _module
