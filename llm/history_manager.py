"""Compatibility alias for :mod:`ai.llm.history_manager`."""

import sys

from ai.llm import history_manager as _module

sys.modules[__name__] = _module
