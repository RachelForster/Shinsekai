import json

from t2i.t2i_adapter import ComfyUIT2IAdapter


class _Response:
    def __init__(self, payload=None, content=b""):
        self.status_code = 200
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _workflow_path(tmp_path):
    workflow = {
        "3": {"inputs": {"seed": 0}},
        "5": {"inputs": {"width": 512, "height": 512}},
        "6": {"inputs": {"text": ""}},
        "9": {"inputs": {}},
    }
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    return path


def test_comfyui_does_not_auto_start_by_default(monkeypatch, tmp_path):
    def fail_start(*args, **kwargs):
        raise AssertionError("ComfyUI should only auto-start when auto_start is enabled")

    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process_async", fail_start)

    ComfyUIT2IAdapter(workflow_path=str(_workflow_path(tmp_path)))


def test_comfyui_auto_start_is_explicit(monkeypatch, tmp_path):
    calls = []

    def record_start(self):
        calls.append(self.work_path)

    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process_async", record_start)

    ComfyUIT2IAdapter(
        workflow_path=str(_workflow_path(tmp_path)),
        work_path="C:/ComfyUI",
        auto_start=True,
    )

    assert calls == ["C:/ComfyUI"]


def test_comfyui_injects_prompt_size_and_seed_without_mutating_template(
    monkeypatch, tmp_path
):
    posted_payloads = []

    def fake_post(url, json, timeout):
        posted_payloads.append(json)
        return _Response({"prompt_id": "abc"})

    def fake_get(url, timeout):
        if "/history/" in url:
            return _Response(
                {
                    "abc": {
                        "outputs": {
                            "9": {
                                "images": [
                                    {
                                        "filename": "out.png",
                                        "subfolder": "",
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        return _Response(content=b"image-bytes")

    monkeypatch.setattr("t2i.t2i_adapter.requests.post", fake_post)
    monkeypatch.setattr("t2i.t2i_adapter.requests.get", fake_get)
    monkeypatch.setattr("t2i.t2i_adapter.time.sleep", lambda _seconds: None)
    out_path = tmp_path / "out.png"
    adapter = ComfyUIT2IAdapter(
        workflow_path=str(_workflow_path(tmp_path)),
        prompt_node_id="6",
        output_node_id="9",
        timeout_seconds=4,
    )

    result = adapter.generate_image(
        "city background",
        file_path=str(out_path),
        image_size="landscape",
        seed=123,
    )

    assert result == str(out_path.resolve())
    assert out_path.read_bytes() == b"image-bytes"
    workflow = posted_payloads[0]["prompt"]
    assert workflow["6"]["inputs"]["text"] == "city background"
    assert workflow["5"]["inputs"]["width"] == 832
    assert workflow["5"]["inputs"]["height"] == 512
    assert workflow["3"]["inputs"]["seed"] == 123
    assert adapter.workflow_template["5"]["inputs"]["width"] == 512
    assert adapter.workflow_template["3"]["inputs"]["seed"] == 0
