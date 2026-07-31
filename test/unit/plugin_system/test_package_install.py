from __future__ import annotations

import hashlib
import io
import json
import socket
import uuid
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from plugin_system.install import package as package_download
from plugin_system.registry import download as registry_download
from plugin_system.install.package import (
    PluginPackageNetworkError,
    PluginPackageNonFallbackError,
    install_registry_package_under_plugins,
    registry_package_target,
)
from plugin_system.registry.catalog import RegistryPluginRecord


def _zip_bytes(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            body = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(name, body)
    return buf.getvalue()


def _record(
    *,
    name: str = "demo-plugin",
    url: str = "https://packages.example/demo.zip",
    sha256: str = "",
    size: int | None = None,
) -> RegistryPluginRecord:
    return RegistryPluginRecord(
        id=name,
        name=name,
        display_name="Demo Plugin",
        author="Tester",
        repo="owner/demo",
        description="",
        short_description="",
        entry="plugins.demo.plugin:DemoPlugin",
        package_url=url,
        package_sha256=sha256,
        package_size=size,
    )


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size: int = -1) -> bytes:
        if not self._body:
            return b""
        body = self._body
        self._body = b""
        return body


def test_private_package_cleanup_preserves_a_replacement_directory(tmp_path):
    private = tmp_path / "private"
    preserved = tmp_path / "preserved"
    private.mkdir()
    (private / "owned.txt").write_text("owned", encoding="utf-8")
    identity = private.lstat()
    private.rename(preserved)
    private.mkdir()
    replacement = private / "replacement.txt"
    replacement.write_text("replacement", encoding="utf-8")

    package_download._cleanup_private_tree(
        private,
        expected_identity=identity,
    )

    assert replacement.read_text(encoding="utf-8") == "replacement"
    assert (preserved / "owned.txt").read_text(encoding="utf-8") == "owned"


def test_registry_package_install_verifies_checksum_size_and_extracts(tmp_path, monkeypatch):
    body = _zip_bytes({"demo-plugin/plugin.py": "class DemoPlugin: pass\n"})
    sha = hashlib.sha256(body).hexdigest()
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert timeout == 1
        request_id = request.get_header("X-shinsekai-download-id")
        assert request_id is not None
        uuid.UUID(request_id)
        return _FakeResponse(body)

    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", fake_urlopen)

    target = install_registry_package_under_plugins(
        _record(sha256=sha, size=len(body)),
        plugins_parent=tmp_path,
        timeout_sec=1,
    )

    assert target == (tmp_path / "demo-plugin").resolve(strict=False)
    assert (target / "plugin.py").read_text(encoding="utf-8") == "class DemoPlugin: pass\n"
    assert calls == ["https://packages.example/demo.zip"]


@pytest.mark.parametrize(
    ("sha_override", "size_override", "message"),
    [
        ("0" * 64, None, "checksum mismatch"),
        (None, 1, "size mismatch"),
    ],
)
def test_registry_package_install_rejects_checksum_or_size_mismatch(
    tmp_path,
    monkeypatch,
    sha_override,
    size_override,
    message,
):
    body = _zip_bytes({"demo-plugin/plugin.py": "class DemoPlugin: pass\n"})
    sha = hashlib.sha256(body).hexdigest()
    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", lambda *_args, **_kwargs: _FakeResponse(body))

    with pytest.raises(PluginPackageNonFallbackError, match=message):
        install_registry_package_under_plugins(
            _record(
                sha256=sha_override if sha_override is not None else sha,
                size=size_override if size_override is not None else len(body),
            ),
            plugins_parent=tmp_path,
        )

    assert not (tmp_path / "demo-plugin").exists()


def test_registry_package_install_rejects_zip_slip_members(tmp_path, monkeypatch):
    body = _zip_bytes({"../escape.py": "bad\n"})
    sha = hashlib.sha256(body).hexdigest()
    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", lambda *_args, **_kwargs: _FakeResponse(body))

    with pytest.raises(PluginPackageNonFallbackError, match="unsafe plugin package path"):
        install_registry_package_under_plugins(
            _record(sha256=sha, size=len(body)),
            plugins_parent=tmp_path,
        )

    assert not (tmp_path / "escape.py").exists()
    assert not (tmp_path / "demo-plugin").exists()


def test_registry_package_install_rejects_hosts_outside_allowlist(tmp_path, monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("host validation should run before network access")

    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", fail_urlopen)

    with pytest.raises(PluginPackageNonFallbackError, match="host is not allowed"):
        install_registry_package_under_plugins(
            _record(url="https://evil.example/demo.zip", sha256="0" * 64, size=1),
            plugins_parent=tmp_path,
        )


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_registry_package_install_blocks_http_errors_from_github_fallback(tmp_path, monkeypatch, status):
    def fail_urlopen(request, *_args, **_kwargs):
        raise HTTPError(
            request.full_url,
            status,
            "explicit HTTP failure",
            hdrs=None,
            fp=io.BytesIO(b""),
        )

    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", fail_urlopen)

    with pytest.raises(PluginPackageNonFallbackError, match=f"HTTP error: {status}"):
        install_registry_package_under_plugins(
            _record(sha256="0" * 64, size=1),
            plugins_parent=tmp_path,
        )


@pytest.mark.parametrize(
    "network_error",
    [
        URLError(socket.gaierror("getaddrinfo failed")),
        URLError(ConnectionRefusedError("connection refused")),
        URLError(ConnectionResetError("connection reset by peer")),
        TimeoutError("timed out"),
    ],
)
def test_registry_package_install_allows_github_fallback_for_transient_network_errors(
    tmp_path,
    monkeypatch,
    network_error,
):
    def fail_urlopen(*_args, **_kwargs):
        raise network_error

    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", fail_urlopen)

    with pytest.raises(PluginPackageNetworkError, match="download failed"):
        install_registry_package_under_plugins(
            _record(sha256="0" * 64, size=1),
            plugins_parent=tmp_path,
        )


def test_registry_package_install_skips_download_when_target_exists_without_overwrite(tmp_path, monkeypatch):
    target = tmp_path / "demo-plugin"
    target.mkdir()
    (target / "plugin.py").write_text("old\n", encoding="utf-8")

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("existing plugin should not be downloaded without overwrite")

    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", fail_urlopen)

    result = install_registry_package_under_plugins(
        _record(sha256="0" * 64, size=1),
        plugins_parent=tmp_path,
        overwrite=False,
    )

    assert result == target.resolve(strict=False)
    assert (target / "plugin.py").read_text(encoding="utf-8") == "old\n"


def test_registry_package_no_overwrite_rechecks_target_after_download(tmp_path, monkeypatch):
    body = _zip_bytes({"demo-plugin/plugin.py": "stale downloader\n"})
    sha = hashlib.sha256(body).hexdigest()
    target = tmp_path / "demo-plugin"

    def publish_peer_then_respond(*_args, **_kwargs):
        target.mkdir()
        (target / "plugin.py").write_text("peer install\n", encoding="utf-8")
        return _FakeResponse(body)

    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", publish_peer_then_respond)

    result = install_registry_package_under_plugins(
        _record(sha256=sha, size=len(body)),
        plugins_parent=tmp_path,
        overwrite=False,
    )

    assert result == target.resolve(strict=False)
    assert (target / "plugin.py").read_text(encoding="utf-8") == "peer install\n"
    assert not list(tmp_path.glob(".demo-plugin.backup-*"))


def test_registry_package_install_rolls_back_old_directory_when_overwrite_replace_fails(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "demo-plugin"
    target.mkdir()
    (target / "plugin.py").write_text("old\n", encoding="utf-8")
    body = _zip_bytes({"demo-plugin/plugin.py": "new\n"})
    sha = hashlib.sha256(body).hexdigest()

    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")
    monkeypatch.setattr(package_download, "urlopen", lambda *_args, **_kwargs: _FakeResponse(body))

    def fail_publish(_source, _target, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(
        package_download,
        "replace_directory_transactionally",
        fail_publish,
    )

    with pytest.raises(OSError, match="simulated replace failure"):
        install_registry_package_under_plugins(
            _record(sha256=sha, size=len(body)),
            plugins_parent=tmp_path,
            overwrite=True,
        )

    assert target.is_dir()
    assert (target / "plugin.py").read_text(encoding="utf-8") == "old\n"
    assert not any(path.name.startswith(".demo-plugin.backup-") for path in tmp_path.iterdir())


def test_registry_download_persists_and_reads_install_metadata(tmp_path, monkeypatch):
    state_path = tmp_path / "downloads.json"
    monkeypatch.setattr(registry_download, "_DOWNLOAD_STATE_PATH", state_path)

    registry_download.mark_repo_downloaded(
        "https://github.com/Owner/Demo",
        manifest_entry="demo.plugin:DemoPlugin",
        install_metadata={
            "dependencyDetail": "ok",
            "dependencyStatus": "pip_ok",
            "entry": "plugins.demo.plugin:DemoPlugin",
            "ignored": "not persisted",
            "packageSha256": "abc123",
            "packageSize": 42,
            "packageSource": "r2",
            "packageStatus": "installed",
            "packageUrl": "https://packages.example/demo.zip",
            "repo": "owner/demo",
            "sourceType": "registry_package",
            "tagName": "",
        },
    )

    assert registry_download.load_plugin_install_metadata("demo.plugin:DemoPlugin") == {
        "dependencyDetail": "ok",
        "dependencyStatus": "pip_ok",
        "entry": "plugins.demo.plugin:DemoPlugin",
        "packageSha256": "abc123",
        "packageSize": 42,
        "packageSource": "r2",
        "packageStatus": "installed",
        "packageUrl": "https://packages.example/demo.zip",
        "repo": "owner/demo",
        "sourceType": "registry_package",
    }
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert raw["repos"] == ["owner/demo"]
    assert "plugins.demo.plugin:DemoPlugin" in raw["entry_install"]

    assert registry_download.load_plugin_install_metadata(
        " demo.plugin:DemoPlugin"
    ) == {}
    with pytest.raises(ValueError, match="exact portable"):
        registry_download.mark_repo_downloaded(
            "owner/other",
            manifest_entry=" demo.plugin:DemoPlugin",
        )


def test_registry_download_state_uses_project_root_when_cwd_changes(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project_root.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project_root.as_posix())
    monkeypatch.chdir(unrelated)

    registry_download.mark_repo_downloaded("owner/demo")

    state_path = project_root / "data" / "config" / "plugin_registry_downloads.json"
    assert state_path.is_file()
    assert not (unrelated / "data").exists()


def test_registry_download_state_prefers_explicit_root_over_ambient_root(
    tmp_path,
    monkeypatch,
):
    ambient = tmp_path / "ambient"
    selected = tmp_path / "selected"
    ambient.mkdir()
    selected.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", ambient.as_posix())

    registry_download.mark_repo_downloaded(
        "owner/demo",
        manifest_entry="plugins.demo:Plugin",
        root=selected,
    )

    assert registry_download.load_downloaded_repos(root=selected) == {
        "owner/demo"
    }
    assert (
        selected / "data/config/plugin_registry_downloads.json"
    ).is_file()
    assert not (
        ambient / "data/config/plugin_registry_downloads.json"
    ).exists()


def test_registry_package_default_target_uses_project_root_not_cwd(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)

    target = registry_package_target(_record())

    assert target == project / "plugins/demo-plugin"


def test_registry_package_explicit_parent_must_be_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        registry_package_target(_record(), plugins_parent=Path("relative-plugins"))


def test_registry_package_explicit_parent_does_not_expand_user_home_alias():
    with pytest.raises(ValueError, match="absolute"):
        registry_package_target(_record(), plugins_parent=Path("~/plugins"))


def test_registry_package_rejects_symlink_parent(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "plugins"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(PermissionError, match="symbolic link"):
        registry_package_target(_record(), plugins_parent=linked)


def test_registry_package_rejects_intermediate_alias_inside_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    alias = project / "alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        registry_package_target(
            _record(),
            plugins_parent=alias / "plugins",
        )


def test_registry_package_rejects_intermediate_alias_outside_project(tmp_path):
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(PermissionError, match="symbolic link"):
        registry_package_target(
            _record(),
            plugins_parent=alias / "plugins",
        )


def test_registry_package_replace_rejects_existing_file_without_touching_it(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "plugin.py").write_text("new", encoding="utf-8")
    target = tmp_path / "plugins/demo-plugin"
    target.parent.mkdir()
    target.write_text("keep", encoding="utf-8")

    with pytest.raises(PluginPackageNonFallbackError, match="not a directory"):
        package_download._replace_directory(extracted, target)

    assert target.read_text(encoding="utf-8") == "keep"
    assert (extracted / "plugin.py").is_file()


def test_registry_package_target_uses_portable_windows_device_name_on_all_platforms(tmp_path):
    target = registry_package_target(_record(name="CON"), plugins_parent=tmp_path)

    assert target.name == "CON_plugin"


def test_registry_package_target_rejects_case_only_portable_collision(tmp_path):
    (tmp_path / "Demo-Plugin").mkdir()

    with pytest.raises(PluginPackageNonFallbackError, match="portable filesystem") as error:
        registry_package_target(_record(name="demo-plugin"), plugins_parent=tmp_path)

    assert error.value.code == "package_name_collision"


def test_source_plugin_target_rejects_unicode_normalization_collision(tmp_path):
    (tmp_path / "Caf\N{LATIN SMALL LETTER E WITH ACUTE}").mkdir()

    with pytest.raises(FileExistsError, match="portable filesystem"):
        registry_download.portable_plugin_target(tmp_path, "Cafe\N{COMBINING ACUTE ACCENT}")


def test_registry_package_install_rejects_symlink_target_without_touching_external_data(
    tmp_path,
    monkeypatch,
):
    plugins = tmp_path / "plugins"
    external = tmp_path / "external"
    plugins.mkdir()
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        (plugins / "demo-plugin").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "packages.example")

    with pytest.raises(PermissionError, match="symbolic link"):
        install_registry_package_under_plugins(
            _record(sha256="0" * 64, size=1),
            plugins_parent=plugins,
            overwrite=True,
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_github_source_download_extracts_through_staging_directory(tmp_path, monkeypatch):
    body = _zip_bytes({"demo-main/plugin.py": "plugin"})
    plugins = tmp_path / "plugins"
    monkeypatch.setattr(registry_download, "urlopen", lambda *_args, **_kwargs: _FakeResponse(body))

    target = registry_download.download_github_repo_sources(
        "owner/demo",
        plugins_parent=plugins,
        folder_name="Demo",
    )

    assert target == (plugins / "Demo").resolve()
    assert (target / "plugin.py").read_text(encoding="utf-8") == "plugin"
    assert not list(plugins.glob(".Demo.install-*"))


def test_github_source_download_rejects_parent_lexical_alias_before_network(
    tmp_path,
    monkeypatch,
):
    called = False

    def fail_network(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not run")

    monkeypatch.setattr(registry_download, "urlopen", fail_network)

    with pytest.raises(ValueError, match="lexical path aliases"):
        registry_download.download_github_repo_sources(
            "owner/demo",
            plugins_parent=f"{tmp_path.as_posix()}/./plugins",
            folder_name="Demo",
        )

    assert called is False


def test_github_source_download_rejects_user_home_parent_before_network(monkeypatch):
    called = False

    def fail_network(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not run")

    monkeypatch.setattr(registry_download, "urlopen", fail_network)

    with pytest.raises(ValueError, match="absolute"):
        registry_download.download_github_repo_sources(
            "owner/demo",
            plugins_parent="~/plugins",
            folder_name="Demo",
        )

    assert called is False


def test_github_source_download_rejects_backslash_traversal_before_publish(tmp_path, monkeypatch):
    body = _zip_bytes(
        {
            "demo-main/plugin.py": "plugin",
            r"demo-main\..\outside.py": "bad",
        }
    )
    plugins = tmp_path / "plugins"
    monkeypatch.setattr(registry_download, "urlopen", lambda *_args, **_kwargs: _FakeResponse(body))

    with pytest.raises(ValueError, match="archive"):
        registry_download.download_github_repo_sources(
            "owner/demo",
            plugins_parent=plugins,
            folder_name="Demo",
        )

    assert not (plugins / "Demo").exists()
    assert not (tmp_path / "outside.py").exists()
