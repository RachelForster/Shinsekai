"""Compatibility alias for :mod:`application.chat.initialization`."""

from __future__ import annotations

import sys

from application.chat import initialization as _initialization

sys.modules[__name__] = _initialization
