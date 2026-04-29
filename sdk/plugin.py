"""
Minimal plugin contract for lifecycle and metadata only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.config_manager import ConfigManager
    from sdk.register import PluginRegister


class PluginBase(ABC):
    """
    Base plugin contract.

    Register concrete capabilities inside :meth:`initialize` via
    :class:`sdk.register.PluginRegister`.
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique stable id, e.g. ``com.example.myplugin``."""

    @property
    def plugin_version(self) -> str:
        """Semantic version string."""
        return "0.1.0"

    @property
    def enabled(self) -> bool:
        """Whether this plugin should be initialized."""
        return True

    @property
    def priority(self) -> int:
        """Lower value means earlier initialization."""
        return 100

    @abstractmethod
    def initialize(
        self,
        register: PluginRegister,
        plugin_root: Path,
        app_config: ConfigManager | None = None,
    ) -> None:
        """
        Register plugin capabilities to ``register`` and load internal state.
        """

    def shutdown(self) -> None:
        """Lifecycle hook called when host is shutting down."""
        return None
