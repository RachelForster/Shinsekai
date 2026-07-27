"""Compatibility alias for :mod:`application.runtime.dependencies`."""

from __future__ import annotations

import sys

from application.runtime import dependencies as _dependencies

sys.modules[__name__] = _dependencies
