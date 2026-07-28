"""Compatibility alias for :mod:`application.chat.history_state`."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("application.chat.history_state")
