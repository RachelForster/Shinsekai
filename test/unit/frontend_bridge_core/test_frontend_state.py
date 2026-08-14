from pathlib import Path
import inspect

from application.runtime.state import BridgeState, _jsonify


class ModelDumpValue:
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {"nested": [{"value": 1}]}


def test_jsonify_recursively_handles_model_dump_lists_and_dicts():
    assert _jsonify(
        {
            1: ModelDumpValue(),
            "items": [ModelDumpValue(), {"ok": True}],
        }
    ) == {
        "1": {"nested": [{"value": 1}]},
        "items": [{"nested": [{"value": 1}]}, {"ok": True}],
    }


def test_jsonify_returns_scalar_values_unchanged():
    assert _jsonify("text") == "text"
    assert _jsonify(3) == 3
    assert _jsonify(None) is None


def test_bridge_state_project_root_defaults_to_runtime_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "Project Data 项目根"
    project_root.mkdir()
    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))

    state = BridgeState(None, None, None, None)

    assert Path(state.project_root_dir) == project_root.resolve()


def test_bridge_state_keeps_project_root_as_last_positional_parameter():
    parameters = inspect.signature(BridgeState.__init__).parameters
    positional = [
        name
        for name, parameter in parameters.items()
        if name != "self"
        and parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]

    assert positional[-1] == "project_root_dir"
    assert "story_cast_service" not in positional
    assert "story_import_tokens" not in positional
