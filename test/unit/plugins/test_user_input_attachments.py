from __future__ import annotations

from queue import Queue

from core.plugins import plugin_host


class _PluginManager:
    def wire_user_input(self, emit_user_text, processors) -> None:
        processors.append(lambda text: f"processed:{text}")


def test_user_input_processors_preserve_chat_attachments(monkeypatch) -> None:
    queue = Queue()
    monkeypatch.setattr(plugin_host, "_plugin_manager", _PluginManager())
    emit = plugin_host.wire_user_input_plugins(queue)

    emit("hello", attachments=[{"kind": "file", "path": "C:/notes.txt"}])

    message = queue.get_nowait()
    assert message.text == "processed:hello"
    assert message.attachments == [{"kind": "file", "path": "C:/notes.txt"}]
