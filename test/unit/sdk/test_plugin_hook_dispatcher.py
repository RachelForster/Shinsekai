from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sdk.chat_init import ChatInitService, InitChatContext
from sdk.hooks import (
    BeforeChatContext,
    BeforeCompactContext,
    MessageAddedContext,
    InitChatHookError,
    PluginHookDispatcher,
)
from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry


def test_dispatcher_runs_hooks_in_registration_order() -> None:
    dispatcher = PluginHookDispatcher()
    calls: list[tuple[str, list[dict]]] = []
    context = BeforeCompactContext(
        messages=[{"role": "user", "content": "old"}],
        older_messages=[{"role": "user", "content": "old"}],
        recent_messages=[],
    )

    dispatcher.register_before_compact(lambda ctx: calls.append(("first", ctx.messages)))
    dispatcher.register_before_compact(lambda ctx: calls.append(("second", ctx.messages)))

    dispatcher.dispatch_before_compact(context)

    assert calls == [("first", context.messages), ("second", context.messages)]


def test_dispatcher_isolates_hook_exceptions(caplog) -> None:
    dispatcher = PluginHookDispatcher()
    calls: list[str] = []

    def broken_hook(_context: MessageAddedContext) -> None:
        calls.append("broken")
        raise RuntimeError("hook exploded")

    dispatcher.register_message_added(broken_hook)
    dispatcher.register_message_added(lambda _context: calls.append("after"))

    with caplog.at_level(logging.WARNING):
        dispatcher.dispatch_message_added(
            MessageAddedContext(
                role="user",
                message={"role": "user", "content": "hello"},
                messages=[{"role": "user", "content": "hello"}],
            )
        )

    assert calls == ["broken", "after"]
    assert "message_added" in caplog.text
    assert "hook exploded" in caplog.text


def test_dispatcher_noops_without_registered_hooks() -> None:
    dispatcher = PluginHookDispatcher()
    context = BeforeChatContext(
        messages=[{"role": "system", "content": "S"}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )

    dispatcher.dispatch_before_chat(context)

    assert context.messages == [{"role": "system", "content": "S"}]
    assert context.tools is None
    assert context.generation_kwargs == {}


def test_registry_keeps_legacy_compact_hook_compatible() -> None:
    registry = PluginCapabilityRegistry()
    calls: list[list[dict]] = []

    def legacy_hook(messages: list[dict]) -> None:
        calls.append(messages)

    registry.register_compact_hook(legacy_hook)
    context = BeforeCompactContext(
        messages=[{"role": "user", "content": "old"}],
        older_messages=[{"role": "user", "content": "old"}],
        recent_messages=[],
    )

    registry.hook_dispatcher.dispatch_before_compact(context)

    assert calls == [context.messages]
    assert registry.compact_hooks == [legacy_hook]


def test_plugin_manager_and_registry_share_hook_dispatcher(tmp_path: Path) -> None:
    seen: list[bool] = []

    class HookPlugin(PluginBase):
        @property
        def plugin_id(self) -> str:
            return "demo.hooks"

        @property
        def plugin_version(self) -> str:
            return "1.0.0"

        def initialize(
            self,
            register: PluginCapabilityRegistry,
            plugin_root: Path,
            host: PluginHostContext,
        ) -> None:
            _ = plugin_root, host
            seen.append(register.hook_dispatcher is manager.hook_dispatcher)
            register.register_message_added_hook(lambda _context: None)

    manager = PluginManager(plugin_data_root=tmp_path)
    manager.register_plugin_class(HookPlugin)
    manager.instantiate_all()
    manager.load_own_config_all()

    assert seen == [True]
    assert manager.capabilities is not None
    assert manager.capabilities.hook_dispatcher is manager.hook_dispatcher
    assert manager.hook_dispatcher.has_hooks("message_added")


def test_init_chat_hooks_use_weighted_ranges_and_registration_order() -> None:
    events: list[dict] = []
    calls: list[str] = []
    dispatcher = PluginHookDispatcher()

    def first(context: InitChatContext) -> None:
        calls.append("first")
        context.report(0.5, "first halfway")

    def second(context: InitChatContext) -> None:
        calls.append("second")
        context.report(0.5, "second halfway")

    dispatcher.register_init_chat(first, label="first", weight=1)
    dispatcher.register_init_chat(second, label="second", weight=3)
    dispatcher.dispatch_init_chat(InitChatContext(service=ChatInitService(events.append)))

    assert calls == ["first", "second"]
    assert [event["task"]["progress"] for event in events] == pytest.approx(
        [0.0, 0.125, 0.25, 0.25, 0.625, 1.0]
    )


def test_init_chat_noncritical_failure_continues_but_critical_failure_raises(caplog) -> None:
    dispatcher = PluginHookDispatcher()
    calls: list[str] = []

    def optional(_context: InitChatContext) -> None:
        calls.append("optional")
        raise RuntimeError("optional failed")

    dispatcher.register_init_chat(optional, label="optional")
    dispatcher.register_init_chat(lambda _context: calls.append("after"), label="after")

    with caplog.at_level(logging.WARNING):
        failures = dispatcher.dispatch_init_chat(InitChatContext(service=ChatInitService()))

    assert calls == ["optional", "after"]
    assert len(failures) == 1
    assert failures[0].label == "optional"
    assert "optional failed" in caplog.text

    critical_dispatcher = PluginHookDispatcher()
    critical_dispatcher.register_init_chat(optional, label="required", critical=True)
    critical_dispatcher.register_init_chat(lambda _context: calls.append("never"), label="never")

    with pytest.raises(InitChatHookError, match="required"):
        critical_dispatcher.dispatch_init_chat(InitChatContext(service=ChatInitService()))
    assert "never" not in calls


def test_registry_registers_init_chat_hook_and_validates_weight() -> None:
    registry = PluginCapabilityRegistry()
    registry.register_init_chat_hook(lambda _context: None, label="warmup", weight=2.5)

    assert registry.hook_dispatcher.has_hooks("on_init_chat")
    registry.hook_dispatcher.dispatch("on_init_chat", InitChatContext(service=ChatInitService()))

    for invalid_weight in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="weight"):
            registry.register_init_chat_hook(lambda _context: None, weight=invalid_weight)
