"""Compatibility alias for :mod:`ai.tts.tts_adapter`."""

import sys
from ai.tts import tts_adapter as _module

sys.modules[__name__] = _module
