"""Compatibility alias for :mod:`ai.llm.llm_manager`."""

import sys

from ai.llm import llm_manager as _module

sys.modules[__name__] = _module
