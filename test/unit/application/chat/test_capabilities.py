"""Unit tests for `SessionCapability` and `TurnContextProvider` orchestration."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
import os
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from ai.llm.template.prompts import UserPromptContext
from ai.vision.service import PreparedChatInput
from application.chat.capabilities import (
    RELATION_CONTEXT_MARKER,
    BackgroundTurnContextProvider,
    BaseSessionCapability,
    BaseTurnContextProvider,
    KnowledgeSessionCapability,
    MemorySessionCapability,
    PerceptionSessionCapability,
    PerceptionTurnContextProvider,
    PluginLoadedCapabilityContext,
    RelationSessionCapability,
    RelationTurnContextProvider,
    SessionCapabilitySet,
    SessionRuntimeCapabilityContext,
    StartupCapabilityContext,
    StreamingWiringCapabilityContext,
    TurnAdmissionDecision,
    TurnAdmissionRequest,
    TurnContextPipeline,
    TurnUserPromptContribution,
)
from application.chat.runtime.commands import (
    ChatCommandBindings,
    ChatCommandDispatcher,
    ChatCommandRequest,
    ChatCommandUiBindings,
)
from application.runtime.context import AppRuntime, set_app_runtime
from application.runtime.workers.llm_worker import LLMWorker
from core.messaging.chat_turn_service import ChatTurnService
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher
from sdk.messages import UserInputMessage


class _RecordingTurnProvider(BaseTurnContextProvider):
    def __init__(
        self,
        capability_id: str,
        *,
        admit: TurnAdmissionDecision | None = None,
        prompt: TurnUserPromptContribution | None = None,
        delegates_to_hook_dispatcher: bool = False,
    ) -> None:
        self.capability_id = capability_id
        self._admit = admit
        self._prompt = prompt
        self.delegates_to_hook_dispatcher = delegates_to_hook_dispatcher
        self.events: list[tuple[str, Any]] = []

    def admit_turn(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnAdmissionDecision | None:
        self.events.append(("admit", request.source))
        return self._admit

    def contribute_user_prompt(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnUserPromptContribution | None:
        self.events.append(("prompt", request.text))
        return self._prompt

    def before_chat(self, context: BeforeChatContext) -> None:
        self.events.append(("before_chat", len(context.messages)))
        context.messages.append(
            {"role": "system", "content": f"[{self.capability_id}]"}
        )

    def message_added(self, context: MessageAddedContext) -> None:
        self.events.append(("message_added", context.role))


def test_turn_context_pipeline_admission_prompt_and_dispatcher_hooks() -> None:
    p1 = _RecordingTurnProvider(
        "first",
        admit=TurnAdmissionDecision(admitted=True, record_user_message=False),
        prompt=TurnUserPromptContribution(
            background={"场景": "教室"},
            prefix="[环境提示 A]",
            suffix="[尾注 A]",
        ),
    )
    p2 = _RecordingTurnProvider(
        "second",
        admit=TurnAdmissionDecision(admitted=True, record_user_message=True),
        prompt=TurnUserPromptContribution(
            prefix="[环境提示 B]",
            suffix="[尾注 B]",
        ),
    )
    delegated = _RecordingTurnProvider(
        "delegated",
        delegates_to_hook_dispatcher=True,
    )
    pipeline = TurnContextPipeline((p1, p2, delegated))

    request = TurnAdmissionRequest(
        history_turn_id="turn-1",
        source="user",
        text="你好",
    )
    decision = pipeline.admit_turn(request)
    assert decision == TurnAdmissionDecision(admitted=True, record_user_message=False)

    envelope = pipeline.collect_user_prompt(request)
    assert envelope.has_enrichment is True
    assert envelope.background == {"场景": "教室"}
    assert envelope.prefix == "[环境提示 A]\n\n[环境提示 B]"
    assert envelope.suffix == "[尾注 A]\n\n[尾注 B]"

    prepared = PreparedChatInput(
        content=[
            {"type": "text", "text": "你好"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ],
        display_text="你好 [image]",
        mode="native",
        prompt_context=UserPromptContext(user_input="你好", prefix="[模板前缀]"),
    )
    rendered = prepared.render_content(
        background=envelope.background,
        prefix=envelope.prefix,
        suffix=envelope.suffix,
    )
    assert isinstance(rendered, list)
    assert rendered[1]["type"] == "image_url"
    rendered_text = rendered[0]["text"]
    assert "[模板前缀]" in rendered_text
    assert "[环境提示 A]" in rendered_text
    assert "[当前显示背景]" in rendered_text
    assert "你好" in rendered_text
    assert "[尾注 B]" in rendered_text

    dispatcher = PluginHookDispatcher()
    pipeline.register_dispatcher_hooks(dispatcher)
    pipeline.register_dispatcher_hooks(dispatcher)  # idempotent per dispatcher

    before_ctx = BeforeChatContext(
        messages=[{"role": "user", "content": "你好"}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    dispatcher.dispatch_before_chat(before_ctx)
    assert [m["content"] for m in before_ctx.messages] == [
        "你好",
        "[first]",
        "[second]",
    ]
    assert ("before_chat", 1) not in delegated.events

    added_ctx = MessageAddedContext(
        role="assistant",
        message={"role": "assistant", "content": "回应"},
        messages=before_ctx.messages,
    )
    dispatcher.dispatch_message_added(added_ctx)
    assert ("message_added", "assistant") in p1.events
    assert ("message_added", "assistant") in p2.events
    assert ("message_added", "assistant") not in delegated.events


def test_turn_context_pipeline_short_circuits_when_provider_rejects() -> None:
    reject = _RecordingTurnProvider(
        "gate",
        admit=TurnAdmissionDecision(admitted=False, record_user_message=False),
    )
    after = _RecordingTurnProvider("after")
    pipeline = TurnContextPipeline((reject, after))

    decision = pipeline.admit_turn(
        TurnAdmissionRequest(history_turn_id="turn-x", source="perception")
    )
    assert decision == TurnAdmissionDecision(admitted=False, record_user_message=False)
    assert after.events == []


def test_session_capability_set_orders_lifecycle_and_composes_shutdown() -> None:
    lifecycle: list[str] = []

    class _Cap(BaseSessionCapability):
        def __init__(self, cid: str, *, has_pre_shutdown: bool = False) -> None:
            self.capability_id = cid
            self._has_pre_shutdown = has_pre_shutdown
            self._provider = _RecordingTurnProvider(cid)

        def on_plugins_loaded(self, context: PluginLoadedCapabilityContext) -> None:
            del context
            lifecycle.append(f"{self.capability_id}:plugins")

        def on_llm_ready(self, context: StartupCapabilityContext) -> None:
            del context
            lifecycle.append(f"{self.capability_id}:llm")

        def init_chat_flags(self) -> dict[str, Any]:
            return {f"{self.capability_id}_flag": True}

        def configure_session_runtime(
            self,
            context: SessionRuntimeCapabilityContext,
        ) -> None:
            del context
            lifecycle.append(f"{self.capability_id}:runtime")

        def bind_streaming_session(
            self,
            context: StreamingWiringCapabilityContext,
        ) -> None:
            del context
            lifecycle.append(f"{self.capability_id}:bind")

        def on_session_ready(self) -> None:
            lifecycle.append(f"{self.capability_id}:ready")

        def turn_context_providers(self):
            return (self._provider,)

        def command_handlers(self):
            return {f"{self.capability_id}-cmd": lambda payload: lifecycle.append(f"{self.capability_id}:cmd:{payload}")}

        def pre_shutdown_action(self):
            if not self._has_pre_shutdown:
                return None
            return lambda: lifecycle.append(f"{self.capability_id}:pre_shutdown")

        def on_shutdown(self) -> None:
            lifecycle.append(f"{self.capability_id}:shutdown")

    idle_set = SessionCapabilitySet((_Cap("alpha"),))
    primary_close = lambda: lifecycle.append("asr:close")
    assert idle_set.compose_pre_shutdown(primary_close) is primary_close

    cap_set = SessionCapabilitySet(
        (_Cap("alpha", has_pre_shutdown=True), _Cap("beta")),
        default_turn_providers=(BackgroundTurnContextProvider(),),
    )
    cap_set.on_plugins_loaded(
        PluginLoadedCapabilityContext(
            args=SimpleNamespace(),
            config=SimpleNamespace(),
            plugin_manager=None,
            hook_dispatcher=None,
        )
    )
    cap_set.on_llm_ready(
        StartupCapabilityContext(
            args=SimpleNamespace(),
            config=SimpleNamespace(),
            llm_adapter=object(),
            llm_manager=SimpleNamespace(),
            plugin_manager=None,
            hook_dispatcher=None,
            character_names=(),
        )
    )
    assert cap_set.collect_init_chat_flags() == {
        "alpha_flag": True,
        "beta_flag": True,
    }

    pipeline = cap_set.build_turn_context_pipeline()
    assert [p.capability_id for p in pipeline.providers()] == [
        "background",
        "alpha",
        "beta",
    ]

    app_runtime = SimpleNamespace(turn_context_pipeline=pipeline)
    dispatcher = PluginHookDispatcher()
    cap_set.configure_session_runtime(
        SessionRuntimeCapabilityContext(
            mode="stream",
            args=SimpleNamespace(),
            config=SimpleNamespace(),
            startup=SimpleNamespace(llm_manager=SimpleNamespace(hook_dispatcher=dispatcher)),
            transport=SimpleNamespace(),
            runtime=SimpleNamespace(),
            ui_updates=SimpleNamespace(),
            chat_turn_service=SimpleNamespace(),
            app_runtime=app_runtime,
        )
    )
    cap_set.bind_streaming_session(
        StreamingWiringCapabilityContext(bindings=SimpleNamespace(), app_runtime=app_runtime)
    )
    cap_set.on_session_ready()
    handlers = cap_set.command_handlers()
    handlers["alpha-cmd"]("ok")

    composed = cap_set.compose_pre_shutdown(primary_close)
    assert composed is not None and composed is not primary_close
    composed()
    cap_set.on_shutdown()

    assert lifecycle == [
        "alpha:plugins",
        "beta:plugins",
        "alpha:llm",
        "beta:llm",
        "alpha:runtime",
        "beta:runtime",
        "alpha:bind",
        "beta:bind",
        "alpha:ready",
        "beta:ready",
        "alpha:cmd:ok",
        "alpha:pre_shutdown",
        "asr:close",
        "beta:shutdown",
        "alpha:shutdown",
    ]


def test_memory_and_knowledge_capabilities_install_hooks_cleanly(monkeypatch) -> None:
    monkeypatch.setenv("SHINSEKAI_MEMORY_AUTO_ENABLED", "off")
    memory_cap = MemorySessionCapability()
    assert memory_cap.init_chat_flags() == {"memory_enabled": False}

    monkeypatch.setenv("SHINSEKAI_MEMORY_AUTO_ENABLED", "1")
    assert memory_cap.init_chat_flags() == {"memory_enabled": True}

    fake_memory_hooks = SimpleNamespace(before_chat=Mock(), message_added=Mock())
    installer = Mock(return_value=fake_memory_hooks)
    dispatcher = PluginHookDispatcher()
    memory_cap.on_llm_ready(
        StartupCapabilityContext(
            args=SimpleNamespace(),
            config=SimpleNamespace(),
            llm_adapter="adapter",
            llm_manager=SimpleNamespace(hook_dispatcher=dispatcher),
            plugin_manager=SimpleNamespace(hook_dispatcher=dispatcher),
            hook_dispatcher=dispatcher,
            character_names=("Mika",),
            runtime_imports=SimpleNamespace(install_memory_hooks=installer),
        )
    )
    installer.assert_called_once_with(
        dispatcher,
        llm_adapter="adapter",
        character_names=["Mika"],
    )
    assert len(memory_cap.turn_context_providers()) == 1

    knowledge_cap = KnowledgeSessionCapability()
    fake_knowledge_hooks = SimpleNamespace(before_chat=Mock())
    register_knowledge = Mock(return_value=fake_knowledge_hooks)
    monkeypatch.setattr(
        "application.knowledge.hooks.install_knowledge_hooks",
        register_knowledge,
    )
    search_fn = Mock()
    status_fn = Mock()
    knowledge_cap.on_plugins_loaded(
        PluginLoadedCapabilityContext(
            args=SimpleNamespace(),
            config=SimpleNamespace(
                config=SimpleNamespace(api_config=SimpleNamespace(knowledge_enabled=True))
            ),
            plugin_manager=SimpleNamespace(hook_dispatcher=dispatcher),
            hook_dispatcher=dispatcher,
            transport=SimpleNamespace(
                knowledge_search=search_fn,
                knowledge_status=status_fn,
            ),
        )
    )
    register_knowledge.assert_called_once_with(
        dispatcher,
        search_func=search_fn,
        status_func=status_fn,
    )
    assert len(knowledge_cap.turn_context_providers()) == 1


def test_relation_capability_skips_duplicate_and_injects_live_updates(
    tmp_path: Path,
) -> None:
    char_file = tmp_path / "character_config.yaml"
    char_file.write_text("characters: []\n", encoding="utf-8")

    nodes = [{"key": "Alice"}, {"key": "Bob"}]
    alice = SimpleNamespace(
        name="Alice",
        relation_graph={
            "nodes": nodes,
            "edges": [
                {"source": "Alice", "target": "Bob", "content": "青梅竹马"}
            ],
        },
    )
    bob = SimpleNamespace(
        name="Bob",
        relation_graph={
            "nodes": nodes,
            "edges": [
                {"source": "Bob", "target": "Alice", "content": "同桌搭档"}
            ],
        },
    )
    refreshed: list[int] = []

    def refresh_media_catalogs() -> None:
        refreshed.append(1)
        alice.relation_graph = {
            "nodes": nodes,
            "edges": [
                {"source": "Alice", "target": "Bob", "content": "宿敌"}
            ],
        }

    config = SimpleNamespace(
        _CHARACTERS_CONFIG_PATH=str(char_file),
        config=SimpleNamespace(characters=[alice, bob]),
        get_character_by_name=lambda name: {"Alice": alice, "Bob": bob}.get(name),
        refresh_media_catalogs=refresh_media_catalogs,
    )

    translate = lambda key, **kwargs: f"{key}:{kwargs}"
    dispatcher = PluginHookDispatcher()
    relation_cap = RelationSessionCapability(translate=translate)
    relation_cap.on_llm_ready(
        StartupCapabilityContext(
            args=SimpleNamespace(player_character="Bob"),
            config=config,
            llm_adapter=object(),
            llm_manager=SimpleNamespace(hook_dispatcher=dispatcher),
            plugin_manager=None,
            hook_dispatcher=dispatcher,
            character_names=("Alice",),
        )
    )
    providers = relation_cap.turn_context_providers()
    assert len(providers) == 1
    provider = providers[0]
    assert isinstance(provider, RelationTurnContextProvider)

    initial_block = provider.render_relation_block()
    assert "青梅竹马" in initial_block

    # When system prompt already embeds the identical block, do not duplicate tokens.
    unchanged_ctx = BeforeChatContext(
        messages=[
            {"role": "system", "content": f"Base prompt\n\n{initial_block}"},
            {"role": "user", "content": "你好"},
        ],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    dispatcher.dispatch_before_chat(unchanged_ctx)
    assert len(unchanged_ctx.messages) == 2
    assert refreshed == []

    # Advance file mtime to simulate live relation editing during session.
    stat = char_file.stat()
    os.utime(char_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))

    updated_ctx = BeforeChatContext(
        messages=[
            {"role": "system", "content": f"Base prompt\n\n{initial_block}"},
            {"role": "user", "content": "现在呢？"},
        ],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    dispatcher.dispatch_before_chat(updated_ctx)
    assert refreshed == [1]
    assert len(updated_ctx.messages) == 3
    assert updated_ctx.messages[-1]["role"] == "system"
    assert updated_ctx.messages[-1]["content"].startswith(RELATION_CONTEXT_MARKER)
    assert "宿敌" in updated_ctx.messages[-1]["content"]


@dataclass
class _FakePerceptionApiConfig:
    perception_enabled: bool = False
    perception_proactive_enabled: bool = False
    perception_salience_threshold: float = 0.7

    def model_copy(self, *, deep: bool = False) -> _FakePerceptionApiConfig:
        del deep
        return copy(self)


def test_perception_turn_provider_and_capability_commands(monkeypatch) -> None:
    hooks = SimpleNamespace(
        prepare_turn=Mock(side_effect=[False, True, True]),
        before_chat=Mock(),
        message_added=Mock(),
    )
    coordinator = SimpleNamespace(
        mark_proactive_turn_admitted=Mock(),
        ingest=Mock(),
        clear=Mock(),
        _emit_state=Mock(),
        stop=Mock(),
        start=Mock(),
    )
    pause_asr = Mock()
    provider = PerceptionTurnContextProvider(
        hooks=hooks,
        coordinator=coordinator,
        pause_asr=pause_asr,
    )

    rejected = provider.admit_turn(
        TurnAdmissionRequest(history_turn_id="t1", source="perception")
    )
    assert rejected == TurnAdmissionDecision(admitted=False, record_user_message=False)
    coordinator.mark_proactive_turn_admitted.assert_not_called()

    admitted_proactive = provider.admit_turn(
        TurnAdmissionRequest(history_turn_id="t2", source="perception")
    )
    assert admitted_proactive == TurnAdmissionDecision(
        admitted=True,
        record_user_message=False,
    )
    coordinator.mark_proactive_turn_admitted.assert_called_once_with()
    pause_asr.assert_called_once_with()

    admitted_user = provider.admit_turn(
        TurnAdmissionRequest(history_turn_id="t3", source="user")
    )
    assert admitted_user == TurnAdmissionDecision(
        admitted=True,
        record_user_message=True,
    )

    capability = PerceptionSessionCapability()
    config = SimpleNamespace(
        config=SimpleNamespace(api_config=_FakePerceptionApiConfig()),
    )
    capability._context = SessionRuntimeCapabilityContext(
        mode="stream",
        args=SimpleNamespace(),
        config=config,
        startup=SimpleNamespace(),
        transport=SimpleNamespace(),
        runtime=SimpleNamespace(),
        ui_updates=SimpleNamespace(),
        chat_turn_service=SimpleNamespace(),
        app_runtime=SimpleNamespace(),
    )
    capability.coordinator = coordinator
    capability._plugin_runtime_bound = True

    bound_receivers: list[Any] = []
    monkeypatch.setattr(
        "plugin_system.host.bind_perception_runtime",
        bound_receivers.append,
    )

    dispatcher = ChatCommandDispatcher(
        bindings=ChatCommandBindings(
            submit_text=lambda *_a, **_kw: True,
            can_submit_text=lambda: True,
            shutdown_session=lambda: None,
            resolve_tool_confirmation=lambda *_a: True,
            ui=ChatCommandUiBindings(
                clear_options=lambda: None,
                sync_history=lambda: None,
                notify=lambda _msg: None,
                clear_tool_confirmation=lambda _id: None,
                handle_playback_signal=lambda *_a: None,
                skip_speech=lambda: None,
            ),
            translate=lambda key, **_kw: key,
        ),
        config=config,
        llm_manager=SimpleNamespace(get_messages=lambda: []),
        runtime_asr=SimpleNamespace(),
        chat_turn_service=SimpleNamespace(),
        branch_manager=SimpleNamespace(),
        chat_history=[],
        last_user_message={},
        presentation_queue=SimpleNamespace(),
        capability_commands=capability.command_handlers(),
    )

    assert dispatcher.execute(
        ChatCommandRequest("perception-ingest", {"frame": "abc"})
    ).ok
    coordinator.ingest.assert_called_once_with({"frame": "abc"})

    bad_ingest = dispatcher.execute(ChatCommandRequest("perception-ingest", "bad"))
    assert bad_ingest.ok is False

    assert dispatcher.execute(ChatCommandRequest("perception-clear")).ok
    coordinator.clear.assert_called_once_with()

    assert dispatcher.execute(
        ChatCommandRequest(
            "perception-config-sync",
            {
                "perception_enabled": True,
                "perception_salience_threshold": 0.85,
                "ignored_key": "nope",
            },
        )
    ).ok
    assert config.config.api_config.perception_enabled is True
    assert config.config.api_config.perception_salience_threshold == 0.85
    coordinator._emit_state.assert_called_once_with()

    pre_shutdown = capability.pre_shutdown_action()
    assert pre_shutdown == coordinator.stop
    capability.on_shutdown()
    assert bound_receivers == [None]


def test_llm_worker_executes_custom_turn_context_providers_without_domain_coupling() -> None:
    class _ProactiveHintProvider(BaseTurnContextProvider):
        capability_id = "custom_hint"

        def admit_turn(
            self,
            request: TurnAdmissionRequest,
        ) -> TurnAdmissionDecision | None:
            if request.text == "drop-me":
                return TurnAdmissionDecision(admitted=False, record_user_message=False)
            if request.source == "ambient_sensor":
                return TurnAdmissionDecision(admitted=True, record_user_message=False)
            return None

        def contribute_user_prompt(
            self,
            request: TurnAdmissionRequest,
        ) -> TurnUserPromptContribution | None:
            if request.source == "ambient_sensor":
                return TurnUserPromptContribution(
                    prefix="[传感器事件]",
                    suffix="[请自然回应]",
                )
            return None

    input_queue: Queue[UserInputMessage | None] = Queue()
    dialog_queue: Queue[Any] = Queue()
    presentation_queue: Queue[Any] = Queue()

    input_queue.put(UserInputMessage(text="drop-me", source="ambient_sensor"))
    input_queue.put(UserInputMessage(text="窗外下雨了", source="ambient_sensor"))
    input_queue.put(None)

    llm_manager = MagicMock()
    llm_manager.llm_adapter = MagicMock()
    llm_manager.chat.return_value = (
        '{"character_name":"Alice","speech":"记得带伞。","sprite":"0"}'
    )
    ui_updates = MagicMock()
    ui_updates.chat_history = []
    ui_updates.current_background_path = ""

    runtime = AppRuntime(
        config=SimpleNamespace(
            config=SimpleNamespace(api_config=SimpleNamespace(is_streaming=False))
        ),
        ui_update_manager=ui_updates,
        llm_manager=llm_manager,
        tts_manager=None,
        t2i_manager=None,
        bgm_list=[],
        user_input_queue=input_queue,
        dialog_queue=dialog_queue,
        presentation_queue=presentation_queue,
        text_processor=MagicMock(),
        opencc=MagicMock(),
        chat_turn_service=ChatTurnService(),
        turn_context_pipeline=TurnContextPipeline((_ProactiveHintProvider(),)),
    )
    set_app_runtime(runtime)
    try:
        LLMWorker(input_queue, dialog_queue).run()
    finally:
        set_app_runtime(None)

    assert llm_manager.chat.call_count == 1
    rendered_prompt = llm_manager.chat.call_args.args[0]
    chat_kwargs = llm_manager.chat.call_args.kwargs
    assert "[传感器事件]" in rendered_prompt
    assert "窗外下雨了" in rendered_prompt
    assert "[请自然回应]" in rendered_prompt
    assert chat_kwargs["user_source"] == "ambient_sensor"
    assert chat_kwargs["user_display_text"] == "窗外下雨了"
    ui_updates.record_user_message.assert_not_called()
    dialog = dialog_queue.get_nowait()
    assert dialog.text == "记得带伞。"
