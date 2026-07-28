"""Compatibility alias for :mod:`ai.llm.claude_url`."""

import sys
from ai.llm import claude_url as _module

sys.modules[__name__] = _module
