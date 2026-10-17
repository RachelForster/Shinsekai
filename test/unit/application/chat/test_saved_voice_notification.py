from unittest.mock import Mock

from application.chat.presentation.updates import StreamingUIUpdateManager
from application.media.resource_urls import UnconfiguredResourceUrls


def test_saved_voice_notice_expires_without_clearing_newer_notice(monkeypatch) -> None:
    callbacks = []

    class FakeTimer:
        def __init__(self, _delay, callback):
            callbacks.append(callback)
            self.daemon = False

        def start(self) -> None:
            pass

    monkeypatch.setattr("application.chat.presentation.updates.threading.Timer", FakeTimer)
    sink = Mock()
    ui = StreamingUIUpdateManager(sink, chat_history=[], resource_urls=UnconfiguredResourceUrls())

    ui.post_notification("语音已保存")
    ui.post_notification("另一条通知")
    callbacks[0]()
    assert sink.emit.call_count == 2

    ui.post_notification("语音已保存")
    callbacks[1]()
    assert sink.emit.call_args.args[0] == {"type": "notification.change", "text": ""}
