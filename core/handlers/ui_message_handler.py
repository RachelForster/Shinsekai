"""Compatibility alias for :mod:`application.chat.handlers.presentation`."""

from __future__ import annotations

import importlib
import sys

sys.modules[__name__] = importlib.import_module(
    "application.chat.handlers.presentation"
)
