"""Compatibility alias for :mod:`ai.tools.chat_ui_tools`."""

import sys

from ai.tools import chat_ui_tools as _module

sys.modules[__name__] = _module
