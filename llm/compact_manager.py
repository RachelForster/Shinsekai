"""Compatibility alias for :mod:`ai.llm.compact_manager`."""

import sys
from ai.llm import compact_manager as _module

sys.modules[__name__] = _module
