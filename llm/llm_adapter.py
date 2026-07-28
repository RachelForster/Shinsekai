"""Compatibility alias for :mod:`ai.llm.llm_adapter`."""

import sys
from ai.llm import llm_adapter as _module

sys.modules[__name__] = _module
