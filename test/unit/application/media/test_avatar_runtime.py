import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.media.avatar_runtime import AvatarRuntimeService
from core.media.asset_import import PendingAssetBatch


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    files = {"core.js": b"Core", "sdk.js": b"Framework", "LICENSE.md": b"license"}
    installer = SimpleNamespace(version="test-1", download_url="https://example.com/sdk", license_urls=["https://example.com/license"],
                                filenames=tuple(files), prepare=Mock(return_value={"sources": {}}), files=Mock(return_value=files))
    monkeypatch.setattr("application.media.avatar_runtime.adapter_for", lambda _: SimpleNamespace(runtime_installer=installer))
    source = tmp_path / "sdk.zip"
    source.write_bytes(b"fixture")
    body = {"source_path": str(source), "accepted_license": True, "compiled": "compiled"}
    service = AvatarRuntimeService(tmp_path)
    return service, installer, body, tmp_path / "data/runtime/avatars/demo"


def test_installs_atomically_outside_frontend_dist_and_serves_allowlist(runtime):
    service, installer, body, root = runtime
    assert not service.status("demo")["installed"]
    assert service.prepare("demo", body) == {"sources": {}}
    assert service.install("demo", body)["installed"]
    for name in installer.filenames:
        assert service.file("demo", name).read_bytes() == installer.files.return_value[name]
    assert not list(root.glob(".batch-*/.pending-import"))
    with pytest.raises(PermissionError):
        service.file("demo", "../current.json")
    with pytest.raises(PermissionError):
        service.file("demo", "current.json")


def test_requires_explicit_license_acceptance(runtime):
    service, installer, body, root = runtime
    for value in (False, "true", None):
        with pytest.raises(ValueError, match="accept"):
            service.prepare("demo", {**body, "accepted_license": value})
        with pytest.raises(ValueError, match="accept"):
            service.install("demo", {**body, "accepted_license": value})
    installer.prepare.assert_not_called()
    installer.files.assert_not_called()
    assert not root.exists()


def test_configuration_publication_failure_rolls_back_files(runtime, monkeypatch):
    service, _, body, root = runtime
    monkeypatch.setattr("application.media.avatar_runtime.os.replace", Mock(side_effect=PermissionError("read only")))
    with pytest.raises(PermissionError):
        service.install("demo", body)
    assert not service.status("demo")["installed"]
    assert not list(root.glob(".batch-*"))
    assert not list(root.glob(".current-*"))


def test_recovers_interrupted_install_but_preserves_published_batch(runtime):
    service, _, body, root = runtime
    with pytest.raises(KeyboardInterrupt):
        with PendingAssetBatch(root) as batch:
            (batch.path / "sdk.js").write_bytes(b"partial")
            orphan = batch.path
            raise KeyboardInterrupt()
    assert orphan.exists()
    assert not service.status("demo")["installed"]
    assert not orphan.exists()
    service.install("demo", body)
    manifest = json.loads((root / "current.json").read_text())
    published = root / manifest["batch"]
    (published / ".pending-import").write_text("interrupted after publication")
    assert service.status("demo")["installed"]
    assert published.exists()
    assert not (published / ".pending-import").exists()


def test_idempotent_import_and_integrity_check(runtime):
    service, _, body, root = runtime
    service.install("demo", body)
    before = (root / "current.json").read_bytes()
    service.install("demo", body)
    assert (root / "current.json").read_bytes() == before
    service.file("demo", "sdk.js").write_bytes(b"tampered")
    assert not service.status("demo")["installed"]
    with pytest.raises(ValueError, match="integrity"):
        service.file("demo", "sdk.js")


def test_unsupported_format_and_invalid_ids(runtime, monkeypatch):
    service, _, _, _ = runtime
    for value in ("../l2d", "L2D", "", "l2d/path"):
        with pytest.raises(ValueError, match="Invalid avatar format"):
            service.status(value)
    monkeypatch.setattr("application.media.avatar_runtime.adapter_for", lambda _: SimpleNamespace(runtime_installer=None))
    with pytest.raises(ValueError, match="does not require"):
        service.status("mmd")
