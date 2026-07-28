"""Compatibility alias for :mod:`application.runtime.tasks`."""

from __future__ import annotations

import sys

from application.runtime import tasks as _tasks

sys.modules[__name__] = _tasks
