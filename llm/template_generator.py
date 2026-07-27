"""Compatibility alias for :mod:`ai.llm.template_generator`."""

import sys
from ai.llm import template_generator as _module

sys.modules[__name__] = _module
