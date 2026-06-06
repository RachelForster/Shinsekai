from pathlib import Path
from types import SimpleNamespace

import pytest

from core.plugins.package_download import PluginPackageNetworkError, PluginPackageNonFallbackError
from core.plugins.registry_catalog import RegistryPluginRecord
from frontend_bridge_core import plugin_updates
from frontend_bridge_core.plugin_updates import (
    _infer_plugin_entry,
    _install_plugin_source,
    _is_repo_source,
    _lookup_registry_plugin,
    _plugin_class_from_file,
    _repo_slug_from_source,
    _synthetic_plugin_result,
)
from frontend_bridge_core.state import BridgeState


def test_repo_slug_from_source_accepts_common_github_forms():
    assert _repo_slug_from_source("owner/repo") == "owner/repo"
    assert _repo_slug_from_source("https://github.com/owner/repo.git") == "owner/repo"
    assert _repo_slug_from_source("github.com/owner/repo/tree/main") == "owner/repo"
    assert _repo_slug_from_source("git@github.com:owner/repo.git") == "owner/repo"
    assert _repo_slug_from_source("http://github.com/owner/repo/tree/main?x=1#readme") == "owner/repo"
    assert _repo_slug_from_source("owner") == ""


def test_repo_source_rejects_manifest_entries():
    assert _is_repo_source("owner/repo") is True
    assert _is_repo_source("https://github.com/owner/repo.git") is True
    assert _is_repo_source("git@github.com:owner/repo.git") is True
    assert _is_repo_source("plugins.demo.plugin:DemoPlugin") is False
    assert _is_repo_source("not-enough") is False


def test_plugin_class_from_file_detects_pluginbase_subclasses(tmp_path):
    plugin_py = tmp_path / "plugin.py"
    plugin_py.write_text(
        "\n".join(
            [
                "class Helper:",
                "    pass",
                "class DemoPlugin(PluginBase):",
                "    pass",
            ]
        ),
        encoding="utf-8",
    )

    assert _plugin_class_from_file(plugin_py) == "DemoPlugin"

    plugin_py.write_text("class Broken(:\n", encoding="utf-8")
    assert _plugin_class_from_file(plugin_py) == ""


def test_infer_plugin_entry_uses_top_level_or_nested_plugin_file(tmp_path):
    plugin_root = tmp_path / "demo_plugin"
    plugin_root.mkdir()
    (plugin_root / "plugin.py").write_text("class DemoPlugin(PluginBase):\n    pass\n", encoding="utf-8")

    assert _infer_plugin_entry(plugin_root) == "plugins.demo_plugin.plugin:DemoPlugin"

    nested_root = tmp_path / "nested_plugin"
    nested = nested_root / "package"
    nested.mkdir(parents=True)
    (nested / "plugin.py").write_text("class NestedPlugin(shin.PluginBase):\n    pass\n", encoding="utf-8")

    assert _infer_plugin_entry(nested_root) == "plugins.nested_plugin.package.plugin:NestedPlugin"


def test_synthetic_plugin_result_uses_safe_defaults():
    assert _synthetic_plugin_result(
        description="Downloaded but not enabled",
        enabled=False,
        plugin_id="plugins.demo.plugin:Demo",
        title="Demo",
        version="1.0",
    ) == {
        "author": "",
        "description": "Downloaded but not enabled",
        "directory": "",
        "enabled": False,
        "entry": "plugins.demo.plugin:Demo",
        "id": "plugins.demo.plugin:Demo",
        "loadError": "",
        "loaded": False,
        "permissions": [],
        "settingsPages": [],
        "slots": ["settings-extension"],
        "title": "Demo",
        "toolsTabs": [],
        "version": "1.0",
    }


def test_infer_plugin_entry_ignores_non_identifier_module_parts(tmp_path):
    plugin_root = tmp_path / "bad-name"
    plugin_root.mkdir()
    (plugin_root / "plugin.py").write_text("class DemoPlugin(PluginBase):\n    pass\n", encoding="utf-8")

    assert _infer_plugin_entry(plugin_root) == ""


def _registry_record(
    *,
    package_url: str = "https://packages.example/demo.zip",
    entry: str = "plugins.demo.plugin:DemoPlugin",
) -> RegistryPluginRecord:
    return RegistryPluginRecord(
        id="demo-id",
        name="demo-plugin",
        display_name="Demo Plugin",
        author="Tester",
        repo="owner/demo",
        description="Long detail",
        short_description="Short detail",
        entry=entry,
        package_source="r2",
        package_url=package_url,
        package_sha256="abc123",
        package_size=42,
    )


def _state_with_task() -> BridgeState:
    state = BridgeState(None, None, None, None)
    state.tasks["task"] = {
        "id": "task",
        "logs": [],
        "message": "",
        "phase": "queued",
        "progress": 0,
        "status": "running",
    }
    return state


def _plugin_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "plugin.py").write_text("class DemoPlugin(PluginBase):\n    pass\n", encoding="utf-8")
    return root


def _patch_manifest_and_state(monkeypatch, marks: list[dict]):
    monkeypatch.setattr(
        plugin_updates,
        "_plugin_result_from_manifest",
        lambda entry: {"entry": entry, "enabled": True},
    )

    def fake_mark_repo_downloaded(repo, **kwargs):
        marks.append({"repo": repo, **kwargs})

    monkeypatch.setattr("core.plugins.registry_download.mark_repo_downloaded", fake_mark_repo_downloaded)


def test_lookup_registry_plugin_matches_id_and_display_name(monkeypatch):
    record = _registry_record()
    monkeypatch.setattr("core.plugins.registry_catalog.fetch_registry_plugins", lambda timeout_sec=12: [record])

    assert _lookup_registry_plugin("demo-id") is record
    assert _lookup_registry_plugin("Demo Plugin") is record


def test_install_plugin_source_prefers_registry_package_over_github(tmp_path, monkeypatch):
    record = _registry_record()
    marks: list[dict] = []
    calls: list[tuple[str, object]] = []
    package_root = _plugin_root(tmp_path, "package-plugin")

    monkeypatch.setattr(plugin_updates, "_lookup_registry_plugin", lambda _source: record)
    _patch_manifest_and_state(monkeypatch, marks)

    def fake_package_install(rec, **kwargs):
        calls.append(("package", kwargs.get("overwrite")))
        assert rec is record
        assert kwargs.get("plugins_parent") == Path("plugins")
        return package_root

    def fail_github(*_args, **_kwargs):
        raise AssertionError("registry package should be used before GitHub")

    monkeypatch.setattr(
        "core.plugins.package_download.install_registry_package_under_plugins",
        fake_package_install,
    )
    monkeypatch.setattr("core.plugins.github_bundle_update.install_github_plugin_under_plugins", fail_github)
    monkeypatch.setattr(
        "core.plugins.plugin_requirements_install.install_plugin_requirements_txt",
        lambda root, **_kwargs: calls.append(("pip", root)) or ("pip_ok", ""),
    )

    result = _install_plugin_source(_state_with_task(), "task", "owner/demo", overwrite=True)

    assert result["entry"] == "plugins.demo.plugin:DemoPlugin"
    assert result["enabled"] is True
    assert result["install"] == {
        "dependencyStatus": "pip_ok",
        "entry": "plugins.demo.plugin:DemoPlugin",
        "packageSha256": "abc123",
        "packageSize": 42,
        "packageSource": "r2",
        "packageStatus": "verified",
        "packageUrl": "https://packages.example/demo.zip",
        "repo": "owner/demo",
        "sourceLabel": "官方包体 (R2)",
        "sourceType": "package",
    }
    assert calls == [("package", True), ("pip", package_root)]
    assert marks
    assert marks[0]["repo"] == "owner/demo"
    assert marks[0]["manifest_entry"] == "plugins.demo.plugin:DemoPlugin"
    assert marks[0]["install_metadata"] == result["install"]


def test_install_plugin_source_does_not_mark_existing_directory_as_verified(tmp_path, monkeypatch):
    record = _registry_record()
    marks: list[dict] = []
    calls: list[tuple[str, object]] = []
    package_root = _plugin_root(tmp_path, "package-plugin")

    monkeypatch.setattr(plugin_updates, "_lookup_registry_plugin", lambda _source: record)
    monkeypatch.setattr("core.plugins.package_download.registry_package_target", lambda *_args, **_kwargs: package_root)
    _patch_manifest_and_state(monkeypatch, marks)

    def fake_package_install(rec, **kwargs):
        calls.append(("package", kwargs.get("overwrite")))
        assert rec is record
        return package_root

    monkeypatch.setattr(
        "core.plugins.package_download.install_registry_package_under_plugins",
        fake_package_install,
    )
    monkeypatch.setattr(
        "core.plugins.plugin_requirements_install.install_plugin_requirements_txt",
        lambda root, **_kwargs: calls.append(("pip", root)) or ("pip_ok", ""),
    )

    result = _install_plugin_source(_state_with_task(), "task", "owner/demo", overwrite=False)

    assert result["install"] == {
        "dependencyStatus": "pip_ok",
        "entry": "plugins.demo.plugin:DemoPlugin",
        "packageSource": "local",
        "packageStatus": "existing",
        "repo": "owner/demo",
        "sourceLabel": "Existing plugin directory",
        "sourceType": "existing",
    }
    assert calls == [("package", False), ("pip", package_root)]
    assert marks[0]["install_metadata"] == result["install"]


def test_install_plugin_source_falls_back_to_github_for_registry_package_network_error(
    tmp_path,
    monkeypatch,
):
    record = _registry_record()
    marks: list[dict] = []
    calls: list[str] = []
    github_root = _plugin_root(tmp_path, "github-plugin")

    monkeypatch.setattr(plugin_updates, "_lookup_registry_plugin", lambda _source: record)
    _patch_manifest_and_state(monkeypatch, marks)

    def fail_package(*_args, **_kwargs):
        calls.append("package")
        raise PluginPackageNetworkError("r2 offline")

    def fake_github(repo, **kwargs):
        calls.append("github")
        assert repo == "owner/demo"
        assert kwargs.get("catalog_display_name") == "demo-plugin"
        return github_root

    monkeypatch.setattr(
        "core.plugins.package_download.install_registry_package_under_plugins",
        fail_package,
    )
    monkeypatch.setattr("core.plugins.github_bundle_update.install_github_plugin_under_plugins", fake_github)
    monkeypatch.setattr(
        "core.plugins.plugin_requirements_install.install_plugin_requirements_txt",
        lambda *_args, **_kwargs: ("pip_ok", ""),
    )

    state = _state_with_task()

    result = _install_plugin_source(state, "task", "owner/demo")

    assert result == {"entry": "plugins.demo.plugin:DemoPlugin", "enabled": True}
    assert calls == ["package", "github"]
    assert marks[0]["manifest_entry"] == "plugins.demo.plugin:DemoPlugin"
    assert any("官方包体暂时无法访问，正在自动尝试 GitHub 源码安装。" in line for line in state.tasks["task"]["logs"])


@pytest.mark.parametrize(
    ("package_error", "expected_code", "expected_message"),
    [
        (
            PluginPackageNonFallbackError(
                "checksum mismatch",
                code="package_checksum_mismatch",
                user_message="包体校验未通过，已阻止安装。",
            ),
            "package_checksum_mismatch",
            "包体校验未通过，已阻止安装。",
        ),
        (
            PluginPackageNonFallbackError(
                "unsafe plugin package path",
                code="package_unsafe_path",
                user_message="包体校验未通过，已阻止安装。",
            ),
            "package_unsafe_path",
            "包体校验未通过，已阻止安装。",
        ),
    ],
)
def test_install_plugin_source_does_not_fallback_to_github_for_package_safety_errors(
    monkeypatch,
    package_error,
    expected_code,
    expected_message,
):
    record = _registry_record()
    monkeypatch.setattr(plugin_updates, "_lookup_registry_plugin", lambda _source: record)

    def fail_package(*_args, **_kwargs):
        raise package_error

    def fail_github(*_args, **_kwargs):
        raise AssertionError("checksum and package safety errors must not fallback to GitHub")

    monkeypatch.setattr(
        "core.plugins.package_download.install_registry_package_under_plugins",
        fail_package,
    )
    monkeypatch.setattr("core.plugins.github_bundle_update.install_github_plugin_under_plugins", fail_github)

    state = _state_with_task()

    with pytest.raises(Exception, match=expected_message):
        _install_plugin_source(state, "task", "owner/demo")

    task = state.tasks["task"]
    assert task["errorCode"] == expected_code
    assert task["errorUserMessage"] == expected_message
    assert task["fallbackAllowed"] is False
    assert str(package_error) in task["errorDetail"]


def test_install_plugin_source_does_not_fallback_to_github_when_package_dependency_install_fails(
    tmp_path,
    monkeypatch,
):
    record = _registry_record()
    package_root = _plugin_root(tmp_path, "package-plugin")
    monkeypatch.setattr(plugin_updates, "_lookup_registry_plugin", lambda _source: record)
    monkeypatch.setattr(
        "core.plugins.package_download.install_registry_package_under_plugins",
        lambda *_args, **_kwargs: package_root,
    )

    def fail_github(*_args, **_kwargs):
        raise AssertionError("dependency failures after package install must not fallback to GitHub")

    monkeypatch.setattr("core.plugins.github_bundle_update.install_github_plugin_under_plugins", fail_github)
    monkeypatch.setattr(
        "core.plugins.plugin_requirements_install.install_plugin_requirements_txt",
        lambda *_args, **_kwargs: ("pip_failed", "dependency boom"),
    )

    state = _state_with_task()

    with pytest.raises(RuntimeError, match="包体已通过校验，但依赖安装失败，请查看日志。"):
        _install_plugin_source(state, "task", "owner/demo")

    task = state.tasks["task"]
    assert task["errorCode"] == "package_dependency_failed"
    assert task["errorUserMessage"] == "包体已通过校验，但依赖安装失败，请查看日志。"
    assert task["errorDetail"] == "dependency boom"
    assert task["fallbackAllowed"] is False


def test_install_plugin_source_treats_github_dependency_conflicts_as_failures(
    tmp_path,
    monkeypatch,
):
    record = _registry_record(package_url="")
    github_root = _plugin_root(tmp_path, "github-plugin")
    monkeypatch.setattr(plugin_updates, "_lookup_registry_plugin", lambda _source: record)
    monkeypatch.setattr(
        "core.plugins.github_bundle_update.install_github_plugin_under_plugins",
        lambda *_args, **_kwargs: github_root,
    )
    monkeypatch.setattr(
        "core.plugins.plugin_requirements_install.install_plugin_requirements_txt",
        lambda *_args, **_kwargs: ("pip_conflict", "dependency conflict"),
    )

    with pytest.raises(RuntimeError, match="dependency conflict"):
        _install_plugin_source(_state_with_task(), "task", "owner/demo")
