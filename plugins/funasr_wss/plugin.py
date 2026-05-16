from __future__ import annotations

from pathlib import Path

from plugins.funasr_wss.adapter import FunASRWSSAdapter
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry


class FunASRWssPlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return "dev.shinsekai.funasr_wss"

    @property
    def plugin_name(self) -> str:
        return "FunASR WSS"

    @property
    def plugin_description(self) -> str:
        return "Connect microphone ASR to a self-hosted FunASR WebSocket service."

    @property
    def plugin_author(self) -> str:
        return "umikok7"

    @property
    def plugin_version(self) -> str:
        return "0.1.0"

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        _ = plugin_root, host
        register.register_asr_adapter("funasr_wss", FunASRWSSAdapter)

    def shutdown(self) -> None:
        return None


Plugin = FunASRWssPlugin
