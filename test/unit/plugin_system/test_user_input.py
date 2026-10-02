from __future__ import annotations

from queue import Queue

from plugin_system.host import service as plugin_host


class _PluginManager:
    def wire_user_input(self, emit_user_text, processors) -> None:
        processors.append(lambda text: f"processed:{text}")


def test_user_input_processors_preserve_chat_attachments(monkeypatch) -> None:
    queue = Queue()
    monkeypatch.setattr(plugin_host, "_plugin_manager", _PluginManager())
    emit = plugin_host.wire_user_input_plugins(queue)

    accepted = emit("hello", attachments=[{"kind": "file", "path": "C:/notes.txt"}])

    assert accepted is True
    message = queue.get_nowait()
    assert message.text == "processed:hello"
    assert message.attachments == [{"kind": "file", "path": "C:/notes.txt"}]


def test_user_input_processor_reports_rejected_input(monkeypatch) -> None:
    class _RejectingPluginManager:
        def wire_user_input(self, emit_user_text, processors) -> None:
            processors.append(lambda _text: None)

    queue = Queue()
    monkeypatch.setattr(plugin_host, "_plugin_manager", _RejectingPluginManager())

    accepted = plugin_host.wire_user_input_plugins(queue)("rejected")

    assert accepted is False
    assert queue.empty()


def test_user_input_pipeline_forwards_deferred_admission_policy(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    on_admit = lambda _text, _attachments: None
    monkeypatch.setattr(plugin_host, "_plugin_manager", _PluginManager())
    emit = plugin_host.wire_user_input_plugins(
        Queue(),
        sink=lambda text, **kwargs: calls.append((text, kwargs)),
    )

    assert emit(
        "voice",
        interrupt_current=False,
        defer_until_idle=True,
        on_admit=on_admit,
    )
    assert calls == [
        (
            "processed:voice",
            {
                "attachments": [],
                "defer_until_idle": True,
                "interrupt_current": False,
                "on_admit": on_admit,
            },
        )
    ]
