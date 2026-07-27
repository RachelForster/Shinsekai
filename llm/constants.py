"""Compatibility alias for :mod:`config.llm_defaults`."""

import sys
from config import llm_defaults as _module

sys.modules[__name__] = _module
