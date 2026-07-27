"""Compatibility alias for :mod:`ai.llm.message_sanitizer`."""

import sys
from ai.llm import message_sanitizer as _module

sys.modules[__name__] = _module
