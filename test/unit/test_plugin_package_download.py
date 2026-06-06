from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from core.plugins import package_download, registry_download
from core.plugins.package_download import (
    PluginPackageNonFallbackError,
    install_registry_package_under_plugins,
)
from core.plugins.registry_catalog import RegistryPluginRecord


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


def test_registry_package_install_verifies_checksum_size_and_extracts(tmp_path, monkeypatch):
    body = _zip_bytes({"demo-plugin/plugin.py": "class DemoPlugin: pass\n"})
    sha = hashlib.sha256(body).hexdigest()
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert timeout == 1
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

    def fail_move(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(package_download.shutil, "move", fail_move)

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
