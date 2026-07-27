"""Compatibility alias for :mod:`application.runtime.event_sink`."""

from __future__ import annotations

import importlib
import sys

sys.modules[__name__] = importlib.import_module("application.runtime.event_sink")
