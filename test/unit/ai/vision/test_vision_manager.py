from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.vision import VisionAdapter, VisionManager
from ai.vision.moondream_adapter import (
    MOONDREAM_PLUGIN_ID,
    MoondreamPluginUnavailable,
    MoondreamVisionAdapter,
    _bind_plugin_config_paths,
    _moondream_config_path,
)


class FakeVisionAdapter(VisionAdapter):
    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return f"{len(image_bytes)}:{prompt}"


def test_vision_manager_dispatches_to_registered_adapter(monkeypatch):
    monkeypatch.setattr(VisionManager, "_adapters", dict(VisionManager._adapters))
    VisionManager.register_adapter("fake", FakeVisionAdapter)

    manager = VisionManager("FAKE")

    assert manager.describe(b"image", "describe") == "5:describe"


def test_moondream_adapter_requires_the_optional_plugin(monkeypatch):
    monkeypatch.setattr(
        "ai.vision.moondream_adapter.installed_moondream_directory",
        lambda **_kwargs: None,
    )

    with pytest.raises(MoondreamPluginUnavailable, match="Moondream"):
        MoondreamVisionAdapter()


def test_moondream_cache_path_uses_project_root_after_cwd_changes(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)
    config = SimpleNamespace(cache_dir="data/cache/moondream")

    _bind_plugin_config_paths(config)

    assert config.cache_dir == (project / "data/cache/moondream").as_posix()


def test_moondream_cache_path_prefers_explicit_root_over_ambient_root(
    tmp_path,
    monkeypatch,
):
    ambient = tmp_path / "ambient"
    selected = tmp_path / "selected"
    ambient.mkdir()
    selected.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", ambient.as_posix())
    config = SimpleNamespace(cache_dir="data/cache/moondream")

    _bind_plugin_config_paths(config, root=selected)

    assert config.cache_dir == (
        selected / "data/cache/moondream"
    ).as_posix()


def test_moondream_cache_path_rejects_outer_whitespace(tmp_path, monkeypatch):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())

    with pytest.raises(ValueError, match="surrounding whitespace"):
        _bind_plugin_config_paths(SimpleNamespace(cache_dir=" data/cache/moondream"))


def test_moondream_config_fallback_uses_project_data_not_plugin_source(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    def _not_bound():
        raise RuntimeError("plugin root not set")

    path = _moondream_config_path(
        SimpleNamespace(default_config_path=lambda root: root / "config.json"),
        SimpleNamespace(plugin_config_path=_not_bound),
    )

    assert path == (
        project / "data" / "plugins" / MOONDREAM_PLUGIN_ID / "config.json"
    )


def test_moondream_config_fallback_prefers_explicit_root(
    tmp_path,
    monkeypatch,
):
    ambient = tmp_path / "ambient"
    selected = tmp_path / "selected"
    ambient.mkdir()
    selected.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", ambient.as_posix())

    def not_bound():
        raise RuntimeError("plugin root not set")

    path = _moondream_config_path(
        SimpleNamespace(default_config_path=lambda root: root / "config.json"),
        SimpleNamespace(plugin_config_path=not_bound),
        root=selected,
    )

    assert path == (
        selected
        / "data/plugins"
        / MOONDREAM_PLUGIN_ID
        / "config.json"
    )


def test_moondream_config_rejects_linked_leaf(tmp_path, monkeypatch):
    project = tmp_path / "project"
    plugin_root = project / "data" / "plugins" / MOONDREAM_PLUGIN_ID
    external = tmp_path / "external.json"
    plugin_root.mkdir(parents=True)
    external.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    try:
        (plugin_root / "config.json").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        _moondream_config_path(
            SimpleNamespace(default_config_path=lambda root: root / "config.json"),
            SimpleNamespace(
                plugin_config_path=lambda: plugin_root / "config.json",
            ),
        )
