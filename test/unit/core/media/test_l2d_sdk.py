import hashlib
import zipfile

import pytest

from core.media.avatar import l2d_sdk


@pytest.fixture
def archive(tmp_path, monkeypatch):
    path = tmp_path / "sdk.zip"
    entries = {
        "Core/live2dcubismcore.min.js": b"// test Core",
        "Core/LICENSE.md": b"Core license",
        "Framework/LICENSE.md": b"Framework license",
        "Framework/src/live2dcubismframework.ts": b"export const test = 1;",
        "Samples/Resources/Haru/Haru.moc3": b"sample must not be installed",
    }
    with zipfile.ZipFile(path, "w") as handle:
        for name, content in entries.items():
            handle.writestr(l2d_sdk.SDK_ROOT + name, content)
    monkeypatch.setattr(l2d_sdk, "SDK_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(l2d_sdk, "COMPILED_SHA256", hashlib.sha256(b"test compiled bridge").hexdigest())
    return path


def test_prepare_and_install_only_the_approved_runtime(archive):
    installer = l2d_sdk.Live2DRuntimeInstaller()
    assert installer.prepare(archive) == {"sources": {"Framework/src/live2dcubismframework.ts": "export const test = 1;"}}
    files = installer.files(archive, "test compiled bridge")
    assert set(files) == set(installer.filenames)
    assert files["cubism-core-LICENSE.md"] == b"Core license"
    assert not any("Haru" in name for name in files)


def test_rejects_modified_archive(archive):
    with archive.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="unmodified official"):
        l2d_sdk.Live2DRuntimeInstaller().prepare(archive)


@pytest.mark.parametrize("compiled", [None, "alert('untrusted')", "x" * (l2d_sdk.MAX_INPUT_BYTES + 1)], ids=["null", "untrusted", "oversized"])
def test_rejects_untrusted_compiler_output(archive, compiled):
    with pytest.raises(ValueError):
        l2d_sdk.Live2DRuntimeInstaller().files(archive, compiled)


@pytest.mark.parametrize("name", ["../escape.ts", "/escape.ts", "Framework\\evil.ts"])
def test_rejects_unsafe_zip_paths_even_if_hash_accepted(archive, monkeypatch, name):
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr(name.replace("\\", "/"), b"test")
    if "\\" in name:
        # ZipInfo normalizes os.sep on Windows when constructing a fixture;
        # preserve the actual archive spelling in both ZIP headers instead.
        archive.write_bytes(archive.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
    monkeypatch.setattr(l2d_sdk, "SDK_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="Unsafe"):
        l2d_sdk.Live2DRuntimeInstaller().prepare(archive)


def test_rejects_directory_or_oversized_zip(tmp_path, monkeypatch):
    installer = l2d_sdk.Live2DRuntimeInstaller()
    with pytest.raises(ValueError):
        installer.prepare(tmp_path)
    archive = tmp_path / "large.zip"
    archive.write_bytes(b"too large")
    monkeypatch.setattr(l2d_sdk, "MAX_ARCHIVE_BYTES", 4)
    with pytest.raises(ValueError, match="exceeds"):
        installer.prepare(archive)
