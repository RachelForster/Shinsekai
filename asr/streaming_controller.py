"""Compatibility alias for :mod:`ai.asr.streaming_controller`."""

import sys
from ai.asr import streaming_controller as _module

sys.modules[__name__] = _module
