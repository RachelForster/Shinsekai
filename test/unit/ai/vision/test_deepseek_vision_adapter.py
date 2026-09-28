from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from ai.vision.deepseek_vision_adapter import DeepseekVisionAdapter


class _Completions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="a small blue icon"))]
        )


def test_deepseek_vision_adapter_sends_base64_image_block_with_detail():
    completions = _Completions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = DeepseekVisionAdapter(
        api_key="sk-test",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        detail="low",
        client=client,
    )
    image = b"\x89PNG\r\n\x1a\nimage"

    result = adapter.describe(image, "What is shown?")

    assert result == "a small blue icon"
    assert completions.kwargs["model"] == "deepseek-flash"
    content = completions.kwargs["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "What is shown?"}
    assert content[1]["image_url"]["detail"] == "low"
    assert content[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    )


def test_deepseek_vision_adapter_rejects_unsupported_image_content():
    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    adapter = DeepseekVisionAdapter(api_key="sk-test", client=client)

    with pytest.raises(ValueError, match="JPEG、PNG、GIF 和 WebP"):
        adapter.describe(b"not-an-image", "inspect")


def test_deepseek_vision_adapter_exposes_detail_choices():
    field = DeepseekVisionAdapter.get_config_schema()["detail"]

    assert field["default"] == "auto"
    assert field["choices"] == ["auto", "low", "high", "original"]
