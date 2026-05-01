"""
Minimal plugin contract for lifecycle and metadata only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sdk.plugin_host_context import PluginHostContext
    from sdk.register import PluginCapabilityRegistry


class PluginBase(ABC):
    """
    Base plugin contract.

    Register concrete capabilities inside :meth:`initialize` via
    :class:`~sdk.register.PluginCapabilityRegistry` (historical alias ``PluginRegister``).
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
    def plugin_name(self) -> str:
        """Human-readable title on the plugin manage screen."""
        pid = self.plugin_id
        tail = pid.rpartition(".")[-1]
        if tail:
            return tail.replace("_", " ").strip() or pid
        return pid

    @property
    def plugin_description(self) -> str:
        """Short description; empty hides the line on the manage card."""
        return ""

    @property
    def plugin_author(self) -> str:
        """Author or vendor; empty hides the author segment on the manage card."""
        return ""

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
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        """
        Register plugin capabilities to ``register`` and load internal state.

        ``host`` is a read-only snapshot (:class:`~sdk.plugin_host_context.PluginHostContext`).
        It does **not** include API keys, save APIs, or a :class:`~config.config_manager.ConfigManager`.
        """

    def shutdown(self) -> None:
        """Lifecycle hook called when host is shutting down."""
        return None
