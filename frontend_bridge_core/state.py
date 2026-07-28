"""Compatibility alias for :mod:`application.runtime.state`."""

from __future__ import annotations

import sys

from application.runtime import state as _state

sys.modules[__name__] = _state
