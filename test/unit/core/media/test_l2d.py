import json
from pathlib import Path

import pytest

from core.media.avatar.l2d import Live2DAdapter

FIXTURES = json.loads((Path(__file__).resolve().parents[3] / "fixtures/avatar/l2d_states.json").read_text())


@pytest.fixture
def model(tmp_path):
    for name in ("sample.moc3", "texture.png", "expressions/smile.exp3.json", "motions/nod.motion3.json"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    path = tmp_path / "sample.model3.json"
    path.write_text(json.dumps({"Version": 3, "FileReferences": {"Moc": "sample.moc3", "Textures": ["texture.png"], "Expressions": [{"File": "expressions/smile.exp3.json"}], "Motions": {"Tap": [{"File": "motions/nod.motion3.json"}]}}}))
    return path


def test_inspect_lists_complete_safe_package(model):
    files = Live2DAdapter().inspect(model)
    assert files.entry == model
    assert {path.name for path in files.files} == {"sample.model3.json", "sample.moc3", "texture.png", "smile.exp3.json", "nod.motion3.json"}


@pytest.mark.parametrize("value", FIXTURES["valid"])
def test_accept_shared_fixtures(model, value):
    assert Live2DAdapter().parse_state(model, value) == value


@pytest.mark.parametrize("value", FIXTURES["invalid"])
def test_reject_shared_fixtures(model, value):
    with pytest.raises((ValueError, FileNotFoundError)):
        Live2DAdapter().parse_state(model, value)


@pytest.mark.parametrize("path", ["../escape.moc3", "C:/escape.moc3", "https://example.com/a.moc3", "%2e%2e/escape.moc3", "folder\\a.moc3"])
def test_reject_escaped_dependency(model, path):
    value = json.loads(model.read_text())
    value["FileReferences"]["Moc"] = path
    model.write_text(json.dumps(value))
    with pytest.raises((ValueError, PermissionError)):
        Live2DAdapter().inspect(model)


def test_missing_texture(model):
    (model.parent / "texture.png").unlink()
    with pytest.raises(FileNotFoundError):
        Live2DAdapter().inspect(model)


def test_directory_with_multiple_models_requires_selection(model):
    (model.parent / "second.model3.json").write_text(model.read_text())
    with pytest.raises(ValueError):
        Live2DAdapter().inspect(model.parent)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_parameters(model, number):
    with pytest.raises(ValueError):
        Live2DAdapter().parse_state(model, {"parameters": {"ParamAngleX": number}, "expressions": [], "motion": ""})
