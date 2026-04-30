from __future__ import annotations

from pathlib import Path

from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry
from sdk.types import ToolsTabContribution

from plugins.moondream_vision import runtime


class MoondreamVisionPlugin(PluginBase):
    """Moondream2 + mss：将屏幕内容识别结果作为用户消息提交。"""

    @property
    def plugin_id(self) -> str:
        return "com.easyai.moondream_vision"

    @property
    def plugin_version(self) -> str:
        return "0.1.0"

    @property
    def priority(self) -> int:
        return 80

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        runtime.set_plugin_root(plugin_root)
        register.register_user_input_trigger(runtime.bind_emit)

        tab_root = plugin_root

        def build_tools(plg):
            from plugins.moondream_vision.settings_tab import MoondreamVisionSettingsTab

            return MoondreamVisionSettingsTab(plg, tab_root)

        register.register_tools_tab(
            ToolsTabContribution(
                tab_id="moondream_vision",
                title="Moondream 识屏",
                build=build_tools,
                order=45.0,
            )
        )

    def shutdown(self) -> None:
        runtime.shutdown()
