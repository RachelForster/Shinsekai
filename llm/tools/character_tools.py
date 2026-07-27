"""Compatibility alias for :mod:`ai.tools.character_tools`."""

import sys
from ai.tools import character_tools as _module

sys.modules[__name__] = _module
