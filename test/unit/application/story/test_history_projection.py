import json

import pytest

from application.story import history_projection
from application.story.history_projection import project_story_history
from core.chat_history.storage import chat_history_active_path, load_branch_state
from test.unit.application.story.test_scene_commit import _persisted_scene, _recover
from test.unit.application.story.test_simple_scene_nodes import _dialogue


def test_projection_migrates_legacy_file_and_keeps_distinct_identical_turns(tmp_path):
    session, _, scene = _persisted_scene(
        tmp_path, _dialogue("等一等"), _dialogue("等一等")
    )
    legacy_path = tmp_path / "old.json"
    prefix = [{"role": "system", "content": "原始系统提示词"}]
    legacy_path.write_text(json.dumps(prefix), encoding="utf-8")
    session.owner_history_path = str(legacy_path)
    for index in range(2):
        scene.handle_free_text(
            "继续", command_id=f"turn-{index}", message_id=f"m-{index}"
        )
    for _ in range(2):
        project_story_history(session)
    active = chat_history_active_path(legacy_path)
    assert active == tmp_path / "old" / "active.json"
    messages = json.loads(active.read_text(encoding="utf-8"))
    assert messages[:1] == prefix
    assert [item["content"] for item in messages[1:]] == [
        "继续",
        "等一等",
        "继续",
        "等一等",
    ]
    assert load_branch_state(legacy_path)["branches"]["main"]["messages"] == messages


def test_recovery_repairs_projection_interrupted_between_files(tmp_path, monkeypatch):
    session, _, scene = _persisted_scene(tmp_path, _dialogue("进去吧", "lobby"))
    scene.handle_free_text("进去", command_id="turn", message_id="m")
    write = history_projection._atomic_write_json

    def fail_branch_write(path, payload):
        if path.name == "branches.json":
            raise OSError("projection interrupted")
        write(path, payload)

    monkeypatch.setattr(history_projection, "_atomic_write_json", fail_branch_write)
    with pytest.raises(OSError, match="projection interrupted"):
        project_story_history(session)
    assert chat_history_active_path(session.owner_history_path).exists()
    recovered, _, _ = _recover(session, scene)
    monkeypatch.setattr(history_projection, "_atomic_write_json", write)
    project_story_history(recovered)
    tree = load_branch_state(session.owner_history_path)
    assert len(tree["branches"]["main"]["messages"]) == 2
    assert tree["branches"]["main"]["history"] == [
        "<b>你</b>：进去",
        "<b>ling</b>：进去吧",
    ]


def test_projection_restores_each_branch_history_and_an_empty_rollback(tmp_path):
    session, _, scene = _persisted_scene(tmp_path, _dialogue("进大厅", "lobby"))
    initial_generation = session.active_branch.generation
    scene.handle_free_text("进去", command_id="turn", message_id="m")
    session.fork("alternate", generation=initial_generation)
    project_story_history(session)
    tree = load_branch_state(session.owner_history_path)
    assert tree["active"] == "alternate"
    assert tree["branches"]["alternate"]["messages"] == []
    assert len(tree["branches"]["main"]["messages"]) == 2
    session.switch_branch("main")
    session.restore_generation(initial_generation)
    project_story_history(session)
    assert (
        json.loads(
            chat_history_active_path(session.owner_history_path).read_text(
                encoding="utf-8"
            )
        )
        == []
    )
