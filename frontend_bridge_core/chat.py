"""Compatibility alias for :mod:`application.chat.runtime_process`."""

from __future__ import annotations

import sys

from application.chat import runtime_process as _runtime_process

sys.modules[__name__] = _runtime_process
