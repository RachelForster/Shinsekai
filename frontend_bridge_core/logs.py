"""Compatibility alias for :mod:`application.diagnostics.logs`."""

from __future__ import annotations

import sys

from application.diagnostics import logs as _logs

sys.modules[__name__] = _logs
