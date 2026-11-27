"""Unit tests for inline voice tags, voice instruction capabilities, and backward compatibility."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from ai.llm.template.session.tts_style import (
    TTS_STYLE_CONTEXT_MARKER,
    TTS_STYLE_CONTEXT_SPEC,
    TtsStyleContextPromptContext,
)
from ai.llm.text_processor import TextProcessor
from ai.tts.adapters.fish_audio_protocol import DEFAULT_FISH_AUDIO_URL
from ai.tts.adapters.fish_audio_s2_pro import FishAudioS2ProAdapter
from ai.tts.qwen3_tts_adapter import DEFAULT_QWEN3_TTS_URL, Qwen3TTSLlamaAdapter
from ai.tts.tts_manager import TTSManager
from ai.tts.voice_tags import (
    split_tts_sentences_preserving_tags,
    strip_inline_voice_tags,
)
from application.chat.capabilities import (
    SessionRuntimeCapabilityContext,
    StartupCapabilityContext,
    TtsStyleSessionCapability,
    TtsStyleTurnContextProvider,
    build_default_session_capabilities,
)
from application.chat.dialog_media import (
    DefaultTtsGenerationStrategy,
    ResolvedSpriteAsset,
    TtsGenerationRequest,
)
from core.messaging.formats.json_format import JsonDialogFormat
from core.messaging.formats.xml_tags_format import XmlTagsDialogFormat
from sdk.adapters.tts import TTSAdapter
from sdk.hooks import BeforeChatContext, PluginHookDispatcher
from sdk.messages import LLMDialogMessage


class _StrictLegacyTTSAdapter(TTSAdapter):
    """Simulates an older third-party TTS plugin without ``**kwargs`` or capability flags."""

    requires_ref_audio = False

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def switch_model(self, model_info: Any) -> None:
        return None

    def generate_speech(
        self,
        text: str,
        file_path: str | None = None,
        ref_audio_path: str | None = None,
        prompt_text: str | None = None,
        prompt_lang: str | None = None,
        text_lang: str = "ja",
        character_name: str | None = None,
        speed_factor: float | None = None,
    ) -> str:
        self.calls.append({"text": text, "text_lang": text_lang})
        target = Path(file_path or "")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"RIFF" + (b"\x01" * 32))
        return str(target)


class _InstructAwareTTSAdapter(TTSAdapter):
    """Simulates a TTS adapter supporting both inline tags and ``voice_instruct``."""

    requires_ref_audio = False

    def __init__(self, *, inline: bool = True, instruct: bool = True) -> None:
        self._inline = inline
        self._instruct = instruct
        self.calls: list[dict[str, Any]] = []

    @property
    def supports_inline_voice_tags(self) -> bool:
        return self._inline

    @property
    def supports_voice_instruction(self) -> bool:
        return self._instruct

    def switch_model(self, model_info: Any) -> None:
        return None

    def generate_speech(self, text: str, file_path: str | None = None, **kwargs: Any) -> str:
        self.calls.append({"text": text, "kwargs": kwargs})
        target = Path(file_path or "")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"RIFF" + (b"\x02" * 32))
        return str(target)


def test_tts_adapter_capability_defaults_and_legacy_plugin_safety(tmp_path: Path) -> None:
    legacy = _StrictLegacyTTSAdapter()
    assert legacy.supports_inline_voice_tags is False
    assert legacy.supports_voice_instruction is False

    manager = TTSManager(audio_cache_dir=tmp_path)
    try:
        manager.set_tts_adapter(legacy)
        audio_path = manager.generate_tts(
            "こんにちは",
            voice_instruct="soft teasing whisper",
        )
        assert audio_path and Path(audio_path).is_file()
        assert len(legacy.calls) == 1
        assert legacy.calls[0]["text"] == "こんにちは"
    finally:
        manager.shutdown(stop_server=False)


def test_dialog_message_and_xml_roundtrip_voice_instruct() -> None:
    msg = LLMDialogMessage(character_name="Alice", speech="Hi", instruct="playful whisper")
    assert msg.voice_instruct == "playful whisper"

    msg_alias = LLMDialogMessage(character_name="Alice", speech="Hey", voice_instruction="gentle smile")
    assert msg_alias.voice_instruct == "gentle smile"
    assert LLMDialogMessage(character_name="Alice", speech="Neutral").voice_instruct == ""

    fmt = XmlTagsDialogFormat()
    raw_xml = (
        '<narr voice_instruct="calm storyteller">Night falls.<tr>[sigh] Night falls.</tr></narr>\n'
        '<say name="Alice" sprite="1" voice_instruct="soft whisper">'
        "Secret!<tr>[soft whisper] 秘密だよ！</tr></say>\n"
        '<say name="Bob" sprite="2">Plain line.</say>'
    )
    parsed = fmt.parse_complete(raw_xml)
    assert parsed[0].voice_instruct == "calm storyteller"
    assert parsed[1].voice_instruct == "soft whisper"
    assert parsed[1].translate == "[soft whisper] 秘密だよ！"
    assert parsed[2].voice_instruct == ""

    serialized = fmt.serialize(parsed)
    assert 'voice_instruct="calm storyteller"' in serialized
    assert 'voice_instruct="soft whisper"' in serialized
    assert '<say char="Bob" sprite="2">Plain line.</say>' in serialized
    reparsed = fmt.parse_complete(serialized)
    assert [m.voice_instruct for m in reparsed] == ["calm storyteller", "soft whisper", ""]


@pytest.mark.parametrize("locale", ["zh_CN", "en", "ja"])
@pytest.mark.parametrize("format_id", ["json_v1", "xml_v1", "custom_fmt"])
def test_tts_style_prompt_spec_renders_for_locales_and_formats(
    locale: str,
    format_id: str,
) -> None:
    assert (
        TTS_STYLE_CONTEXT_SPEC.render_system(
            TtsStyleContextPromptContext(locale=locale, output_format_id=format_id)
        )
        == ""
    )
    both = TTS_STYLE_CONTEXT_SPEC.render_system(
        TtsStyleContextPromptContext(
            locale=locale,
            supports_inline_voice_tags=True,
            supports_voice_instruction=True,
            output_format_id=format_id,
        )
    )
    assert TTS_STYLE_CONTEXT_MARKER in both
    assert "[laugh]" in both
    assert "voice_instruct" in both
    assert ("<tr>...</tr>" if format_id == "xml_v1" else "translate") in both

    instruct_only = TTS_STYLE_CONTEXT_SPEC.render_system(
        TtsStyleContextPromptContext(
            locale=locale,
            supports_inline_voice_tags=False,
            supports_voice_instruction=True,
            output_format_id=format_id,
        )
    )
    assert TTS_STYLE_CONTEXT_MARKER in instruct_only
    assert "[laugh]" not in instruct_only
    assert "voice_instruct" in instruct_only


def test_tts_style_session_capability_injects_strips_and_adapts_dynamically() -> None:
    default_caps = build_default_session_capabilities()
    cap_ids = [cap.capability_id for cap in default_caps.capabilities()]
    assert "tts_style" in cap_ids
    assert isinstance(default_caps.get("tts_style"), TtsStyleSessionCapability)

    dispatcher = PluginHookDispatcher()
    tts_manager = SimpleNamespace(tts_adapter=None)
    config = SimpleNamespace(config=SimpleNamespace(system_config=SimpleNamespace(ui_language="en")))
    args = SimpleNamespace(output_format="xml_v1")
    llm_manager = SimpleNamespace(hook_dispatcher=dispatcher)

    cap = TtsStyleSessionCapability()
    cap.on_llm_ready(
        StartupCapabilityContext(
            args=args,
            config=config,
            llm_adapter=object(),
            llm_manager=llm_manager,
            plugin_manager=SimpleNamespace(hook_dispatcher=dispatcher),
            hook_dispatcher=dispatcher,
            character_names=("Alice",),
            tts_manager=tts_manager,
        )
    )
    cap.configure_session_runtime(
        SessionRuntimeCapabilityContext(
            mode="headless",
            args=args,
            config=config,
            startup=SimpleNamespace(llm_manager=llm_manager, tts_manager=tts_manager),
            transport=SimpleNamespace(),
            runtime=SimpleNamespace(tts_manager=tts_manager),
            ui_updates=SimpleNamespace(),
            chat_turn_service=SimpleNamespace(),
            app_runtime=SimpleNamespace(),
        )
    )

    ctx_none = BeforeChatContext(
        messages=[
            {"role": "system", "content": f"{TTS_STYLE_CONTEXT_MARKER} stale"},
            {"role": "user", "content": "hello"},
        ],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    dispatcher.dispatch_before_chat(ctx_none)
    assert len(ctx_none.messages) == 1

    tts_manager.tts_adapter = _InstructAwareTTSAdapter(inline=True, instruct=True)
    ctx_active = BeforeChatContext(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    dispatcher.dispatch_before_chat(ctx_active)
    injected = [m for m in ctx_active.messages if m["role"] == "system"]
    assert len(injected) == 1
    assert TTS_STYLE_CONTEXT_MARKER in injected[0]["content"]
    assert "<tr>...</tr>" in injected[0]["content"]

    tts_manager.tts_adapter = _InstructAwareTTSAdapter(inline=False, instruct=False)
    provider = TtsStyleTurnContextProvider(
        config=config,
        tts_adapter_getter=lambda: tts_manager.tts_adapter,
        output_format_id="json_v1",
    )
    ctx_disabled = BeforeChatContext(
        messages=list(ctx_active.messages),
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    provider.before_chat(ctx_disabled)
    assert all(TTS_STYLE_CONTEXT_MARKER not in m.get("content", "") for m in ctx_disabled.messages)


def test_voice_tag_helpers_preserve_markdown_and_split_safely() -> None:
    raw = "[laugh] Look at [this link](https://example.com) right here! [soft whisper] Okay?"
    assert strip_inline_voice_tags(raw) == "Look at [this link](https://example.com) right here! Okay?"

    sentences = split_tts_sentences_preserving_tags(
        "[soft, slow whisper] First sentence! [laugh, pause] Second sentence.",
        max_length=25,
    )
    assert "[soft, slow whisper] First sentence!" in sentences
    assert "[laugh, pause] Second sentence." in sentences


def test_tts_manager_and_strategy_language_probe_and_guarded_forwarding(tmp_path: Path) -> None:
    tp = TextProcessor()
    adapter = _InstructAwareTTSAdapter(inline=True, instruct=True)
    manager = TTSManager(audio_cache_dir=tmp_path)
    try:
        manager.set_tts_adapter(adapter)
        manager.set_language("ja")
        out = manager.generate_tts(
            "[laugh] 今日はいい天気ですね",
            text_processor=tp,
            voice_instruct="bright cheerful tone",
        )
        assert out and Path(out).is_file()
        assert adapter.calls[0]["text"] == "[laugh] 今日はいい天気ですね"
        assert adapter.calls[0]["kwargs"]["text_lang"] == "ja"
        assert adapter.calls[0]["kwargs"]["voice_instruct"] == "bright cheerful tone"
    finally:
        manager.shutdown(stop_server=False)

    mock_manager = MagicMock()
    mock_manager.tts_adapter = None
    wav_file = tmp_path / "line.wav"
    wav_file.write_bytes(b"RIFF" + (b"\x01" * 16))
    mock_manager.generate_tts.return_value = str(wav_file)
    runtime = SimpleNamespace(
        tts_manager=mock_manager,
        text_processor=tp,
        config=SimpleNamespace(
            config=SimpleNamespace(
                api_config=SimpleNamespace(tts_split_enabled=True, tts_max_sentence_length=15)
            )
        ),
    )
    character = SimpleNamespace(
        sovits_model_path="",
        gpt_model_path="",
        refer_audio_path="",
        prompt_text="",
        prompt_lang="ja",
        speech_speed=1.0,
    )
    req = TtsGenerationRequest(
        runtime=runtime,
        character=character,
        character_name="Alice",
        message=LLMDialogMessage(
            character_name="Alice",
            speech="你好呀",
            translate="[soft, whisper] こんにちは。",
            voice_instruct="whisper gently",
        ),
        sprite=ResolvedSpriteAsset(asset_id="1", index=0, value={}),
    )
    paths = list(DefaultTtsGenerationStrategy().generate(req))
    assert len(paths) == 1
    mock_manager.generate_tts.assert_called_once()
    assert mock_manager.generate_tts.call_args.args[0] == "[soft, whisper] こんにちは。"
    assert mock_manager.generate_tts.call_args.kwargs["voice_instruct"] == "whisper gently"


def test_fish_audio_s2_pro_inline_tags_and_voice_instruct_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert FishAudioS2ProAdapter.get_config_schema()["enable_inline_tags"]["default"] is True
    adapter = FishAudioS2ProAdapter(
        base_url=DEFAULT_FISH_AUDIO_URL,
        api_key="sk-fish-test",
        reference_id="voice-1",
    )
    assert adapter.supports_inline_voice_tags is True
    assert adapter.supports_voice_instruction is False
    disabled = FishAudioS2ProAdapter(
        base_url=DEFAULT_FISH_AUDIO_URL,
        api_key="sk-fish-test",
        reference_id="voice-1",
        enable_inline_tags=False,
    )
    assert disabled.supports_inline_voice_tags is False

    bodies: list[dict[str, Any]] = []
    monkeypatch.setattr(
        adapter._session,
        "post",
        lambda url, **kw: bodies.append(kw["json"])
        or SimpleNamespace(ok=True, status_code=200, content=b"RIFF" + (b"\x01" * 32), text=""),
    )
    adapter.generate_speech("你好", file_path=str(tmp_path / "a.wav"), voice_instruct="soft sigh")
    adapter.generate_speech("[laugh] 你好", file_path=str(tmp_path / "b.wav"), voice_instruct="soft sigh")
    assert bodies[0]["text"] == "[soft sigh] 你好"
    assert bodies[1]["text"] == "[laugh] 你好"


def test_qwen3_tts_voice_instruction_opt_in_and_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Qwen3TTSLlamaAdapter, "_start_server_process", lambda self: None)
    assert Qwen3TTSLlamaAdapter.get_config_schema()["enable_voice_instruction"]["default"] is False
    post_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "ai.tts.qwen3_tts_adapter.requests.Session.post",
        lambda self, url, **kw: post_calls.append(kw["json"])
        or SimpleNamespace(ok=True, status_code=200, content=b"RIFF" + (b"\x01" * 32), text=""),
    )
    default_adapter = Qwen3TTSLlamaAdapter(tts_server_url=DEFAULT_QWEN3_TTS_URL, voice="vivian")
    enabled_adapter = Qwen3TTSLlamaAdapter(
        tts_server_url=DEFAULT_QWEN3_TTS_URL,
        voice="vivian",
        enable_voice_instruction=True,
    )
    try:
        assert default_adapter.supports_voice_instruction is False
        assert enabled_adapter.supports_voice_instruction is True
        default_adapter.generate_speech("Hello", file_path=str(tmp_path / "default.wav"), text_lang="en", voice_instruct="warm smile")
        enabled_adapter.generate_speech("Hello", file_path=str(tmp_path / "enabled.wav"), text_lang="en", voice_instruct="warm smile")
        assert "instructions" not in post_calls[0]
        assert post_calls[1]["instructions"] == "warm smile"
    finally:
        default_adapter.stop_server()
        enabled_adapter.stop_server()


def test_json_format_serialization_and_xml_to_json_preserves_voice_instruct() -> None:
    from ai.llm.dialog_repair import normalize_messages_for_output_format

    json_fmt = JsonDialogFormat()
    items = [
        LLMDialogMessage(character_name="Alice", speech="Hi", sprite="1", voice_instruct="soft whisper"),
        LLMDialogMessage(character_name="Bob", speech="Plain", sprite="2"),
    ]
    serialized = json_fmt.serialize(items)
    assert serialized is not None and '"voice_instruct": "soft whisper"' in serialized
    reparsed = json_fmt.parse_complete(serialized)
    assert [m.voice_instruct for m in reparsed] == ["soft whisper", ""]

    xml_history = [
        {
            "role": "assistant",
            "content": '<say char="Alice" sprite="1" voice_instruct="soft whisper">Hi</say>',
            "__output_format": "xml_v1",
        }
    ]
    converted = normalize_messages_for_output_format(xml_history, json_fmt)
    parsed_back = json_fmt.parse_complete(converted[0]["content"])
    assert len(parsed_back) == 1
    assert parsed_back[0].voice_instruct == "soft whisper"

    assert (
        FishAudioS2ProAdapter.get_config_schema()["enable_inline_tags"]["labelKey"]
        == "ops.api.tts.fishAudio.extra.enableInlineTags"
    )
    assert (
        Qwen3TTSLlamaAdapter.get_config_schema()["enable_voice_instruction"]["labelKey"]
        == "ops.api.tts.qwen3Gguf.extra.enableVoiceInstruction"
    )
