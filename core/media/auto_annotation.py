"""Compatibility alias for :mod:`application.media.auto_annotation`."""

from __future__ import annotations

import importlib
import sys

sys.modules[__name__] = importlib.import_module("application.media.auto_annotation")
