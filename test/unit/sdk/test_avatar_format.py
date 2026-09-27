"""Tests for the SDK's model-avatar format contribution surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdk.adapters import (
    ModelAssetAdapter,
    ModelCapabilities,
    ModelFiles,
)
from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry


class _NullAdapter(ModelAssetAdapter):
    format_id = "null"
    capabilities = ModelCapabilities(mouth=True)

    def inspect(self, source: Path) -> ModelFiles:
        return ModelFiles(entry=source)

    def parse_state(self, model: Path, value: object) -> dict:
        return {}

    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        return ()


class TestRegisterAvatarFormat:
    def test_registers_and_sorts_by_priority(self):
        registry = PluginCapabilityRegistry()
        registry.register_avatar_format("zeta", _NullAdapter, priority=10)
        registry.register_avatar_format("alpha", _NullAdapter, priority=1)

        assert [c.format_id for c in registry.avatar_formats] == ["alpha", "zeta"]

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError):
            PluginCapabilityRegistry().register_avatar_format("   ", _NullAdapter)

    def test_static_reserved(self):
        with pytest.raises(ValueError):
            PluginCapabilityRegistry().register_avatar_format("static", _NullAdapter)

    def test_non_callable_factory_rejected(self):
        with pytest.raises(TypeError):
            PluginCapabilityRegistry().register_avatar_format("null", object())  # type: ignore[arg-type]


class _AvatarPlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return "demo.avatar"

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        _ = plugin_root, host
        register.register_avatar_format("null", _NullAdapter, label="Null")


def test_plugin_manager_collects_avatar_formats(tmp_path: Path) -> None:
    manager = PluginManager(plugin_data_root=tmp_path)
    manager.register_plugin_class(_AvatarPlugin)

    formats = manager.collect_avatar_formats()
    assert [c.format_id for c in formats] == ["null"]
    assert formats[0].label == "Null"
    assert formats[0].factory().format_id == "null"
