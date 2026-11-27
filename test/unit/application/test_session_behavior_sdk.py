"""Unit tests for the public SessionBehavior SDK, HostSessionRuntimePort, and wiring."""

from __future__ import annotations

from queue import Queue
from types import SimpleNamespace
from typing import Any

import pytest

from application.chat.capabilities.contracts import (
    SessionRuntimeCapabilityContext,
    StreamingWiringCapabilityContext,
)
from application.chat.host.launch_preparation import ChatLaunchPreparation
from application.chat.runtime.commands import (
    ChatCommandBindings,
    ChatCommandDispatcher,
    ChatCommandRequest,
    ChatCommandUiBindings,
)
from application.chat.runtime.launch_args import (
    _parse_chat_launch_config,
    build_chat_arg_parser,
)
from application.plugins.session_behaviors import (
    find_session_behavior_plugin_id,
    list_session_behavior_contributions,
)
from application.session_behavior import (
    BehaviorTransition,
    CastBinding,
    CastingMap,
    HostSessionRuntimePort,
    SessionBehaviorCapability,
)
from sdk.messages import LLMDialogMessage
from sdk.register import PluginCapabilityRegistry
from sdk.session_behavior import (
    BaseSessionBehavior,
    CharacterSummaryView,
    InteractionPolicy,
    SessionBehaviorContribution,
    SessionBehaviorInitContext,
    SessionRuntimePort,
    UserInputInterceptResult,
)


class _WerewolfLikeBehavior(BaseSessionBehavior):
    behavior_id = "werewolf_game"

    def __init__(self, init_ctx: SessionBehaviorInitContext) -> None:
        self.init_ctx = init_ctx
        self.bound_runtime: SessionRuntimePort | None = None
        self.ready_called = 0
        self.shutdown_called = 0
        self.intercepted_inputs: list[tuple[str, tuple[Any, ...]]] = []

    def on_runtime_bound(self, runtime: SessionRuntimePort) -> None:
        self.bound_runtime = runtime

    def build_initial_state(self, context: SessionBehaviorInitContext) -> dict[str, Any]:
        return {
            "phase": "day",
            "difficulty": context.config.get("difficulty", "normal"),
            "notes": [],
        }

    def describe_state(self, state, state_version: int):
        from sdk.session_behavior import BehaviorStateEnvelope

        return BehaviorStateEnvelope(
            behavior_id=self.behavior_id,
            state_version=state_version,
            stage_policy=InteractionPolicy(
                hide_input_layer=False,
                allow_free_text_interject=False,
                allow_unbound_speakers=True,
            ),
            hud={"phase": state.get("phase"), "notes": list(state.get("notes") or [])},
        )

    def on_session_ready(self, *, state, state_version: int, branch_id: str, runtime):
        del branch_id, runtime
        self.ready_called += 1
        return BehaviorTransition(next_state={**dict(state), "phase": "night"})

    def on_user_input(
        self,
        text: str,
        *,
        attachments=(),
        state,
        state_version: int,
        branch_id: str,
        runtime,
    ):
        del state_version, branch_id, runtime
        self.intercepted_inputs.append((text, tuple(attachments)))
        if text.startswith("/vote "):
            target = text.split(" ", 1)[1].strip()
            notes = [*list(state.get("notes") or []), f"voted:{target}"]
            return UserInputInterceptResult(
                handled=True,
                transition=BehaviorTransition(next_state={**dict(state), "notes": notes}),
            )
        if text.startswith("/rewrite "):
            return UserInputInterceptResult(handled=False, passthrough_text="rewritten")
        return None

    def on_shutdown(self) -> None:
        self.shutdown_called += 1


def test_cast_binding_display_name_roundtrip_and_resolution() -> None:
    casting = CastingMap(
        (CastBinding(character_name="Alice", aliases=("Heroine",), display_name="Seer"),)
    )
    restored = CastingMap.from_dict(casting.to_dict())
    assert restored.bindings[0].display_name == "Seer"
    assert restored.resolve_display_name("Heroine") == "Seer"
    assert restored.resolve_display_name(" Villager ") == "Villager"


def test_registry_plugin_manager_and_application_query_helpers() -> None:
    from sdk.manager import PluginManager

    reg = PluginCapabilityRegistry()
    reg.set_settings_ui_plugin_context("com.example.game", "1.0.0")
    contribution = SessionBehaviorContribution(
        behavior_id="werewolf",
        factory=_WerewolfLikeBehavior,
        name="Werewolf",
        description="Social deduction game",
        default_config={"players": 6},
    )
    reg.register_session_behavior(contribution)

    with pytest.raises(ValueError, match="duplicate session behavior"):
        reg.register_session_behavior(contribution)
    with pytest.raises(ValueError, match="behavior_id"):
        reg.register_session_behavior(
            SessionBehaviorContribution(behavior_id="", factory=_WerewolfLikeBehavior)
        )

    mgr = PluginManager()
    mgr._capabilities = reg
    mgr._instantiated = True
    mgr._initialized = True
    assert mgr.find_session_behavior("werewolf").plugin_id == "com.example.game"
    assert len(mgr.collect_session_behaviors()) == 1


def test_application_plugins_session_behaviors_helpers(monkeypatch) -> None:
    mgr = SimpleNamespace(
        collect_session_behaviors=lambda: [
            SessionBehaviorContribution(
                behavior_id="werewolf",
                factory=_WerewolfLikeBehavior,
                plugin_id="com.example.game",
                name="Werewolf",
                description="Mystery",
                default_config={"players": 8},
            )
        ],
        find_session_behavior=lambda bid: (
            SessionBehaviorContribution(
                behavior_id="werewolf",
                factory=_WerewolfLikeBehavior,
                plugin_id="com.example.game",
            )
            if bid == "werewolf"
            else None
        ),
    )
    monkeypatch.setattr("application.plugins.session_behaviors.get_plugin_manager", lambda: mgr)

    items = list_session_behavior_contributions()
    assert items == [
        {
            "behaviorId": "werewolf",
            "pluginId": "com.example.game",
            "name": "Werewolf",
            "description": "Mystery",
            "defaultConfig": {"players": 8},
        }
    ]
    assert find_session_behavior_plugin_id("werewolf") == "com.example.game"
    assert find_session_behavior_plugin_id("unknown") == ""


def test_plugin_behavior_attach_ready_and_user_input_interception(tmp_path) -> None:
    from sdk.manager import PluginManager

    reg = PluginCapabilityRegistry()
    reg.set_settings_ui_plugin_context("com.example.game", "1.0.0")
    reg.register_session_behavior(
        SessionBehaviorContribution(
            behavior_id="werewolf_game",
            factory=_WerewolfLikeBehavior,
            default_config={"difficulty": "normal"},
        )
    )
    mgr = PluginManager()
    mgr._capabilities = reg
    mgr._instantiated = True
    mgr._initialized = True

    events: list[dict[str, Any]] = []
    submitted: list[str] = []
    cap = SessionBehaviorCapability(emit_event=events.append)
    history_arg = str(tmp_path / "sess.json")
    cfg = SimpleNamespace(config=SimpleNamespace(characters=[]))
    startup = SimpleNamespace(
        plugin_manager=mgr,
        llm_manager=SimpleNamespace(),
        character_names=("Alice",),
    )
    args = SimpleNamespace(
        history=history_arg,
        behavior_id="werewolf_game",
        behavior_config='{"difficulty": "hard"}',
    )

    cap.configure_session_runtime(
        SessionRuntimeCapabilityContext(
            mode="streaming",
            args=args,
            config=cfg,
            startup=startup,
            transport=SimpleNamespace(emit=events.append),
            runtime=SimpleNamespace(dialog_queue=Queue()),
            ui_updates=None,
            chat_turn_service=None,
            app_runtime=None,
        )
    )
    assert isinstance(cap.behavior, _WerewolfLikeBehavior)
    assert cap.behavior.init_ctx.config["difficulty"] == "hard"
    assert cap.behavior.bound_runtime is cap.runtime_port
    assert events[-1]["behavior"]["hud"]["phase"] == "day"

    cap.on_session_ready()
    assert cap.behavior.ready_called == 1
    assert events[-1]["behavior"]["hud"]["phase"] == "night"
    assert events[-1]["behavior"]["stateVersion"] == 2

    dispatcher = ChatCommandDispatcher(
        bindings=ChatCommandBindings(
            submit_text=lambda text, **_kw: submitted.append(text),
            can_submit_text=lambda: True,
            shutdown_session=lambda: None,
            resolve_tool_confirmation=lambda _i, _a: False,
            ui=ChatCommandUiBindings(
                clear_options=lambda: None,
                sync_history=lambda: None,
                notify=lambda _m: None,
                clear_tool_confirmation=lambda _i: None,
            ),
            translate=lambda key, **_kw: key,
        ),
        config=cfg,
        llm_manager=startup.llm_manager,
        runtime_asr=SimpleNamespace(pause_for_turn=lambda: None),
        chat_turn_service=SimpleNamespace(),
        chat_history=[],
        last_user_message={},
        presentation_queue=Queue(),
        history_argument=history_arg,
    )
    cap.bind_streaming_session(
        StreamingWiringCapabilityContext(
            bindings=SimpleNamespace(command_dispatcher=dispatcher),
            app_runtime=None,
        )
    )

    # Intercepted even though allow_free_text_interject=False!
    res = dispatcher.execute(
        ChatCommandRequest(type="send-message", payload={"text": "/vote Bob", "attachments": []})
    )
    assert res.ok is True
    assert submitted == []
    assert events[-1]["behavior"]["hud"]["notes"] == ["voted:Bob"]
    assert events[-1]["behavior"]["stateVersion"] == 3

    # Non-intercepted text hits free-text guard (disabled -> rejected gracefully)
    assert dispatcher.execute(ChatCommandRequest(type="send-message", payload="plain chat")).ok is False

    # Rewriting passthrough text works when free-text is allowed
    from core.chat_history.behavior_state_store import BehaviorStateStore
    from core.chat_history.sqlite_session_store import SqliteSessionStore
    from sdk.session_behavior import BehaviorStateEnvelope

    class _PassthroughBehavior(_WerewolfLikeBehavior):
        def describe_state(self, state, state_version: int):
            return BehaviorStateEnvelope(
                behavior_id=self.behavior_id, state_version=state_version,
                stage_policy=InteractionPolicy(allow_free_text_interject=True),
            )

    cap.detach_behavior()
    pass_store = BehaviorStateStore(SqliteSessionStore(":memory:"), None)
    cap.attach_behavior(_PassthroughBehavior(SessionBehaviorInitContext(behavior_id="p", plugin_id="com.example.game")), state_store=pass_store, initial_state={})
    assert dispatcher.execute(ChatCommandRequest(type="send-message", payload="/rewrite raw")).ok is True
    assert submitted == ["rewritten"]
    cap.on_shutdown()
    assert cap.behavior.shutdown_called == 1


def test_host_session_runtime_port_isolation_dialogs_and_async_commit(
    tmp_path, monkeypatch
) -> None:
    created_adapters: list[Any] = []

    class _IsolationAdapter:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.calls: list[list[dict[str, Any]]] = []
            created_adapters.append(self)

        def get_supported_chat_params(self) -> set[str]:
            return {"temperature", "max_tokens"}

        def chat(self, messages: list[dict[str, Any]], stream: bool = False, **kwargs):
            assert stream is False
            self.calls.append(messages)
            return SimpleNamespace(content=f"reply:{messages[-1]['content']}")

        def decode_response(self, response: Any):
            return SimpleNamespace(content=response.content)

    monkeypatch.setattr(
        "application.session_behavior.runtime_port.LLMAdapterFactory.create_adapter",
        lambda **_kw: _IsolationAdapter(**_kw),
    )

    alice = SimpleNamespace(
        name="Alice",
        display_name="Seer",
        character_brief="Village seer",
        character_setting="",
        emotion_tags="calm,alert",
        sprite_groups=["default", "cloak"],
        refer_audio_path="alice.wav",
        gpt_model_path="",
        sovits_model_path="",
    )
    cfg = SimpleNamespace(
        config=SimpleNamespace(
            api_config=SimpleNamespace(temperature=0.7),
            characters=[alice],
        ),
        get_llm_api_config=lambda: ("OpenAI", "gpt-test", "https://api.example/v1", "sk-secret"),
        merged_llm_factory_kwargs=lambda _provider, base: dict(base),
    )

    events: list[dict[str, Any]] = []
    cap = SessionBehaviorCapability(emit_event=events.append)
    from core.chat_history.behavior_state_store import BehaviorStateStore
    from core.chat_history.sqlite_session_store import SqliteSessionStore

    session_dir = tmp_path / "port_sess"
    session_dir.mkdir()
    store = BehaviorStateStore(SqliteSessionStore(session_dir / "history.db"), session_dir)
    behavior = _WerewolfLikeBehavior(
        SessionBehaviorInitContext(behavior_id="werewolf_game", plugin_id="com.example.game")
    )
    dialog_queue: Queue[LLMDialogMessage] = Queue()
    port = HostSessionRuntimePort(
        plugin_id="com.example.game",
        config=cfg,
        runtime_components=SimpleNamespace(dialog_queue=dialog_queue),
        capability=cap,
    )
    cap.set_runtime_port(port)
    cap.attach_behavior(behavior, state_store=store, initial_state={"phase": "day"})

    # Isolated per-character LLM calls spawn fresh adapters & never expose api_key
    r1 = port.complete_llm([{"role": "system", "content": "You are Wolf"}, {"role": "user", "content": "wolf-turn"}])
    r2 = port.complete_llm([{"role": "system", "content": "You are Seer"}, {"role": "user", "content": "seer-turn"}])
    assert r1 == "reply:wolf-turn"
    assert r2 == "reply:seer-turn"
    assert len(created_adapters) == 2
    assert created_adapters[0] is not created_adapters[1]

    # Read-only character views omit credentials
    chars = port.list_characters()
    assert chars == (
        CharacterSummaryView(
            name="Alice",
            description="Village seer",
            aliases=("Seer",),
            tags=("calm", "alert"),
            sprite_groups=("default", "cloak"),
            has_voice=True,
        ),
    )

    # Dialog delivery sets turn_id=None (safe for DialogMediaWorker) and fresh dialog_id
    count = port.deliver_dialogs(
        [
            {"character_name": "Alice", "speech": "It was dark last night.", "sprite": "0"},
            LLMDialogMessage(character_name="NARR", speech="Dawn breaks.", sprite="-1"),
        ]
    )
    assert count == 2
    first = dialog_queue.get_nowait()
    second = dialog_queue.get_nowait()
    assert first.name == "Alice" and first.turn_id is None and first.dialog_id
    assert second.name == "NARR" and second.turn_id is None and second.dialog_id != first.dialog_id

    # Async commit & custom event
    env = port.commit_async_transition(
        expected_state_version=1,
        transition=BehaviorTransition(next_state={"phase": "vote", "notes": ["done"]}),
    )
    assert env.state_version == 2
    port.emit_custom_event("phase.changed", {"phase": "vote"})
    assert events[-1] == {
        "type": "plugin.behavior.event",
        "pluginId": "com.example.game",
        "eventType": "phase.changed",
        "payload": {"phase": "vote"},
    }


def test_launch_args_and_preparation_preserve_behavior_config(tmp_path) -> None:
    parser = build_chat_arg_parser(lambda k: k)
    parsed = parser.parse_args(
        ["--behavior-id", "werewolf", "--behavior-config", '{"players": 9}']
    )
    assert parsed.behavior_id == "werewolf"
    assert parsed.behavior_config == '{"players": 9}'

    defaults = _parse_chat_launch_config(
        '{"behavior_id": "werewolf", "behavior_config": "{\\"players\\": 9}"}'
    )
    assert defaults["behavior_id"] == "werewolf"
    assert defaults["behavior_config"] == '{"players": 9}'

    from config.schema import SystemConfig

    main_py = tmp_path / "main.py"
    main_py.write_text("print('ok')\n", encoding="utf-8")
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    prep = ChatLaunchPreparation(
        project_root=lambda: tmp_path,
        app_root=lambda _s: tmp_path,
        exe_candidates=lambda _s: [],
        main_py=lambda: main_py,
    )
    state = SimpleNamespace(
        template_dir_path=str(template_dir),
        history_dir=str(tmp_path / "history"),
        chat_session={
            "behaviorId": "werewolf",
            "behaviorConfig": {"players": 9},
            "userDisplayName": "",
        },
        config_manager=SimpleNamespace(
            save_system_config=lambda: None,
            config=SimpleNamespace(
                system_config=SystemConfig(ui_language="zh_CN"),
                api_config=SimpleNamespace(
                    tts_provider="gpt-sovits",
                    knowledge_search_limit=5,
                    memory_auto_enabled=False,
                    memory_extract_interval_turns=5,
                    memory_search_limit=5,
                    memory_recent_buffer_messages=16,
                ),
            ),
        ),
        chat_stream=None,
        auth_token="",
    )
    plan = prep.prepare(
        state,
        character_names=["Alice"],
        history_file=str(tmp_path / "h.json"),
        init_sprite_path="",
        room_id="r1",
        selected_bg="bg",
        system_template="sys",
        user_scenario="scen",
        use_cg=False,
    )
    import json

    launch_cfg = json.loads(plan.environment["SHINSEKAI_CHAT_LAUNCH_CONFIG"])
    assert launch_cfg["behavior_id"] == "werewolf"
    assert json.loads(launch_cfg["behavior_config"]) == {"players": 9}
