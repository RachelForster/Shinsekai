from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from application.chat.launch_history import (
    _new_history_instance_id,
    persist_confirmed_history_path,
    plan_chat_history_launch,
    resolve_chat_history_path,
)
from application.chat.session_store import (
    load_template_session,
    save_template_session,
)
from application.chat.templates import _history_id_from_scenario
from core.chat_history.storage import ACTIVE_HISTORY_FILENAME


def _state(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        history_dir=str(tmp_path / "history"),
        project_root_dir=str(tmp_path),
        template_dir_path=str(tmp_path / "templates"),
    )


def test_regular_launch_keeps_the_selected_history_path(tmp_path: Path) -> None:
    state = _state(tmp_path)
    selected = tmp_path / "selected-history"
    selected.mkdir()
    (selected / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")

    target = plan_chat_history_launch(
        state,
        {"historyPath": str(selected), "characters": ["Alice"]},
        {"scenario": "scene"},
        start_fresh=False,
    )

    assert target.history_path == selected
    assert target.previous_history_path == selected
    assert target.starts_fresh is False


def test_quick_restart_preserves_explicit_history_and_uses_new_managed_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path)
    Path(state.history_dir).mkdir()
    selected = tmp_path / "imported-history"
    selected.mkdir()
    marker = selected / ACTIVE_HISTORY_FILENAME
    marker.write_text("previous", encoding="utf-8")
    instance_id = "20260831T120000000000Z-a1b2c3d4"
    monkeypatch.setattr(
        "application.chat.launch_history._new_history_instance_id",
        lambda: instance_id,
    )

    target = plan_chat_history_launch(
        state,
        {"historyPath": str(selected), "characters": ["Alice"]},
        {"scenario": "scene"},
        start_fresh=True,
    )

    expected_name = f"{_history_id_from_scenario('scene', ['Alice'])}-{instance_id}"
    assert target.previous_history_path == selected
    assert target.history_path == Path(state.history_dir) / expected_name
    assert target.starts_fresh is True
    assert marker.read_text(encoding="utf-8") == "previous"


def test_empty_scenario_keeps_the_stable_default_identity(tmp_path: Path) -> None:
    state = _state(tmp_path)

    path = resolve_chat_history_path(
        state,
        {"historyPath": "", "characters": ["Alice"]},
        {"scenario": ""},
    )

    assert path.name == _history_id_from_scenario("", ["Alice"])


def test_new_json_path_becomes_a_session_directory_but_legacy_file_is_kept(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    Path(state.history_dir).mkdir()
    template = {"scenario": "scene", "system": "system"}
    new_json_path = Path(state.history_dir) / "manual.json"
    legacy_path = Path(state.history_dir) / "legacy.json"
    legacy_path.write_text("[]", encoding="utf-8")

    assert resolve_chat_history_path(
        state,
        {"historyPath": new_json_path.as_posix()},
        template,
    ) == new_json_path.with_suffix("")
    assert resolve_chat_history_path(
        state,
        {"historyPath": legacy_path.as_posix()},
        template,
    ) == legacy_path


def test_new_history_instance_id_is_path_safe_and_collision_resistant() -> None:
    first = _new_history_instance_id()
    second = _new_history_instance_id()

    assert re.fullmatch(r"\d{8}T\d{12}Z-[0-9a-f]{8}", first)
    assert first != second


def test_confirmed_history_path_is_used_by_resume_last(tmp_path: Path) -> None:
    state = _state(tmp_path)
    save_template_session(
        state.template_dir_path,
        {"history_file": "old-history", "scenario_text": "scene"},
    )
    selected = Path(state.history_dir) / "new-history"

    assert persist_confirmed_history_path(state, selected) is True

    stored = load_template_session(state.template_dir_path)
    assert stored is not None
    assert stored["history_file"] == selected.as_posix()
    assert stored["scenario_text"] == "scene"
