from io import StringIO, BytesIO
import base64
import hashlib
import json
import sys
from unittest.mock import Mock

from PIL import Image
import pytest

from core.media import toonout, toonout_assets, toonout_worker
from tools import remove_bg


def test_one_worker_per_job_preserves_alpha_and_closes_on_failure(monkeypatch):
    session = Mock(device="cuda")
    session.side_effect = [
        Image.new("RGBA", (12, 20), (1, 2, 3, 128)),
        RuntimeError("frame failed"),
    ]
    factory = Mock(return_value=session)
    fallback = Mock()
    monkeypatch.setattr(toonout, "ToonOutSession", factory)
    monkeypatch.setattr(remove_bg, "remove_background_image", fallback)
    with pytest.raises(RuntimeError, match="frame failed"):
        with remove_bg.background_remover(model="toonout") as remove:
            assert remove(Image.new("RGB", (12, 20))).getpixel((0, 0)) == (1, 2, 3, 128)
            assert remove.metadata() == {
                "model": "toonout",
                "requestedModel": "toonout",
                "device": "cuda",
            }
            remove(Image.new("RGB", (12, 20)))
    factory.assert_called_once()
    session.close.assert_called_once()
    fallback.assert_not_called()


def test_uninstalled_model_falls_back_once_and_reports_actual_model(monkeypatch):
    factory = Mock(side_effect=toonout.ToonOutUnavailable("not installed"))
    fallback = Mock(side_effect=lambda image, **_: image.convert("RGBA"))
    monkeypatch.setattr(toonout, "ToonOutSession", factory)
    monkeypatch.setattr(remove_bg, "remove_background_image", fallback)
    with remove_bg.background_remover(model="toonout", alpha_matting=True) as remove:
        for _ in range(2):
            remove(Image.new("RGB", (12, 20)))
        assert remove.metadata()["model"] == "isnet-anime"
        assert remove.metadata()["requestedModel"] == "toonout"
        assert remove.metadata()["fallbackReason"] == "toonout-unavailable"
    factory.assert_called_once()
    assert fallback.call_count == 2
    assert fallback.call_args.kwargs["alpha_matting"] is True


def test_selected_legacy_model_does_not_launch_torch_worker(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(toonout, "ToonOutSession", factory)
    monkeypatch.setattr(remove_bg, "remove_background_image", lambda image, **_: image)
    with remove_bg.background_remover(model="isnet-anime") as remove:
        remove(Image.new("RGBA", (12, 20)))
        assert "fallbackReason" not in remove.metadata()
    factory.assert_not_called()
    with pytest.raises(ValueError, match="抠图模型"):
        remove_bg.BackgroundRemover("unknown", False)


def test_worker_protocol_uses_configured_python_and_closes_pipes(tmp_path, monkeypatch):
    data = BytesIO()
    Image.new("RGBA", (12, 20), (5, 6, 7, 128)).save(data, "PNG")
    response = {"image": base64.b64encode(data.getvalue()).decode("ascii")}
    process = Mock(
        stdin=StringIO(),
        stdout=StringIO(
            json.dumps({"ready": True, "device": "cuda"})
            + "\n"
            + json.dumps(response)
            + "\n"
        ),
    )
    process.poll.return_value = None
    popen = Mock(return_value=process)
    (tmp_path / "runtime.json").write_text(json.dumps({"python": sys.executable}))
    monkeypatch.setattr(toonout, "model_directory", lambda: tmp_path)
    monkeypatch.setattr(toonout, "verify_assets", lambda _: None)
    monkeypatch.setattr(toonout.subprocess, "Popen", popen)
    worker = toonout.ToonOutSession()
    assert worker(Image.new("RGB", (12, 20))).getpixel((0, 0)) == (5, 6, 7, 128)
    assert popen.call_args.args[0][0] == sys.executable
    worker.close()
    assert process.stdin.closed and process.stdout.closed
    process.wait.assert_called_once_with(timeout=5)


def test_corrupt_artifact_blocks_worker_before_executing_code(tmp_path, monkeypatch):
    (tmp_path / "code.py").write_bytes(b"bad")
    monkeypatch.setattr(
        toonout_assets,
        "ARTIFACTS",
        {
            "code.py": (
                "repo/resolve/revision/code.py",
                hashlib.sha256(b"good").hexdigest(),
            )
        },
    )
    monkeypatch.setattr(toonout, "model_directory", lambda: tmp_path)
    popen = Mock()
    monkeypatch.setattr(toonout.subprocess, "Popen", popen)
    with pytest.raises(toonout.ToonOutUnavailable, match="校验失败"):
        toonout.ToonOutSession()
    popen.assert_not_called()


def test_setup_downloads_only_missing_or_corrupt_artifacts(tmp_path, monkeypatch):
    from core import downloads

    content = b"verified artifact"
    expected = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        toonout_assets,
        "ARTIFACTS",
        {"weights.pth": ("repo/resolve/pin/weights.pth", expected)},
    )
    download = Mock(
        side_effect=lambda url, path, headers, **kwargs: path.write_bytes(content)
    )
    monkeypatch.setattr(downloads, "download_archive", download)
    toonout_assets.install_assets(tmp_path)
    toonout_assets.install_assets(tmp_path)
    download.assert_called_once()
    assert download.call_args.kwargs["expected_sha256"] == expected
    (tmp_path / "weights.pth").write_bytes(b"broken")
    toonout_assets.install_assets(tmp_path)
    assert download.call_count == 2


@pytest.mark.parametrize(
    "url,running,expected",
    [
        ("http://127.0.0.1:8189", [], True),
        ("http://localhost:8188", [1], False),
        ("https://example.com", [], False),
        ("", [], False),
    ],
)
def test_only_explicit_idle_local_comfy_cache_is_released(
    tmp_path, monkeypatch, url, running, expected
):
    import requests

    (tmp_path / "runtime.json").write_text(json.dumps({"comfyui_url": url}))
    get = Mock(
        return_value=Mock(
            json=Mock(return_value={"queue_running": running, "queue_pending": []})
        )
    )
    post = Mock()
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    toonout_worker._release_idle_cache(tmp_path)
    assert post.called is expected
    if expected:
        assert post.call_args.kwargs["json"] == {
            "unload_models": True,
            "free_memory": True,
        }
