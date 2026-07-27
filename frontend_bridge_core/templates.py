"""Compatibility alias for :mod:`application.chat.templates`."""

from __future__ import annotations

import sys

from application.chat import templates as _templates

sys.modules[__name__] = _templates
