from __future__ import annotations

from pathlib import Path

from plugins.funasr_wss.adapter import FunASRWSSAdapter, _funasr_lang, _parse_chunk_size
from plugins.funasr_wss.plugin import FunASRWssPlugin
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry


class TestFunASRWssPlugin:
    def test_registers_asr_provider(self):
        reg = PluginCapabilityRegistry()
        plugin = FunASRWssPlugin()

        plugin.initialize(
            reg,
            plugin_root=Path("."),
            host=PluginHostContext.from_config_manager(None),
        )

        assert reg.asr_adapters["funasr_wss"] is FunASRWSSAdapter


class TestFunASRWSSAdapter:
    def test_connect_avoids_unnecessary_subprotocol_negotiation(self):
        seen = {}

        class DummyWebSocket:
            def settimeout(self, timeout):
                seen["timeout"] = timeout

            def send(self, payload):
                seen["payload"] = payload

        class DummyWebSocketModule:
            @staticmethod
            def create_connection(uri, **kwargs):
                seen["uri"] = uri
                seen["kwargs"] = kwargs
                return DummyWebSocket()

        class DummyStream:
            def stop_stream(self):
                pass

            def close(self):
                pass

        class DummyPyAudioModule:
            paInt16 = 8

            class PyAudio:
                def open(self, **kwargs):
                    seen["stream_kwargs"] = kwargs
                    return DummyStream()

                def terminate(self):
                    pass

        class TestAdapter(FunASRWSSAdapter):
            def _import_websocket_client(self):
                return DummyWebSocketModule()

            def _import_pyaudio(self):
                return DummyPyAudioModule

        adapter = TestAdapter(language="zh", callback=lambda *_: None)

        adapter._connect()

        assert seen["uri"] == "ws://127.0.0.1:10096"
        assert "subprotocols" not in seen["kwargs"]
        assert seen["kwargs"]["enable_multithread"] is True
        adapter._close_resources()

    def test_schema_contains_minimal_connection_fields(self):
        schema = FunASRWSSAdapter.get_config_schema()

        assert set(schema) == {"host", "port", "use_ssl", "mode"}
        assert schema["mode"]["default"] == "2pass"

    def test_chunk_size_parsing(self):
        assert _parse_chunk_size("5,10,5") == [5, 10, 5]
        assert _parse_chunk_size([8, 8, 4]) == [8, 8, 4]

    def test_language_mapping(self):
        assert _funasr_lang("zh") == "zh"
        assert _funasr_lang("en_US") == "en"
        assert _funasr_lang("ja") == "ja"
        assert _funasr_lang("yue") == "zh"

    def test_builds_start_payload(self):
        seen = []
        adapter = FunASRWSSAdapter(
            language="ja",
            callback=lambda text, is_partial: seen.append((text, is_partial)),
            host="127.0.0.1",
            port=10096,
            use_ssl=False,
            mode="2pass",
        )

        payload = adapter._build_start_payload()

        assert payload["mode"] == "2pass"
        assert payload["wav_format"] == "pcm"
        assert payload["lang"] == "ja"
        assert payload["chunk_size"] == [5, 10, 5]

    def test_handles_2pass_online_and_offline_messages(self):
        seen = []
        adapter = FunASRWSSAdapter(
            language="zh",
            callback=lambda text, is_partial: seen.append((text, is_partial)),
        )

        adapter._handle_server_message({"mode": "2pass-online", "text": "你"})
        adapter._handle_server_message({"mode": "2pass-offline", "text": "你好"})

        assert seen == [("你", True), ("你好", False)]

    def test_handles_generic_final_message(self):
        seen = []
        adapter = FunASRWSSAdapter(
            language="zh",
            callback=lambda text, is_partial: seen.append((text, is_partial)),
        )

        adapter._handle_server_message({"text": "hello", "is_final": True})

        assert seen == [("hello", False)]

    def test_sender_loop_signals_end_of_stream_on_empty_audio(self):
        sent_messages = []

        class DummyWebSocket:
            def send(self, payload):
                sent_messages.append(payload)

            def send_binary(self, payload):
                sent_messages.append(payload)

        class DummyStream:
            def read(self, frames_per_buffer, exception_on_overflow=False):
                return b""

        adapter = FunASRWSSAdapter(language="zh", callback=lambda *_: None)
        adapter._ws = DummyWebSocket()
        adapter._stream = DummyStream()

        adapter._sender_loop()

        assert sent_messages == ['{"is_speaking": false}']
