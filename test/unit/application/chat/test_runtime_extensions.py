from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from application.bootstrap.chat_runtime import get_chat_runtime
from application.chat.build_snapshot import build_chat_snapshot
from application.chat.dispatch_commands import CommandContext, CommandRegistry, RuntimeCommandPorts, dispatch_chat_command
from application.chat.history_commands import HistoryCommandBindings, HistoryParticipant, register_history_commands
from application.chat.lifecycle import ChatLifecycle, ChatLifecycleEvent
from application.chat.mobile_access import MobileAccessInfo
from application.chat.snapshot_contributions import SnapshotContext, SnapshotContributors
from application.runtime.state import BridgeState
from config.schema import ApiConfig


def state_with_stream(streaming: bool = False) -> BridgeState:
    state = BridgeState(
        config_manager=SimpleNamespace(config=SimpleNamespace(
            api_config=ApiConfig(), characters=[],
            system_config=SimpleNamespace(voice_language="ja"),
        )),
        character_manager=None, background_manager=None, template_generator=None,
        chat_session={"sessionId": "session" if streaming else ""},
    )
    if streaming:
        state.chat_stream = SimpleNamespace(get_snapshot=lambda *_args, **_kwargs: {
            "historyEntries": [], "status": "listening", "wsUrl": "ws://local",
        })
    return state


def context(command: str, payload=None) -> CommandContext:
    return CommandContext({"type": command, "payload": payload}, RuntimeCommandPorts(
        session_id="", stream=None, snapshot=lambda *_args, **kwargs: kwargs,
        update_session=lambda _patch: None,
    ))


def test_commands_and_option_subtypes_are_unique_and_explicit():
    registry = CommandRegistry()
    registry.register("submit-option", lambda _ctx: {"kind": "text"})
    registry.register_option("story-choice", lambda _ctx: {"kind": "story"})
    registry.register_option("tool-confirmation", lambda _ctx: {"kind": "tool"})
    assert registry.execute(context("submit-option", "yes")) == {"kind": "text"}
    assert registry.execute(context("submit-option", {"kind": "story-choice"})) == {"kind": "story"}
    assert registry.execute(context("submit-option", {"kind": "tool-confirmation"})) == {"kind": "tool"}
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register("submit-option", lambda _ctx: {})
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register_option("story-choice", lambda _ctx: {})
    with pytest.raises(ValueError, match="Option selection"):
        registry.execute(context("submit-option", {"kind": "unregistered"}))
    with pytest.raises(ValueError, match="未知聊天命令"):
        registry.execute(context("unregistered"))


def test_registration_needs_no_central_dispatch_change_and_is_instance_local():
    first, second = state_with_stream(), state_with_stream()
    runtime = get_chat_runtime(first)
    assert get_chat_runtime(first) is runtime
    assert get_chat_runtime(second) is not runtime
    seen = []

    def extension(ctx):
        assert not hasattr(ctx, "state")
        assert not hasattr(ctx, "config_manager")
        ctx.body["payload"]["items"].append("local")
        seen.append(ctx.command)
        return ctx.ports.snapshot(extra={"extensionReply": "ok"})

    runtime.commands.register("extension", extension)
    request = {"type": "extension", "payload": {"items": []}}
    assert dispatch_chat_command(first, request)["extensionReply"] == "ok"
    assert request["payload"]["items"] == []
    assert seen == ["extension"]
    with pytest.raises(ValueError, match="未知聊天命令"):
        dispatch_chat_command(second, request)
    # Registering a local handler does not implicitly authorize worker forwarding.
    with pytest.raises(ValueError, match="未知实时聊天命令"):
        context("extension").forward("idle")


def test_contributors_enforce_ownership_and_declare_core_overrides():
    registry = SnapshotContributors()
    registry.register("one", {"custom"}, lambda _ctx: {"custom": 1})
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register("two", {"custom"}, lambda _ctx: {})
    with pytest.raises(ValueError, match="protected"):
        registry.register("unsafe", {"sprites"}, lambda _ctx: {})
    with pytest.raises(ValueError, match="protected"):
        registry.register("unsafe-worker-field", {"stats"}, lambda _ctx: {})
    with pytest.raises(ValueError, match="declared"):
        registry.register("invalid", {"custom2"}, lambda _ctx: {}, allow_core_override=frozenset({"wsUrl"}))
    registry.register("mobile", {"wsUrl"}, lambda _ctx: {"wsUrl": "ws://mobile"},
                      allow_core_override=frozenset({"wsUrl"}))
    view = SnapshotContext.create({}, {}, streaming=True)
    assert registry.project(view) == {"custom": 1, "wsUrl": "ws://mobile"}
    bad = SnapshotContributors()
    bad.register("bad", {"custom"}, lambda _ctx: {"status": "corrupted"})
    with pytest.raises(ValueError, match="undeclared"):
        bad.project(view)


def test_snapshot_inputs_are_detached_and_recursively_readonly_outputs_are_copied():
    session, snapshot = {"nested": {"list": [1]}}, {"sprites": [{"id": "original"}]}
    view = SnapshotContext.create(session, snapshot, streaming=True)
    session["nested"]["list"].append(2)
    assert view.session["nested"]["list"] == (1,)
    with pytest.raises(TypeError):
        view.snapshot["sprites"][0]["id"] = "bad"
    with pytest.raises(AttributeError):
        view.session["nested"]["list"].append(3)
    with pytest.raises(FrozenInstanceError):
        view.streaming = False
    output = {"custom": {"list": [1]}}
    registry = SnapshotContributors()
    registry.register("extension", {"custom"}, lambda _ctx: output)
    projected = registry.project(view)
    projected["custom"]["list"].append(2)
    assert output == {"custom": {"list": [1]}}
    assert snapshot == {"sprites": [{"id": "original"}]}
    # Returning a readonly input subtree still produces detached JSON arrays.
    registry.register("copy-view", {"copiedSprites"}, lambda ctx: {"copiedSprites": ctx.snapshot["sprites"]})
    assert registry.project(view)["copiedSprites"] == [{"id": "original"}]


@pytest.mark.parametrize("streaming", [False, True])
def test_contributions_run_in_both_real_snapshot_paths_without_leaking_between_instances(streaming):
    state = state_with_stream(streaming)
    calls = []

    def contribute(view):
        calls.append(view.streaming)
        assert view.session["sessionId"] == state.chat_session["sessionId"]
        return {"extensionPanel": {"enabled": True}}

    get_chat_runtime(state).snapshots.register("extension", {"extensionPanel"}, contribute)
    assert build_chat_snapshot(state)["extensionPanel"] == {"enabled": True}
    assert calls == [streaming]
    assert "extensionPanel" not in build_chat_snapshot(state_with_stream(streaming))


@pytest.mark.parametrize("streaming", [False, True])
def test_mobile_ws_override_and_snapshot_extra_priority_are_preserved(streaming):
    state = state_with_stream(streaming)
    info = MobileAccessInfo("host", 80, 81, "http://mobile", "ws://mobile", "qr")
    state.mobile_access_service = SimpleNamespace(snapshot=lambda: info)
    get_chat_runtime(state).snapshots.register("late", {"lateField"}, lambda _ctx: {"lateField": "owner"},
                                            after_extra_on_stream=True)
    result = build_chat_snapshot(state, extra={"lateField": "extra"})
    assert result["mobileAccess"]["enabled"] is True
    assert result["lateField"] == ("owner" if streaming else "extra")
    if streaming:
        assert result["wsUrl"] == "ws://mobile"
    else:
        assert "wsUrl" not in result


@pytest.mark.parametrize("command,payload", [("revert-history", 0), ("fork-history", 0), ("switch-branch", "branch")])
def test_history_participants_keep_sync_send_publish_order(command, payload):
    calls = []
    registry = CommandRegistry()
    register_history_commands(registry, HistoryCommandBindings(
        copy_payload=lambda: {}, open_payload=lambda: {}, clear_storage=lambda: None,
        features=lambda: {"forkHistory": True, "conversationTree": True},
    ), HistoryParticipant(
        discard=lambda: None,
        before_branch=lambda *_args: calls.append("sync"),
        after_branch=lambda: calls.append("publish"),
    ))
    stream = SimpleNamespace(
        send_command=lambda *_args: calls.append("send") or True,
        get_snapshot=lambda *_args: {}, update_session_snapshot=lambda *_args: None,
    )
    ctx = CommandContext({"type": command, "payload": payload}, RuntimeCommandPorts(
        "session", stream, lambda *_args, **_kwargs: {}, lambda _patch: None,
    ))
    registry.execute(ctx)
    assert calls == ["sync", "send", "publish"]


def test_lifecycle_order_unregister_failure_isolation_and_readonly_event():
    lifecycle = ChatLifecycle()
    calls = []

    def broken(event):
        calls.append("broken")
        assert set(vars(event)) == {"kind", "session_id"}
        with pytest.raises(FrozenInstanceError):
            event.session_id = "other"
        raise RuntimeError("optional observer failed")

    remove = lifecycle.register(broken)
    lifecycle.register(lambda event: calls.append(event.kind))
    lifecycle.notify(ChatLifecycleEvent("ready", "session"))
    remove()
    remove()
    lifecycle.notify(ChatLifecycleEvent("stopped", "session"))
    assert calls == ["broken", "ready", "stopped"]
