"""Unit tests for Novel Theater document, casting, launch, and library use cases."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.llm.template_generator import TemplateGenerator
from application.chat.conversation_library import (
    _details,
    conversation_launch_payload,
    list_conversations,
)
from application.novel_theater import (
    build_novel_system_template,
    delete_novel_document,
    extract_novel_cast,
    get_novel_document_detail,
    import_novel_document,
    list_novel_documents,
    materialize_novel_session_binding,
    prepare_novel_launch,
    rollback_novel_session_binding,
    save_novel_casting,
)
from application.session_behavior.capability import SessionBehaviorCapability
from application.session_behavior.protocol import CommandResolution
from application.session_behavior.runtime_binding import (
    after_behavior_transition_committed,
)
from config.config_manager import ConfigManager
from config.schema import ApiConfig, AppConfig, SystemConfig
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.sqlite_session_store import close_all_session_stores
from core.chat_history.storage import (
    chat_history_active_path,
    chat_history_session_dir,
    legacy_active_history_branch,
    open_session_store,
)
from sdk.exception.types import AppError
from test.mocks import MockLLMAdapter


def _isolated_config_manager() -> ConfigManager:
    cfg = object.__new__(ConfigManager)
    cfg._config = AppConfig(
        characters=[],
        background_list=[],
        api_config=ApiConfig(),
        system_config=SystemConfig(ui_language="zh_CN"),
    )
    cfg._characters_revision = ""
    cfg._API_CONFIG_PATH = Path("nonexistent-test-api.yaml")
    return cfg


def _make_state(tmp_path: Path, config_manager: ConfigManager | None = None) -> SimpleNamespace:
    cfg_mgr = config_manager or _isolated_config_manager()
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    hist_dir = tmp_path / "chat_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        project_root_dir=str(tmp_path),
        template_dir_path=str(tpl_dir),
        history_dir=str(hist_dir),
        config_manager=cfg_mgr,
        template_generator=TemplateGenerator(),
        chat_session={},
    )


def _sample_novel_txt(tmp_path: Path) -> Path:
    path = tmp_path / "mist_harbor.txt"
    path.write_text(
        "Chapter 1 The Bell\n\nLin entered the foggy dockside station at dawn.\n"
        "\"Is anyone awake?\" she asked.\n\n"
        "Chapter 2 The Lantern\n\nMio held a brass lantern near the pier.\n"
        "\"The ferry leaves before noon,\" Mio whispered.\n",
        encoding="utf-8",
    )
    return path


def test_import_list_detail_and_delete_protection(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    novel_path = _sample_novel_txt(tmp_path)

    detail = import_novel_document(state, novel_path, title="Mist Harbor")
    doc_id = detail["manifest"]["docId"]
    assert detail["manifest"]["title"] == "Mist Harbor"
    assert len(detail["chapters"]) >= 2
    assert len(list_novel_documents(state)) == 1
    assert get_novel_document_detail(state, doc_id)["manifest"]["docId"] == doc_id

    payload = prepare_novel_launch(
        state,
        {"docId": doc_id, "casting": [], "startChapterIndex": 1},
    )
    assert payload["behaviorId"] == "novel_theater"
    assert payload["startChapterIndex"] == 1
    assert payload["characters"] == []
    assert payload["showInitialSprite"] is False
    assert payload["memoryMode"] == "isolated"

    # Preparing a launch payload must be side-effect-free (no pre-launch disk binding).
    session_dir = chat_history_session_dir(payload["historyPath"])
    assert not session_dir.exists()
    assert not (session_dir / "document-binding.json").exists()

    pure_system = build_novel_system_template(state, payload)
    assert pure_system.strip()

    # Materializing the binding protects the document; rolling back unblocks deletion.
    handle = materialize_novel_session_binding(state, payload, payload["historyPath"])
    assert handle is not None
    assert (session_dir / "document-binding.json").is_file()

    with pytest.raises(AppError) as in_use_exc:
        delete_novel_document(state, doc_id)
    assert in_use_exc.value.error_code == "novel.document_in_use"

    rollback_novel_session_binding(handle)
    assert not (session_dir / "document-binding.json").exists()

    removed = delete_novel_document(state, doc_id)
    assert removed == {"ok": True, "docId": doc_id}
    assert list_novel_documents(state) == []


def test_extract_novel_cast_parses_json_and_matches_local_characters(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _isolated_config_manager()
    chars = [
        SimpleNamespace(name="Lin", character_brief="Traveler"),
        SimpleNamespace(name="Mio", character_brief="Keeper"),
    ]
    monkeypatch.setattr(cfg.config, "characters", chars)
    monkeypatch.setattr(
        cfg,
        "get_character_by_name",
        lambda name: next((c for c in chars if c.name == name), None),
    )
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)
    state = _make_state(tmp_path, cfg)
    detail = import_novel_document(state, _sample_novel_txt(tmp_path))
    doc_id = detail["manifest"]["docId"]

    adapter = MockLLMAdapter(
        responses=[
            "```json\n"
            '[{"name": "Lin", "aliases": ["Miss Lin"], "role": "protagonist", '
            '"description": "Lead investigator", "isFirstPerson": false}, '
            '{"name": "Harbor Guard", "aliases": [], "role": "supporting", '
            '"description": "Minor NPC", "isFirstPerson": false}]\n'
            "```"
        ]
    )
    result = extract_novel_cast(state, doc_id, adapter=adapter)
    assert result["docId"] == doc_id
    assert len(result["characters"]) == 2
    assert result["characters"][0]["suggestedCharacter"] == "Lin"
    assert result["characters"][1]["suggestedCharacter"] == ""
    assert [c["name"] for c in result["availableCharacters"]] == ["Lin", "Mio"]


def test_prepare_launch_bound_cast_library_and_save_casting(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _isolated_config_manager()
    lin_char = SimpleNamespace(
        name="Lin",
        character_brief="Traveler",
        character_setting="Secret Local RPG Lore",
        personality="Calm",
        speaking_style="Direct",
        relationship="",
        sprites=[{"path": "lin.png"}],
        sprite_groups={},
    )
    ye_host = SimpleNamespace(
        name="HostActorZero",
        character_brief="Local Host Brief",
        character_setting="Unrelated RPG Setting XYZ",
        personality="Quiet",
        speaking_style="Concise",
        relationship="",
        sprites=[{"path": "host.png"}],
        sprite_groups={},
    )
    char_map = {"Lin": lin_char, "HostActorZero": ye_host}
    monkeypatch.setattr(cfg.config, "characters", [lin_char, ye_host])
    monkeypatch.setattr(
        cfg,
        "get_character_by_name",
        lambda name: char_map.get(name),
    )
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)
    state = _make_state(tmp_path, cfg)
    detail = import_novel_document(state, _sample_novel_txt(tmp_path))
    doc_id = detail["manifest"]["docId"]

    isolated_payload = prepare_novel_launch(
        state,
        {
            "docId": doc_id,
            "nameMode": "story",
            "casting": [
                {
                    "sourceName": "YeWenjie",
                    "aliases": ["Ye"],
                    "targetCharacter": "HostActorZero",
                    "role": "protagonist",
                }
            ],
        },
    )
    isolated_system = build_novel_system_template(state, isolated_payload)
    assert "YeWenjie" in isolated_system
    assert "HostActorZero" not in isolated_system
    assert "Unrelated RPG Setting XYZ" not in isolated_system
    assert "YeWenjie" in isolated_payload["scenario"]
    assert "HostActorZero" not in isolated_payload["scenario"]
    assert isolated_payload["casting"]["bindings"][0]["displayName"] == "YeWenjie"

    payload = prepare_novel_launch(
        state,
        {
            "docId": doc_id,
            "nameMode": "story",
            "casting": [
                {
                    "sourceName": "Miss Lin",
                    "aliases": ["Lina"],
                    "targetCharacter": "Lin",
                    "role": "protagonist",
                }
            ],
        },
    )
    assert payload["characters"] == ["Lin"]
    assert payload["showInitialSprite"] is False
    assert "Miss Lin" in payload["scenario"]

    # Persist conversation record using file-backed conversation folder
    from application.chat.conversation_library import remember_conversation

    history_path = Path(payload["historyPath"])
    materialize_novel_session_binding(state, payload, history_path)
    remember_conversation(state, history_path, payload)

    conversations = list_conversations(state)
    assert len(conversations) == 1
    assert conversations[0]["kind"] == "novel"
    assert conversations[0]["novelDocId"] == doc_id
    assert conversations[0]["behaviorId"] == "novel_theater"
    assert conversations[0]["memoryMode"] == "isolated"
    conv_id = conversations[0]["id"]

    # Idle save_novel_casting updates metadata and SQLite snapshot
    updated_summary = save_novel_casting(
        state,
        conv_id,
        [{"sourceName": "Harbor Girl", "aliases": ["Hina"], "targetCharacter": "Lin"}],
    )
    assert updated_summary["castEntries"][0]["sourceName"] == "Harbor Girl"
    session_dir = chat_history_session_dir(history_path)
    close_all_session_stores()

    # Live session save_novel_casting delegates strictly via behavior-command without pre-mutating SQLite
    store = open_session_store(history_path)
    behavior_store = BehaviorStateStore(store, session_dir)
    capability = SessionBehaviorCapability(branch_id_provider=lambda: "main")
    from application.novel_theater.behavior import NovelTheaterBehavior
    from core.document import DocumentRepository
    from core.storage.layout import StorageLayout

    repo = DocumentRepository(StorageLayout(tmp_path))
    manifest = repo.get_manifest(doc_id)
    assert manifest is not None
    chapters = repo.read_chapters(doc_id)
    chunks = repo.read_chunks(doc_id)
    from application.novel_theater import build_chapter_toc_entries

    toc = build_chapter_toc_entries(chapters, chunks)

    queued_prompts: list[str] = []

    class _DummyRunner:
        def on_transition_committed(self, **_kwargs):
            return None

        def cancel_active(self, **_kwargs):
            return None

        def queue_system_prompt_update(
            self, *, branch_id: str, target_state_version: int, system_prompt: str
        ) -> None:
            del branch_id, target_state_version
            queued_prompts.append(system_prompt)

    behavior = NovelTheaterBehavior(
        manifest=manifest,
        chapters=chapters,
        chunks=chunks,
        toc_entries=toc,
        turn_runner=_DummyRunner(),  # type: ignore[arg-type]
    )
    snap_before = behavior_store.get_latest_state("main")
    assert snap_before is not None
    capability.attach_behavior(
        behavior,
        state_store=behavior_store,
        initial_state=snap_before.state,
        branch_id="main",
    )
    state.chat_session = {"historyPath": history_path.as_posix()}

    monkeypatch.setattr(
        "application.chat.composition._chat_snapshot",
        lambda _state: {"behavior": capability.snapshot_payload()},
    )
    monkeypatch.setattr(
        "application.chat.composition._handle_chat_command",
        lambda _state, cmd: capability.handle_behavior_command(cmd["payload"]),
    )

    save_novel_casting(
        state,
        conv_id,
        [{"sourceName": "LiveRole", "aliases": [], "targetCharacter": "Lin"}],
    )
    snap_after = behavior_store.get_latest_state(legacy_active_history_branch(history_path))
    assert snap_after is not None
    assert snap_after.state_version == snap_before.state_version + 1
    assert snap_after.state["castEntries"][0]["sourceName"] == "LiveRole"
    assert queued_prompts and "LiveRole" in queued_prompts[-1]

    # Rejected synchronous command (e.g. behavior.busy) leaves metadata & SQLite intact.
    monkeypatch.setattr(
        "application.chat.composition._handle_chat_command",
        lambda _state, _cmd: CommandResolution(
            status="rejected",
            error_code="behavior.busy",
            error_message="Generating beat.",
        ),
    )
    with pytest.raises(AppError) as busy_exc:
        save_novel_casting(
            state,
            conv_id,
            [{"sourceName": "RejectedRole", "aliases": [], "targetCharacter": "Lin"}],
        )
    assert busy_exc.value.error_code == "behavior.busy"
    after_reject_snap = behavior_store.get_latest_state(legacy_active_history_branch(history_path))
    assert after_reject_snap is not None
    assert after_reject_snap.state["castEntries"][0]["sourceName"] == "LiveRole"

    # Stream ACK path: failed ACK aborts metadata write; successful ACK passes refreshed systemPrompt.
    sent_commands: list[dict] = []

    class _FakeStream:
        def __init__(self, *, ok: bool) -> None:
            self.ok = ok

        def send_command_and_wait_ack(self, session_id: str, command: dict, *, timeout: float = 5.0) -> dict:
            sent_commands.append({"session_id": session_id, "command": command, "timeout": timeout})
            if not self.ok:
                return {
                    "delivered": True,
                    "ok": False,
                    "timedOut": False,
                    "disconnected": False,
                    "error": "Stale state",
                    "errorCode": "behavior.stale_state_version",
                    "httpStatus": 409,
                }
            return {
                "delivered": True,
                "ok": True,
                "timedOut": False,
                "disconnected": False,
                "error": "",
                "errorCode": "",
                "httpStatus": 0,
            }

    state.chat_session = {"historyPath": history_path.as_posix(), "sessionId": "sess-1"}
    state.chat_stream = _FakeStream(ok=False)
    with pytest.raises(AppError) as ack_err:
        save_novel_casting(
            state,
            conv_id,
            [{"sourceName": "AckFailRole", "aliases": [], "targetCharacter": "Lin"}],
        )
    assert ack_err.value.error_code == "behavior.stale_state_version"
    assert ack_err.value.http_status == 409
    assert list_conversations(state)[0]["castEntries"][0]["sourceName"] == "LiveRole"

    state.chat_stream = _FakeStream(ok=True)
    updated_live = save_novel_casting(
        state,
        conv_id,
        [{"sourceName": "AckOkRole", "aliases": [], "targetCharacter": "Lin"}],
    )
    assert updated_live["castEntries"][0]["sourceName"] == "AckOkRole"
    persisted_launch = conversation_launch_payload(state, conv_id)
    assert "AckOkRole" in persisted_launch["scenario"]
    assert "AckOkRole" in persisted_launch["system"]
    assert sent_commands[-1]["command"]["payload"]["payload"]["systemPrompt"].strip()

    # Also verify _details directly when only document-binding.json exists
    detail_only = _details({"historyPath": history_path.as_posix()})
    assert detail_only["kind"] == "novel"
    assert detail_only["novelDocId"] == doc_id
    close_all_session_stores()


def test_launch_chat_rolls_back_fresh_novel_binding_on_launch_failure(
    tmp_path: Path, monkeypatch
) -> None:
    from application.chat.composition import LAUNCH_FAILURE_PREFIX
    from frontend_bridge_core.chat_session import launch_chat

    state = _make_state(tmp_path)
    state.chat_stream = None
    state.resource_urls = SimpleNamespace(
        avatar_url=lambda *_a: "",
        media_url=lambda *_a: "",
    )
    detail = import_novel_document(state, _sample_novel_txt(tmp_path))
    doc_id = detail["manifest"]["docId"]
    payload = prepare_novel_launch(state, {"docId": doc_id, "casting": []})
    payload["system"] = build_novel_system_template(state, payload)
    history_path = Path(payload["historyPath"])
    session_dir = chat_history_session_dir(history_path)
    assert not session_dir.exists()

    monkeypatch.setattr("frontend_bridge_core.chat_session._chat_process_running", lambda: False)
    monkeypatch.setattr("frontend_bridge_core.chat_session._chat_runtime_closing", lambda _s: False)
    monkeypatch.setattr("frontend_bridge_core.chat_session._chat_runtime_mode", lambda _s: "legacy")
    monkeypatch.setattr("frontend_bridge_core.chat_session.configure_mobile_access", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        "frontend_bridge_core.chat_session._launch_runtime_chat",
        lambda *_a, **_kw: f"{LAUNCH_FAILURE_PREFIX} boom",
    )

    with pytest.raises(RuntimeError):
        launch_chat(state, payload)

    assert not (session_dir / "document-binding.json").exists()

    # An existing pre-bound session must NOT be rolled back if a resume attempt fails.
    existing_handle = materialize_novel_session_binding(state, payload, history_path)
    assert existing_handle is not None
    with pytest.raises(RuntimeError):
        launch_chat(state, payload)
    assert (session_dir / "document-binding.json").is_file()

    rollback_novel_session_binding(existing_handle)
    assert delete_novel_document(state, doc_id) == {"ok": True, "docId": doc_id}
    close_all_session_stores()


def test_regenerate_launch_system_preserves_novel_theater_prompts() -> None:
    from application.chat.conversation_mutations import regenerate_launch_system

    called = False

    def _boom(*_args, **_kwargs):
        nonlocal called
        called = True
        return "GENERIC", {}

    state = SimpleNamespace(
        template_generator=SimpleNamespace(generate_chat_template=_boom),
        config_manager=SimpleNamespace(),
    )
    by_behavior = {
        "behaviorId": "novel_theater",
        "characters": ["Lin"],
        "system": "NOVEL_PROMPT",
    }
    by_doc = {
        "novelDocId": "doc_123",
        "characters": ["Lin"],
        "system": "NOVEL_DOC_PROMPT",
    }

    assert regenerate_launch_system(state, by_behavior) is False
    assert by_behavior["system"] == "NOVEL_PROMPT"
    assert regenerate_launch_system(state, by_doc) is False
    assert by_doc["system"] == "NOVEL_DOC_PROMPT"
    assert called is False
