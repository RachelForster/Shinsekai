import io
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

import core.agent.pi_runtime as module
from core.downloads import DownloadInterrupted


@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Windows", "AMD64", "windows-x64"),
        ("Windows", "ARM64", "windows-arm64"),
        ("Darwin", "aarch64", "darwin-arm64"),
        ("Linux", "x86_64", "linux-x64"),
    ],
)
def test_platform_selection(system, machine, expected):
    assert module.pi_platform(system, machine) == expected


def test_unsupported_platform_has_no_guess():
    with pytest.raises(ValueError):
        module.pi_platform("Windows", "i386")


def installer(monkeypatch, tmp_path, entries=None):
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        for name, body in (
            entries
            or {"pi/pi.exe": b"official test fixture", "pi/README.md": b"readme"}
        ).items():
            archive.writestr(name, body)
    digest = module.file_digest(source)
    monkeypatch.setitem(
        module.PI_ARCHIVES, "windows-x64", ("pi-windows-x64.zip", digest)
    )
    calls = []

    def download(url, target, headers, **kwargs):
        assert kwargs["expected_sha256"] == digest
        assert url.startswith(module.PI_RELEASE)
        calls.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    monkeypatch.setattr(module, "download_archive", download)
    return (
        module.PiRuntimeManager(tmp_path / "runtimes", platform_key="windows-x64"),
        calls,
    )


def test_cache_and_corruption_repair_reuse_verified_archive(monkeypatch, tmp_path):
    manager, calls = installer(monkeypatch, tmp_path)
    runtime = manager.ensure()
    assert runtime.executable.read_bytes() == b"official test fixture"
    assert manager.ensure() == runtime
    (runtime.executable.parent / "README.md").write_bytes(b"broken")
    assert manager.inspect() is None
    assert manager.ensure().executable == runtime.executable
    assert len(calls) == 1
    assert not list(manager.root.glob("install-*"))


@pytest.mark.parametrize(
    "entries",
    [
        {"../outside": b"escape", "pi.exe": b"pi"},
        {"one/pi.exe": b"pi", "two/pi.exe": b"pi"},
    ],
)
def test_bad_archive_never_becomes_installed(monkeypatch, tmp_path, entries):
    manager, _ = installer(monkeypatch, tmp_path, entries)
    with pytest.raises(ValueError):
        manager.ensure()
    assert not manager.installed.exists()
    assert not (tmp_path / "outside").exists()
    assert not list(manager.root.glob("install-*"))


def test_cancelled_repair_preserves_previous_install(monkeypatch, tmp_path):
    manager, _ = installer(monkeypatch, tmp_path)
    runtime = manager.ensure()
    runtime.executable.write_bytes(b"previous contents")
    cancelled = False

    def update(**event):
        nonlocal cancelled
        if event["phase"] == "extract":
            cancelled = True

    with pytest.raises(DownloadInterrupted):
        manager.ensure(update_task=update, is_interrupted=lambda: cancelled)
    assert runtime.executable.read_bytes() == b"previous contents"


def test_tar_symlinks_are_rejected(tmp_path):
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        member = tarfile.TarInfo("pi")
        member.type = tarfile.SYMTYPE
        member.linkname = "../outside"
        target.addfile(member)
    root = tmp_path / "extract"
    root.mkdir()
    manager = module.PiRuntimeManager(tmp_path, platform_key="linux-x64")
    with pytest.raises(ValueError):
        manager._extract(archive, root, lambda: False)


def test_tar_retains_bundled_executable_modes(tmp_path):
    import os
    import stat

    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        member = tarfile.TarInfo("native/helper")
        member.mode = 0o755
        member.size = 4
        target.addfile(member, io.BytesIO(b"data"))
    root = tmp_path / "extract"
    root.mkdir()
    manager = module.PiRuntimeManager(tmp_path, platform_key="linux-x64")
    manager._extract(archive, root, lambda: False)
    helper = root / "native/helper"
    assert helper.read_bytes() == b"data"
    if os.name != "nt":
        assert helper.stat().st_mode & stat.S_IXUSR
