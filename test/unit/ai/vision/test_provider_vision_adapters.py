from __future__ import annotations

import base64
from types import SimpleNamespace

from ai.vision.provider_vision_adapters import ClaudeVisionAdapter, GeminiVisionAdapter


class _Completions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="a red bridge"))]
        )


def test_openai_compatible_provider_sends_base64_image_input():
    completions = _Completions()
    adapter = GeminiVisionAdapter(
        api_key="gemini-key",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.5-flash",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    image = b"\x89PNG\r\n\x1a\nimage"

    assert adapter.describe(image, "Describe") == "a red bridge"
    block = completions.kwargs["messages"][0]["content"][1]
    assert block["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    )


def test_claude_provider_uses_anthropic_image_source():
    calls = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="a green forest")]
            )

    adapter = ClaudeVisionAdapter(
        api_key="claude-key",
        base_url="https://api.anthropic.com/v1",
        model="claude-test",
        client=SimpleNamespace(messages=_Messages()),
    )

    assert adapter.describe(b"\xff\xd8\xffimage", "Describe") == "a green forest"
    source = calls[0]["messages"][0]["content"][0]["source"]
    assert source["type"] == "base64"
    assert source["media_type"] == "image/jpeg"
