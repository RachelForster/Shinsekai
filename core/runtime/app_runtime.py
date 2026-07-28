"""Compatibility alias for :mod:`application.runtime.context`."""

from __future__ import annotations

import importlib
import sys

sys.modules[__name__] = importlib.import_module("application.runtime.context")
