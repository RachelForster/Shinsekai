"""Compatibility alias for :mod:`ai.t2i.t2i_adapter`."""

import sys
from ai.t2i import t2i_adapter as _module

sys.modules[__name__] = _module
