import base64

from t2i.t2i_adapter import OpenAIImageAdapter
from t2i.t2i_manager import T2IAdapterFactory


class _Response:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_factory_registers_openai_image_adapter():
    adapter = T2IAdapterFactory.create_adapter(
        "openai-image",
        api_key="test-key",
        api_url="https://example.test/v1",
    )

    assert isinstance(adapter, OpenAIImageAdapter)
    assert T2IAdapterFactory._adapters["newapi-image"] is OpenAIImageAdapter


def test_generation_endpoint_accepts_base_or_v1_url():
    assert (
        OpenAIImageAdapter(api_url="https://example.test")._generation_endpoint()
        == "https://example.test/v1/images/generations"
    )
    assert (
        OpenAIImageAdapter(api_url="https://example.test/v1")._generation_endpoint()
        == "https://example.test/v1/images/generations"
    )


def test_generate_image_saves_base64_response(monkeypatch, tmp_path):
    calls = []
    image_bytes = b"fake-png"

    def fake_post(url, headers, json, timeout):
        calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return _Response(
            payload={
                "data": [
                    {
                        "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                    }
                ]
            }
        )

    monkeypatch.setattr("t2i.t2i_adapter.requests.post", fake_post)
    out_path = tmp_path / "image.png"
    adapter = OpenAIImageAdapter(
        api_url="https://example.test/v1",
        api_key="test-key",
        model="gpt-image-2",
        timeout_seconds=45,
    )

    result = adapter.generate_image("city background", file_path=str(out_path))

    assert result == str(out_path.resolve())
    assert out_path.read_bytes() == image_bytes
    assert calls[0]["url"] == "https://example.test/v1/images/generations"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["timeout"] == 45
    assert calls[0]["json"]["model"] == "gpt-image-2"
    assert calls[0]["json"]["size"] == "1536x1024"


def test_generate_image_retries_without_optional_fields_on_bad_request(monkeypatch, tmp_path):
    calls = []
    image_bytes = b"retry-png"

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            return _Response(status_code=400)
        return _Response(
            payload={
                "data": [
                    {
                        "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                    }
                ]
            }
        )

    monkeypatch.setattr("t2i.t2i_adapter.requests.post", fake_post)
    out_path = tmp_path / "retry.png"
    adapter = OpenAIImageAdapter(
        api_key="test-key",
        quality="low",
        moderation="low",
    )

    result = adapter.generate_image("1girl portrait", file_path=str(out_path))

    assert result == str(out_path.resolve())
    assert out_path.read_bytes() == image_bytes
    assert "quality" in calls[0]
    assert "moderation" in calls[0]
    assert "quality" not in calls[1]
    assert "moderation" not in calls[1]
    assert "size" not in calls[1]
