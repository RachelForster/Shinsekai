"""Compatibility alias for :mod:`ai.asr.asr_adapter`."""

import sys
from ai.asr import asr_adapter as _module

sys.modules[__name__] = _module
