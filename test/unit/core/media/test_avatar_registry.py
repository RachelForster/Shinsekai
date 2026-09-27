"""Tests for the runtime model-avatar format registry."""

from pathlib import Path

import pytest

from core.media.avatar import registry
from sdk.adapters import (
    AvatarFormatContribution,
    ModelAssetAdapter,
    ModelCapabilities,
    ModelFiles,
)


class _NullAdapter(ModelAssetAdapter):
    format_id = "null"
    capabilities = ModelCapabilities(mouth=True)

    def inspect(self, source: Path) -> ModelFiles:
        return ModelFiles(entry=source)

    def parse_state(self, model: Path, value: object) -> dict:
        return dict(value) if isinstance(value, dict) else {}

    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        return ()


@pytest.fixture(autouse=True)
def _clean_registry():
    registry._reset_for_tests()
    yield
    registry._reset_for_tests()


class TestRegisterAdapter:
    def test_register_and_lookup(self):
        registry.register_adapter(_NullAdapter())
        assert registry.adapter_for("null") is not None
        assert registry.registered_format_ids() == ("null",)
        assert registry.is_registered_format("null")

    def test_unknown_format_raises(self):
        with pytest.raises(KeyError):
            registry.adapter_for("missing")

    def test_duplicate_rejected(self):
        registry.register_adapter(_NullAdapter())
        with pytest.raises(ValueError):
            registry.register_adapter(_NullAdapter())

    def test_static_reserved(self):
        class StaticAdapter(_NullAdapter):
            format_id = "static"

        with pytest.raises(ValueError):
            registry.register_adapter(StaticAdapter())

    def test_capabilities_available(self):
        registry.register_adapter(_NullAdapter())
        assert registry.capabilities_for("null").mouth is True


class TestConfigureRegisteredFormats:
    def test_plugin_formats_are_merged(self):
        registry.configure_registered_formats(
            [AvatarFormatContribution(format_id="null", factory=_NullAdapter)]
        )
        assert registry.adapter_for("null").format_id == "null"
        assert registry.registered_format_ids() == ("null",)

    def test_factory_failure_is_skipped(self):
        def broken() -> ModelAssetAdapter:
            raise RuntimeError("boom")

        registry.configure_registered_formats(
            [
                AvatarFormatContribution(format_id="broken", factory=broken),
                AvatarFormatContribution(format_id="null", factory=_NullAdapter),
            ]
        )
        assert registry.registered_format_ids() == ("null",)

    def test_builtin_wins_over_plugin(self):
        registry.register_adapter(_NullAdapter())
        registry.configure_registered_formats(
            [AvatarFormatContribution(format_id="null", factory=_NullAdapter)]
        )
        assert registry.registered_format_ids() == ("null",)

    def test_static_plugin_contribution_ignored(self):
        class StaticAdapter(_NullAdapter):
            format_id = "static"

        registry.configure_registered_formats(
            [AvatarFormatContribution(format_id="static", factory=StaticAdapter)]
        )
        assert registry.registered_format_ids() == ()
