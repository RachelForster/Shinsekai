"""Compatibility alias for :mod:`application.chat.history_paths`."""

from __future__ import annotations

import sys

from application.chat import history_paths as _history_paths

sys.modules[__name__] = _history_paths
