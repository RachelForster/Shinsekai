from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

from frontend_bridge_core.routes import model_asset_routes
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.model_asset_routes import MODEL_ASSET_ROUTES


def test_model_asset_route_contracts_remain_stable() -> None:
    assert {
        (method, route.pattern)
        for route in MODEL_ASSET_ROUTES
        for method in route.methods
    } == {
        ("POST", "/api/model-assets/download"),
        ("POST", "/api/model-assets/status"),
    }


def test_download_route_reuses_an_existing_task(monkeypatch) -> None:
    state = object()
    request_model = object()
    spec = SimpleNamespace(
        asset_id="demo.asset",
        task_key="demo.asset:default",
        title="Demo asset",
        variant="default",
    )
    existing = {"id": "task-existing", "status": "running"}
    monkeypatch.setattr(
        model_asset_routes,
        "parse_model_asset_request",
        lambda _body: request_model,
    )
    monkeypatch.setattr(
        model_asset_routes,
        "configured_model_values",
        lambda _state: {"asr.faster-whisper": "default"},
    )
    monkeypatch.setattr(
        model_asset_routes,
        "resolve_model_asset",
        lambda _request, *, configured_values: spec,
    )
    monkeypatch.setattr(
        model_asset_routes,
        "find_running_model_download",
        lambda _state, _task_key: existing,
    )

    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "/api/model-assets/download"
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: {"assetId": "demo.asset"}
    handler._enqueue_background_task = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("an existing download must not enqueue another task")
    )
    sent: list[tuple[object, HTTPStatus]] = []
    handler._send_json = lambda data, status=HTTPStatus.OK: sent.append((data, status))

    handler.do_POST()

    assert sent == [(existing, HTTPStatus.ACCEPTED)]


def test_status_and_download_routes_support_direct_huggingface_repo_id(
    tmp_path, monkeypatch
) -> None:
    import threading
    from application.runtime.state import BridgeState

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-hub"))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    state = BridgeState(
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                api_config=SimpleNamespace(
                    hugging_face_access_token="hf-route-secret",
                    perception_model="",
                ),
                system_config=SimpleNamespace(asr_whisper_model_size="small"),
            )
        ),
        character_manager=None,
        background_manager=None,
        template_generator=None,
        task_lock=threading.Lock(),
    )

    status_sent: list[tuple[object, HTTPStatus]] = []
    status_handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    status_handler.server = SimpleNamespace(state=state)
    status_handler.path = "/api/model-assets/status"
    status_handler._require_authorized_write = lambda _path: None
    status_handler._read_json = lambda: {"repoId": "BAAI/bge-m3", "revision": "v1.0"}
    status_handler._send_json = lambda data, status=HTTPStatus.OK: status_sent.append(
        (data, status)
    )
    status_handler.do_POST()

    assert len(status_sent) == 1
    status_payload, status_code = status_sent[0]
    assert status_code == HTTPStatus.OK
    assert status_payload == {
        "assetId": "huggingface.repo",
        "variant": "BAAI/bge-m3@v1.0",
        "title": "BAAI/bge-m3@v1.0",
        "source": "huggingface",
        "repoId": "BAAI/bge-m3",
        "revision": "v1.0",
        "cached": False,
        "downloadable": True,
    }

    enqueued: dict[str, object] = {}
    worker_calls: list[tuple[object, str]] = []
    monkeypatch.setattr(
        model_asset_routes,
        "download_model",
        lambda spec, *, token, update_task: (
            worker_calls.append((spec, token)) or {"cached": True, "repoId": spec.repo_id}
        ),
    )

    def capture_enqueue(**kwargs):
        enqueued.update(kwargs)
        kwargs["worker"]("task-direct-1")
        task = {"id": "task-direct-1", "status": "queued", **kwargs["task_updates"]}
        download_handler._send_json(task, HTTPStatus.ACCEPTED)
        return task

    download_sent: list[tuple[object, HTTPStatus]] = []
    download_handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    download_handler.server = SimpleNamespace(state=state)
    download_handler.path = "/api/model-assets/download"
    download_handler._require_authorized_write = lambda _path: None
    download_handler._read_json = lambda: {
        "repoId": "BAAI/bge-m3",
        "revision": "v1.0",
        "title": "BGE M3",
    }
    download_handler._enqueue_background_task = capture_enqueue
    download_handler._send_json = lambda data, status=HTTPStatus.OK: download_sent.append(
        (data, status)
    )
    download_handler.do_POST()

    assert len(download_sent) == 1
    task_payload, task_code = download_sent[0]
    assert task_code == HTTPStatus.ACCEPTED
    assert enqueued["kind"] == "model-download"
    assert enqueued["title"] == "BGE M3"
    assert task_payload["assetId"] == "huggingface.repo"
    assert task_payload["repoId"] == "BAAI/bge-m3"
    assert task_payload["revision"] == "v1.0"
    assert task_payload["assetKey"] == "huggingface.repo:huggingface:baai/bge-m3@v1.0"
    assert len(worker_calls) == 1
    assert worker_calls[0][0].repo_id == "BAAI/bge-m3"
    assert worker_calls[0][0].allow_patterns == ()
    assert worker_calls[0][0].required_file_groups == ()
    assert worker_calls[0][1] == "hf-route-secret"


def test_routes_reject_explicit_revision_for_fixed_model_assets() -> None:
    import threading
    from application.runtime.state import BridgeState

    state = BridgeState(
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                api_config=SimpleNamespace(
                    hugging_face_access_token="",
                    perception_model="",
                ),
                system_config=SimpleNamespace(asr_whisper_model_size="small"),
            )
        ),
        character_manager=None,
        background_manager=None,
        template_generator=None,
        task_lock=threading.Lock(),
    )

    for path in ("/api/model-assets/status", "/api/model-assets/download"):
        for fixed_asset in ("memory.embedding", "vision.moondream"):
            sent: list[tuple[object, HTTPStatus]] = []
            handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
            handler.server = SimpleNamespace(state=state)
            handler.path = path
            handler._require_authorized_write = lambda _path: None
            handler._read_json = lambda aid=fixed_asset: {
                "assetId": aid,
                "revision": "v1.0",
            }
            handler._log_request_exception = lambda _exc: None
            handler._send_json = lambda data, status=HTTPStatus.OK, bucket=sent: bucket.append(
                (data, status)
            )
            handler.do_POST()

            assert len(sent) == 1
            payload, status = sent[0]
            assert status == HTTPStatus.BAD_REQUEST
            assert "do not accept a revision" in str(payload.get("error", ""))

