"""Compatibility alias for :mod:`application.plugins.catalog`."""

from __future__ import annotations

import sys

from application.plugins import catalog as _catalog

sys.modules[__name__] = _catalog
