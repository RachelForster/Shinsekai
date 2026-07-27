"""Compatibility alias for :mod:`ai.llm.text_processor`."""

import sys
from ai.llm import text_processor as _module

sys.modules[__name__] = _module
