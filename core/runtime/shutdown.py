"""Compatibility alias for :mod:`application.runtime.shutdown`."""

from __future__ import annotations

import importlib
import sys

sys.modules[__name__] = importlib.import_module("application.runtime.shutdown")
