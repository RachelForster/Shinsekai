"""Command extensions substitute small handlers without editing dispatch policy."""

from types import SimpleNamespace

import pytest

from application.chat.runtime_commands import ChatCommandRouter
from test.unit.application.chat.runtime_process_fakes import RecordingStream


@pytest.fixture
def state():
    return SimpleNamespace(
        chat_session={"sessionId": "session-1"}, chat_stream=RecordingStream()
    )


def test_registered_extension_uses_existing_transport_and_snapshot_contract(state):
    router = ChatCommandRouter(
        lambda _state, status, _message="", **kwargs: {
            "status": status,
            **(kwargs.get("extra") or {}),
        }
    )
    router.register(
        "extension",
        lambda context: context.forward("idle", snapshot_patch={"extensionResult": 42}),
    )
    assert router.handle(state, {"type": "extension", "cmdId": "stable"}) == {
        "status": "idle",
        "extensionResult": 42,
    }
    assert state.chat_stream.commands == [
        ("session-1", {"type": "extension", "cmdId": "stable"})
    ]


def test_local_handler_cannot_forward_an_unregistered_runtime_command(state):
    router = ChatCommandRouter(lambda *_args, **_kwargs: {})
    router.register("local", lambda context: context.forward("idle"), runtime=False)
    with pytest.raises(ValueError, match="未知实时聊天命令"):
        router.handle(state, {"type": "local"})
    assert not state.chat_stream.commands


@pytest.mark.parametrize("command,handler", [("", lambda _: {}), ("missing", None)])
def test_registration_requires_name_and_callable(command, handler):
    with pytest.raises(ValueError):
        ChatCommandRouter(lambda _: {}).register(command, handler)


def test_duplicate_registration_cannot_silently_replace_a_command(state):
    router = ChatCommandRouter(lambda _: {})
    router.register("first", lambda _: {"original": True})
    with pytest.raises(ValueError, match="already registered"):
        router.register("first", lambda _: {})
    assert router.handle(state, {"type": "first"}) == {"original": True}
    with pytest.raises(ValueError, match="未知聊天命令"):
        router.handle(state, {"type": "unknown"})
