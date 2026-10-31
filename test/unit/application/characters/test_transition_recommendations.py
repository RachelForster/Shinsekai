import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.characters import generate_briefs
from application.characters import transition_recommendations as analysis
from application.chat.conversation_library import recent_character_dialogs
from application.runtime.tasks import _create_task
from config.schema import Character, SpriteTransition
from core.sprite.transitions import sprite_fingerprint
from frontend_bridge_core.sprite_transitions import run_transition_analysis


@pytest.fixture
def subject(tmp_path):
    paths = [tmp_path / f"{index}.png" for index in range(4)]
    for path in paths:
        path.write_bytes(path.name.encode())
    character = Character(
        name="Mika",
        color="#fff",
        sprite_prefix="mika",
        character_setting="Quiet and observant",
        sprites=[{"path": str(path)} for path in paths],
        emotion_tags="1:平静，站立\n2:开心，挥手\n3:生气，抱臂\n4:难过，垂眸",
    )
    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        history_dir=str(tmp_path / "history"),
        template_dir_path=str(tmp_path / "templates"),
        config_manager=SimpleNamespace(
            get_character_by_name=lambda name: character if name == "Mika" else None
        ),
        tasks={},
        task_lock=threading.Lock(),
    )
    return state, character, paths


def dialogs(values):
    return [
        {"text": f"line {index}", "vibe": "", "assetId": value}
        for index, value in enumerate(values)
    ]


def history(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([{"role": "assistant", "content": json.dumps({"dialog": rows})}]),
        encoding="utf-8",
    )


def test_rank_global_frequency_not_rare_conditional_probability(subject, monkeypatch):
    state, _, paths = subject
    monkeypatch.setattr(
        analysis,
        "recent_character_dialogs",
        lambda *a, **k: [dialogs([1, 2, 1, 2, 1, 2, 1, 2]), dialogs([3, 4])],
    )
    llm = Mock(side_effect=AssertionError("Indexed history must not need the LLM"))
    monkeypatch.setattr(analysis, "chat_character_text", llm)
    result = analysis.analyze_transition_recommendations(state, {"name": "Mika"})
    assert result["basis"] == "instructions"
    assert result["dialogCount"] == 10 and result["transitionCount"] == 8
    assert [
        (item["fromPath"], item["toPath"], item["count"]) for item in result["items"]
    ] == [
        (str(paths[0]), str(paths[1]), 4),
        (str(paths[1]), str(paths[0]), 3),
        (str(paths[2]), str(paths[3]), 1),
    ]
    assert result["items"][2]["conditionalProbability"] == 1
    assert result["items"][2]["probability"] == 1 / 8
    assert sum(item["probability"] for item in result["items"]) == 1
    llm.assert_not_called()


def test_hold_duplicate_and_unknown_gap_do_not_invent_changes(subject, monkeypatch):
    state, _, paths = subject
    monkeypatch.setattr(
        analysis,
        "recent_character_dialogs",
        lambda *a, **k: [dialogs([1, -1, 1, 2, None, 3, 3, 1])],
    )
    llm = Mock(return_value='{"assignments":[{"turn":4,"spriteId":null}]}')
    monkeypatch.setattr(analysis, "chat_character_text", llm)
    result = analysis.analyze_transition_recommendations(state, {"name": "Mika"})
    assert result["transitionCount"] == 2
    assert {(item["fromPath"], item["toPath"]) for item in result["items"]} == {
        (str(paths[0]), str(paths[1])),
        (str(paths[2]), str(paths[0])),
    }
    assert llm.call_args.kwargs == {"tools_enabled": False}
    assert result["basis"] == "inferred" and result["inferredDialogCount"] == 0


def test_semantic_history_is_classified_then_counted_by_code(subject, monkeypatch):
    state, _, paths = subject
    rows = dialogs([-1, -1, -1])
    for row, vibe in zip(rows, ["开心", "生气", "开心"]):
        row["vibe"] = vibe
    monkeypatch.setattr(analysis, "recent_character_dialogs", lambda *a, **k: [rows])
    llm = Mock(
        return_value='```json\n{"assignments":[{"turn":0,"spriteId":2},{"turn":1,"spriteId":3},{"turn":2,"spriteId":2}]}\n```'
    )
    monkeypatch.setattr(analysis, "chat_character_text", llm)
    result = analysis.analyze_transition_recommendations(state, {"name": "Mika"})
    assert result["inferredDialogCount"] == result["mappedDialogCount"] == 3
    assert result["transitionCount"] == 2
    assert all(item["probability"] == 0.5 for item in result["items"])
    assert result["items"][0]["fromPath"] == str(paths[1])
    prompt = json.loads(llm.call_args.args[2])
    assert [turn["vibe"] for turn in prompt["turns"]] == ["开心", "生气", "开心"]
    assert all("path" not in sprite for sprite in prompt["sprites"])


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"assignments":[{"turn":0,"spriteId":99}]}',
        '{"assignments":[{"turn":true,"spriteId":1}]}',
        '{"assignments":[{"turn":0,"spriteId":true}]}',
        '{"assignments":[{"turn":0,"spriteId":1},{"turn":0,"spriteId":2}]}',
    ],
)
def test_reject_invalid_inference_without_fabricating_probabilities(
    subject, monkeypatch, raw
):
    state, _, _ = subject
    monkeypatch.setattr(
        analysis, "recent_character_dialogs", lambda *a, **k: [dialogs([None, 2])]
    )
    monkeypatch.setattr(analysis, "chat_character_text", Mock(return_value=raw))
    with pytest.raises(ValueError, match="聊天分析"):
        analysis.analyze_transition_recommendations(state, {"name": "Mika"})


def test_no_history_or_no_changes_is_explicit(subject, monkeypatch):
    state, _, _ = subject
    monkeypatch.setattr(analysis, "recent_character_dialogs", lambda *a, **k: [])
    with pytest.raises(ValueError, match="没有找到"):
        analysis.analyze_transition_recommendations(state, {"name": "Mika"})
    monkeypatch.setattr(
        analysis, "recent_character_dialogs", lambda *a, **k: [dialogs([1, 1, -1])]
    )
    result = analysis.analyze_transition_recommendations(state, {"name": "Mika"})
    assert result["items"] == [] and result["transitionCount"] == 0


def test_require_tags_only_for_inference_and_validate_saved_character(
    subject, monkeypatch
):
    state, character, _ = subject
    character.emotion_tags = ""
    monkeypatch.setattr(
        analysis, "recent_character_dialogs", lambda *a, **k: [dialogs([1, 2])]
    )
    assert (
        analysis.analyze_transition_recommendations(state, {"name": "Mika"})[
            "transitionCount"
        ]
        == 1
    )
    monkeypatch.setattr(
        analysis, "recent_character_dialogs", lambda *a, **k: [dialogs([None, 2])]
    )
    with pytest.raises(ValueError, match="标签"):
        analysis.analyze_transition_recommendations(state, {"name": "Mika"})
    with pytest.raises(ValueError, match="保存角色"):
        analysis.analyze_transition_recommendations(state, {"name": "Missing"})


def test_existing_clip_requires_valid_fingerprints_and_current_frame_count(
    subject, monkeypatch
):
    state, character, paths = subject
    clip = paths[0].parent / "clip.webm"
    clip.write_bytes(b"saved")
    edge = SpriteTransition(
        from_path=str(paths[0]),
        to_path=str(paths[1]),
        path=str(clip),
        from_fingerprint=sprite_fingerprint(paths[0]),
        to_fingerprint=sprite_fingerprint(paths[1]),
        frame_count=22,
    )
    character.sprite_transitions = [edge]
    monkeypatch.setattr(
        analysis, "recent_character_dialogs", lambda *a, **k: [dialogs([1, 2])]
    )
    assert analysis.analyze_transition_recommendations(state, {"name": "Mika"})[
        "items"
    ][0]["existing"]
    edge.frame_count = 5
    assert not analysis.analyze_transition_recommendations(state, {"name": "Mika"})[
        "items"
    ][0]["existing"]
    edge.frame_count = 22
    paths[0].write_bytes(b"changed image")
    assert not analysis.analyze_transition_recommendations(state, {"name": "Mika"})[
        "items"
    ][0]["existing"]


def test_recent_reader_uses_active_branch_and_live_journal_once(subject):
    state, _, _ = subject
    root = Path(state.history_dir)
    session = root / "recent"
    history(
        root / "recent.json",
        [{"character_name": "Mika", "speech": "stale legacy", "sprite": 4}],
    )
    history(
        session / "active.json",
        [
            {
                "character_name": "Other",
                "speech": "unrelated private text",
                "sprite": 4,
            },
            {"character_name": "Mika", "speech": "old", "sprite": 1},
            {
                "character_name": "Mika",
                "speech": "recent",
                "sprite": 2,
                "dialog_id": "id-2",
            },
        ],
    )
    (session / "branches.json").write_text(
        json.dumps({"branches": {"old": {"messages": ["not active"]}}})
    )
    pending = session / "active.json.tmp"
    pending.write_text(
        json.dumps(
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "dialog": [
                            {
                                "character_name": "Mika",
                                "speech": "recent",
                                "sprite": 2,
                                "dialog_id": "id-2",
                            },
                            {"name": "Mika", "text": "latest", "asset_id": 3},
                        ]
                    }
                ),
            }
        )
        + "\n{unfinished",
        encoding="utf-8",
    )
    before = {file: file.read_bytes() for file in root.rglob("*") if file.is_file()}
    result = recent_character_dialogs(state, "Mika", limit=2)
    assert result == [
        [
            {"text": "recent", "vibe": "", "assetId": 2},
            {"text": "latest", "vibe": "", "assetId": 3},
        ]
    ]
    assert {file: file.read_bytes() for file in before} == before


def test_recent_reader_orders_sessions_and_keeps_only_character_tail(subject):
    state, _, _ = subject
    root = Path(state.history_dir)
    old, new = root / "old.json", root / "new.json"
    history(old, [{"character_name": "Mika", "speech": "older", "sprite": 4}])
    history(
        new,
        [
            {"character_name": "Mika", "speech": str(index), "sprite": index + 1}
            for index in range(3)
        ],
    )
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    result = recent_character_dialogs(state, "Mika", limit=2)
    assert [[row["text"] for row in session] for session in result] == [["1", "2"]]


def test_analysis_task_streams_progress_without_generating_video(subject, monkeypatch):
    state, _, _ = subject
    monkeypatch.setattr(
        analysis, "recent_character_dialogs", lambda *a, **k: [dialogs([1, 2])]
    )
    task = _create_task(state, kind="character-transition-analysis", title="analysis")
    result = run_transition_analysis(state, task["id"], {"name": "Mika"})
    assert result["transitionCount"] == 1
    assert state.tasks[task["id"]]["progress"] == 1


def test_analysis_llm_helper_disables_tools(monkeypatch):
    store = SimpleNamespace(
        get_llm_api_config=lambda: (
            "fake",
            "model",
            "https://example.invalid",
            "test-only",
        ),
        merged_llm_factory_kwargs=lambda provider, values: values,
    )
    factory = Mock()
    manager = Mock()
    manager.return_value.chat.return_value = "result"
    monkeypatch.setattr(generate_briefs, "LLMAdapterFactory", factory)
    monkeypatch.setattr(generate_briefs, "LLMManager", manager)
    assert (
        generate_briefs.chat_character_text(
            store, "system", "data", tools_enabled=False
        )
        == "result"
    )
    assert manager.call_args.kwargs["tools_enabled"] is False
