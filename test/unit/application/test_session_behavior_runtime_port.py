"""Focused regression tests for HostSessionRuntimePort, CastingMap, and identity isolation."""

from __future__ import annotations

from queue import Queue
import re
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel
import pytest

from application.session_behavior import (
    CastBinding,
    CastingMap,
    HostSessionRuntimePort,
    SessionBehaviorCapability,
)
from application.session_behavior.plugin_attachment import try_attach_plugin_behavior
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.sqlite_session_store import SqliteSessionStore
from core.chat_history.storage import chat_history_session_dir, open_session_store
from sdk.exception.types import AppError
from sdk.frontend_ui import _bind_frontend_ui_dispatcher
from sdk.manager import PluginManager
from sdk.register import PluginCapabilityRegistry
from sdk.session_behavior import (
    BaseSessionBehavior,
    SessionBehaviorContribution,
    SessionBehaviorInitContext,
)


def test_casting_map_two_pass_and_unified_resolve_display_name() -> None:
    casting = CastingMap(
        (
            CastBinding(character_name="Alice", display_name="Seer", aliases=("Seer", "Oracle")),
            CastBinding(character_name="Alice", display_name="Witch", aliases=("Witch",)),
        )
    )
    b1 = casting.resolve("Oracle")
    b2 = casting.resolve("Witch")
    assert b1 is not None and b2 is not None and b1 is not b2
    assert casting.resolve_display_name("Oracle", b1) == "Seer"
    assert casting.resolve_display_name("Oracle") == "Seer"
    assert casting.resolve_display_name(" Stranger ") == "Stranger"
    assert casting.bound_speaker_names() == ("Seer", "Oracle", "Witch")


def test_runtime_port_complete_llm_decodes_pydantic_non_stream_response(
    monkeypatch,
) -> None:
    class _FakeChoiceMessage(BaseModel):
        content: str

    class _FakeChoice(BaseModel):
        message: _FakeChoiceMessage

    class _FakeChatCompletion(BaseModel):
        # Pydantic BaseModel defines __iter__ (yielding field tuples), NOT Iterator.__next__.
        choices: list[_FakeChoice]

    class _Adapter:
        def get_supported_chat_params(self) -> set[str]:
            return {"temperature", "max_tokens"}

        def chat(self, messages, stream: bool = False, **_kw):
            assert stream is False
            return _FakeChatCompletion(
                choices=[_FakeChoice(message=_FakeChoiceMessage(content="decoded answer"))]
            )

        def decode_response(self, response: Any):
            return SimpleNamespace(content=response.choices[0].message.content)

        def iter_response_stream(self, *_a, **_kw):
            raise AssertionError("Non-stream response must not enter iter_response_stream")

    monkeypatch.setattr(
        "application.session_behavior.runtime_port.LLMAdapterFactory.create_adapter",
        lambda **_kw: _Adapter(),
    )
    cfg = SimpleNamespace(
        config=SimpleNamespace(api_config=SimpleNamespace(temperature=0.5), characters=[]),
        get_llm_api_config=lambda: ("OpenAI", "gpt-test", "https://api.example/v1", "sk-key"),
        merged_llm_factory_kwargs=lambda _provider, base: dict(base),
    )
    port = HostSessionRuntimePort(plugin_id="com.example.game", config=cfg)

    assert port.complete_llm([{"role": "user", "content": "hi"}]) == "decoded answer"


def test_runtime_port_deliver_dialogs_emits_64_hex_ids() -> None:
    queue: Queue[Any] = Queue()
    port = HostSessionRuntimePort(
        plugin_id="com.example.game",
        config=SimpleNamespace(),
        runtime_components=SimpleNamespace(dialog_queue=queue),
    )
    delivered = port.deliver_dialogs(
        [
            {"character_name": "Alice", "speech": "Line one", "sprite": "0"},
            {"character_name": "Alice", "speech": "Line one", "sprite": "0"},
        ]
    )
    assert delivered == 2
    d1 = queue.get_nowait()
    d2 = queue.get_nowait()
    assert re.fullmatch(r"[0-9a-f]{64}", d1.dialog_id)
    assert re.fullmatch(r"[0-9a-f]{64}", d2.dialog_id)
    assert d1.dialog_id != d2.dialog_id


def test_runtime_port_present_and_dismiss_plugin_page() -> None:
    dispatched: list[dict[str, Any]] = []
    port = HostSessionRuntimePort(plugin_id="com.example.game", config=SimpleNamespace())
    _bind_frontend_ui_dispatcher(dispatched.append)
    try:
        board_uuid = port.present_plugin_page("board", title="Board")
        notes_uuid = port.present_plugin_page("notes", title="Notes")
        assert board_uuid and notes_uuid and board_uuid != notes_uuid
        assert dispatched[-2]["pageId"] == "board"
        assert dispatched[-2]["presentationId"] == board_uuid

        # Dismiss by page_id resolves stored UUID rather than forwarding "board".
        port.dismiss_plugin_page("board")
        assert dispatched[-1] == {
            "type": "plugin.page.dismiss",
            "pluginId": "com.example.game",
            "presentationId": board_uuid,
        }

        # Re-dismissing the same page_id is a clean no-op.
        count_before = len(dispatched)
        port.dismiss_plugin_page("board")
        assert len(dispatched) == count_before

        # Dismissing with None pops the latest remaining page (notes).
        port.dismiss_plugin_page(None)
        assert dispatched[-1]["presentationId"] == notes_uuid

        # Explicit presentation_id dismissal also works when presented again.
        second_board = port.present_plugin_page("board")
        port.dismiss_plugin_page(second_board)
        assert dispatched[-1]["presentationId"] == second_board
    finally:
        _bind_frontend_ui_dispatcher(None)


def test_capability_and_plugin_attachment_reject_identity_mismatch(tmp_path) -> None:
    history_arg = str(tmp_path / "shared_hist.json")
    session_dir = chat_history_session_dir(history_arg)
    session_store = open_session_store(history_arg)
    try:
        behavior_store = BehaviorStateStore(session_store, session_dir)  # type: ignore[arg-type]
        behavior_store.initialize_state(
            branch_id="main",
            behavior_id="alpha",
            state={"owner": "alpha"},
        )

        class _BetaBehavior(BaseSessionBehavior):
            behavior_id = "beta"

        cap = SessionBehaviorCapability()
        with pytest.raises(AppError) as cap_err:
            cap.attach_behavior(
                _BetaBehavior(),
                state_store=BehaviorStateStore(SqliteSessionStore(session_dir / "history.db"), session_dir),
                initial_state={"owner": "beta"},
            )
        assert cap_err.value.error_code == "behavior.identity_mismatch"
        assert cap_err.value.http_status == 409
        assert cap.behavior is None

        reg = PluginCapabilityRegistry()
        reg.set_settings_ui_plugin_context("com.example.beta", "1.0.0")
        reg.register_session_behavior(
            SessionBehaviorContribution(behavior_id="beta", factory=lambda _ctx: _BetaBehavior())
        )
        mgr = PluginManager()
        mgr._capabilities = reg
        mgr._instantiated = True
        mgr._initialized = True

        args = SimpleNamespace(history=history_arg, behavior_id="beta", behavior_config="{}")
        startup = SimpleNamespace(plugin_manager=mgr, character_names=("Alice",))
        with pytest.raises(AppError) as attach_err:
            try_attach_plugin_behavior(
                cap,
                args=args,
                config=SimpleNamespace(config=SimpleNamespace(characters=[])),
                startup=startup,
                runtime_components=None,
                app_runtime=None,
            )
        assert attach_err.value.error_code == "behavior.identity_mismatch"
        assert cap.behavior is None
        assert cap.runtime_port is None
        assert behavior_store.get_latest_state("main").behavior_id == "alpha"  # type: ignore[union-attr]
    finally:
        session_store.close()
