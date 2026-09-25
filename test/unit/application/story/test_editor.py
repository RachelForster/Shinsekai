from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from application.story.editor import read_story_document, save_story_document, suggest_story_graph
from application.story.library import list_story_library, prepare_story_launch
from application.story.coordinator import start_or_recover_story_session, clear_story_session
from application.story.project_loader import StoryProjectLoader
from config.feature_flags import FeatureDisabledError, FeatureFlag, FeatureFlagConfigManager
from core.story import AdvanceStoryTurn
from frontend_bridge_core.routes.router import ApiRequest, TaskResponse
from frontend_bridge_core.routes.story_routes import STORY_ROUTES
from test.unit.application.story.test_library import selected_story


def setup_editor(tmp_path):
    state, task, model, repository = selected_story(tmp_path)
    document = read_story_document(state, task["draftPath"])
    return state, document, model, repository


def add_scene(graph):
    graph = deepcopy(graph)
    graph["nodes"][1]["transitions"][0]["to"] = "confrontation"
    graph["nodes"].insert(2, {
        "id": "confrontation", "type": "free_chat_node", "title": "Confrontation",
        "instruction": "Confront the witness with the discovered clue.",
        "transitions": [{"to": "truth-ending", "when": "The witness admits the truth"}],
    })
    return graph


def test_save_new_graph_keeps_original_and_its_progress(tmp_path):
    state, document, _, _ = setup_editor(tmp_path)
    original_path = Path(document["storyPath"])
    original = original_path.read_bytes()
    history = state.history_dir / "save"
    history.mkdir(parents=True)
    (history / "active.json").write_text("{}", encoding="utf-8")
    state.chat_session = {"historyPath": history.as_posix()}
    session = start_or_recover_story_session(state, document["storyPath"], command_id="start")
    session.execute(AdvanceStoryTurn(command_id="advance", expected_revision=session.active_branch.state.revision,
        expected_node_id="school-gate", next_node_id="school-lobby"))
    saved = save_story_document(state, {**document, "title": "Revised", "graph": add_scene(document["graph"])})
    assert saved["version"] == document["version"] + 1
    assert saved["storyPath"] != document["storyPath"]
    assert original_path.read_bytes() == original
    assert read_story_document(state, saved["storyPath"]) == saved
    assert len(list_story_library(state)) == 2
    assert prepare_story_launch(state, document["storyPath"], history.as_posix())["resetHistory"] is False
    with pytest.raises(ValueError, match="不匹配"):
        prepare_story_launch(state, saved["storyPath"], history.as_posix())
    clear_story_session(state)
    recovered = start_or_recover_story_session(state, document["storyPath"], command_id="resume")
    assert recovered.active_branch.state.current_node_id == "school-lobby"


@pytest.mark.parametrize("invalid", ["dangling", "unreachable", "no-ending", "empty-text", "default-target"])
def test_invalid_graph_is_rejected_without_writing(tmp_path, invalid):
    state, document, _, _ = setup_editor(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    graph = deepcopy(document["graph"])
    if invalid == "dangling":
        graph["nodes"][0]["transitions"][0]["to"] = "missing"
    elif invalid == "unreachable":
        graph["nodes"].append({"id": "orphan", "title": "Orphan", "type": "ending_node"})
    elif invalid == "no-ending":
        graph["nodes"][-1].update(type="free_chat_node", instruction="Wait", transitions=[])
    elif invalid == "empty-text":
        graph["nodes"][0]["instruction"] = ""
    else:
        graph["nodes"][0]["defaultTo"] = "truth-ending"
    with pytest.raises(ValueError):
        save_story_document(state, {**document, "graph": graph})
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == before


def test_stale_source_is_rejected(tmp_path):
    state, document, _, _ = setup_editor(tmp_path)
    path = Path(document["storyPath"])
    source = json.loads(path.read_text(encoding="utf-8"))
    source["title"] = "Changed elsewhere"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="源文件已变化"):
        save_story_document(state, document)
    assert not list(path.parent.glob("edited-*.json"))


def test_llm_node_edit_is_scoped_and_does_not_save(tmp_path):
    state, document, _, _ = setup_editor(tmp_path)
    node = {**document["graph"]["nodes"][0], "instruction": "Invite the player cautiously."}
    model = Mock()
    model.complete.return_value = {"node": node, "graph": add_scene(document["graph"]), "summary": "Tone adjusted"}
    state.story_generation_service.model = model
    before = Path(document["storyPath"]).read_bytes()
    result = suggest_story_graph(state, {**document, "scope": "node", "nodeId": node["id"], "instructions": "更谨慎一些"})
    assert result["graph"]["nodes"][0] == node
    assert result["graph"]["nodes"][1:] == document["graph"]["nodes"][1:]
    assert Path(document["storyPath"]).read_bytes() == before
    assert len(list_story_library(state)) == 1
    request = model.complete.call_args.args[0]
    assert request["operation"] == "revise-node"
    assert request["editInstructions"] == "更谨慎一些"
    assert request["synopsis"] == document["authoringBrief"]
    assert request["resourceCatalog"]["characters"][0]["characterSetting"] == "小玲的完整设定"
    assert request["constraints"]["selectedNodeOnly"] is True
    model.complete.return_value["node"]["id"] = "unexpected"
    with pytest.raises(ValueError, match="节点标识"):
        suggest_story_graph(state, {**document, "scope": "node", "nodeId": "school-gate", "instructions": "修改"})


def test_llm_graph_edit_adds_connected_node_and_rejects_invalid_proposals(tmp_path):
    state, document, _, _ = setup_editor(tmp_path)
    model = Mock()
    candidate = add_scene(document["graph"])
    model.complete.return_value = {"graph": candidate, "summary": "Added confrontation"}
    state.story_generation_service.model = model
    request = {**document, "scope": "graph", "instructions": "添加对质场景"}
    result = suggest_story_graph(state, request)
    assert result["graph"] == candidate
    assert result["validation"]["valid"] is True
    assert len(list_story_library(state)) == 1
    candidate["nodes"][0]["transitions"][0]["to"] = "missing"
    with pytest.raises(ValueError):
        suggest_story_graph(state, request)
    assert read_story_document(state, document["storyPath"]) == document


def test_editor_flattens_references_without_losing_authoring_fields(tmp_path):
    state, document, _, _ = setup_editor(tmp_path)
    path = Path(document["storyPath"])
    source = json.loads(path.read_text(encoding="utf-8"))
    graph = source.pop("narrativeGraph")
    (path.parent / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    source["narrativeGraphRef"] = "graph.json"
    source["metadata"]["customAuthorNote"] = "Keep me"
    path.write_text(json.dumps(source), encoding="utf-8")
    document = read_story_document(state, str(path))
    saved = save_story_document(state, {**document, "title": "From references"})
    aggregate = StoryProjectLoader().load_source(saved["storyPath"])
    assert "narrativeGraphRef" not in aggregate
    assert len(aggregate["narrativeGraph"]["nodes"]) == len(graph["nodes"])
    assert aggregate["metadata"]["customAuthorNote"] == "Keep me"


def test_creation_brief_is_kept_for_author_but_not_used_as_play_scenario(tmp_path):
    state, document, model, _ = setup_editor(tmp_path)
    assert document["authoringBrief"] == model.requests[0]["synopsis"]
    path = Path(document["storyPath"])
    source = json.loads(path.read_text(encoding="utf-8"))
    assert "scenario" not in source["metadata"]["resourceBindings"]
    source["metadata"]["resourceBindings"]["scenario"] = "The culprit is Ling; reveal it in the ending."
    path.write_text(json.dumps(source), encoding="utf-8")
    source["metadata"].pop("authoringBrief", None)
    path.write_text(json.dumps(source), encoding="utf-8")
    assert "culprit" in read_story_document(state, str(path))["authoringBrief"]
    launch = prepare_story_launch(state, str(path))
    assert "culprit" not in launch["scenario"]
    assert document["authoringBrief"] not in launch["scenario"]


def test_editor_routes_are_registered_and_suggestions_run_as_tasks(tmp_path):
    state, document, _, _ = setup_editor(tmp_path)
    routes = {route.name: route for route in STORY_ROUTES}
    request = lambda name, body: ApiRequest(state=state, method="POST", path=routes[name].pattern, query={}, params={}, body=body)
    assert routes["story.editor.read"].handler(request("story.editor.read", document)).data == document
    assert isinstance(routes["story.editor.suggest"].handler(request("story.editor.suggest", document)), TaskResponse)
    with pytest.raises((PermissionError, ValueError)):
        read_story_document(state, str(tmp_path.parent))
    state.config_manager.feature_flags = FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: False})
    with pytest.raises(FeatureDisabledError):
        save_story_document(state, document)


def setup_generated_profile(tmp_path):
    state, document, _, _ = setup_editor(tmp_path)
    path = Path(document["storyPath"])
    source = json.loads(path.read_text(encoding="utf-8"))
    profile = path.parent / "characters" / "witness.yaml"
    profile.parent.mkdir(exist_ok=True)
    profile.write_text("name: Witness\ncharacterSetting: Original witness\n", encoding="utf-8")
    source["cast"]["characters"][0]["source"] = {"type": "author-generated", "path": "characters/witness.yaml"}
    path.write_text(json.dumps(source), encoding="utf-8")
    document = read_story_document(state, str(path))
    return state, document, profile


def test_saved_version_keeps_generated_profiles_when_original_is_regenerated(tmp_path):
    state, document, profile = setup_generated_profile(tmp_path)
    saved = save_story_document(state, document)
    new_source = StoryProjectLoader().load_source(saved["storyPath"])
    copied = Path(saved["storyPath"]).parent / new_source["cast"]["characters"][0]["source"]["path"]
    assert copied != profile
    assert copied.read_bytes() == profile.read_bytes()
    profile.write_text("name: Replacement\n", encoding="utf-8")
    assert "Original witness" in copied.read_text(encoding="utf-8")


def test_profiles_are_synced_and_atomically_published_before_manifest(tmp_path, monkeypatch):
    from application.story import editor

    state, document, profile = setup_generated_profile(tmp_path)
    rename = editor._durable_rename
    fsync = editor.os.fsync
    events = []

    def sync(fd):
        fsync(fd)
        events.append("sync")

    def publish(temporary, destination):
        assert events[-1] == "sync"
        assert not destination.exists()
        if "-character-" in destination.name:
            assert temporary.read_bytes() == profile.read_bytes()
            assert not list(destination.parent.glob("edited-*.json"))
            kind = "profile"
        else:
            source = json.loads(temporary.read_text(encoding="utf-8"))
            copied = destination.parent / source["cast"]["characters"][0]["source"]["path"]
            assert copied.read_bytes() == profile.read_bytes()
            assert "profile" in events
            kind = "manifest"
        rename(temporary, destination)
        events.append(kind)

    monkeypatch.setattr(editor.os, "fsync", sync)
    monkeypatch.setattr(editor, "_durable_rename", publish)
    saved = save_story_document(state, document)
    assert read_story_document(state, saved["storyPath"]) == saved
    assert events[-1] == "manifest"
    assert not list(profile.parent.parent.glob("*.tmp"))


@pytest.mark.parametrize("failure", ["profile-sync", "profile-rename", "manifest-rename", "after-manifest-rename"])
def test_failed_save_never_leaves_manifest_with_missing_profiles(tmp_path, monkeypatch, failure):
    from application.story import editor

    state, document, profile = setup_generated_profile(tmp_path)
    original = Path(document["storyPath"]).read_bytes()
    rename = editor._durable_rename

    def fail_sync(_fd):
        raise OSError("injected sync failure")

    def publish(temporary, destination):
        is_profile = "-character-" in destination.name
        if failure == ("profile-rename" if is_profile else "manifest-rename"):
            raise OSError("injected rename failure")
        rename(temporary, destination)
        if failure == "after-manifest-rename" and not is_profile:
            raise OSError("injected directory sync failure")

    monkeypatch.setattr(editor, "_durable_rename", publish)
    if failure == "profile-sync":
        monkeypatch.setattr(editor.os, "fsync", fail_sync)
    with pytest.raises(OSError, match="injected"):
        save_story_document(state, document)
    root = profile.parent.parent
    assert Path(document["storyPath"]).read_bytes() == original
    assert not list(root.glob("*.tmp"))
    if failure == "after-manifest-rename":
        manifest, = root.glob("edited-*.json")
        source = StoryProjectLoader().load_source(manifest)
        copied = root / source["cast"]["characters"][0]["source"]["path"]
        assert copied.read_bytes() == profile.read_bytes()
        assert read_story_document(state, str(manifest))["version"] == document["version"] + 1
    else:
        assert not list(root.glob("edited-*"))
