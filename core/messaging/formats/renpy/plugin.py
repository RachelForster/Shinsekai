"""Built-in host plugin descriptor for the Ren'Py script DSL format."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sdk.adapters.dialog_format import RENPY_DIALOG_FORMAT_ID
from sdk.plugin import PluginBase

from .format import RenpyDslDialogFormat

if TYPE_CHECKING:
    from sdk.plugin_host_context import PluginHostContext
    from sdk.register import PluginCapabilityRegistry


class RenpyDslPlugin(PluginBase):
    """Built-in plugin contributing the Ren'Py-like dialog format (`renpy_v1`)."""

    @property
    def plugin_id(self) -> str:
        return "shinsekai.builtin.renpy_dsl_format"

    @property
    def plugin_name(self) -> str:
        return "Ren'Py DSL Dialog Format"

    @property
    def plugin_version(self) -> str:
        return "1.0.0"

    @property
    def plugin_description(self) -> str:
        return "Built-in Ren'Py-like script DSL output format (renpy_v1)."

    @property
    def plugin_author(self) -> str:
        return "Shinsekai"

    @property
    def priority(self) -> int:
        return 50

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        del plugin_root, host
        register.register_dialog_format(
            RENPY_DIALOG_FORMAT_ID,
            RenpyDslDialogFormat,
            label=RenpyDslDialogFormat.label,
            priority=50,
        )
