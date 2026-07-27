"""Compatibility alias for :mod:`application.plugins.updates`."""

from __future__ import annotations

import sys

from application.plugins import updates as _updates

sys.modules[__name__] = _updates
