import hashlib
from unittest.mock import Mock

import pytest

from application.characters import mouth_resources as resources


def test_configured_old_python_is_reported_before_install(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"not executed")
    resources.configure(tmp_path, {"pythonPath": str(python), "device": "cpu"})
    monkeypatch.setattr(resources, "_probe", Mock(return_value={"version": [3, 10, 11], "missing": []}))
    assert not resources.runtime_status(tmp_path)["compatible"]
    with pytest.raises(ValueError, match="3.12"):
        resources.install_runtime(tmp_path, None, Mock())


def test_extra_packages_are_isolated_by_python_minor_version(tmp_path):
    assert resources.package_directory(tmp_path, [3, 12, 0]) != resources.package_directory(tmp_path, [3, 13, 5])
    assert resources.package_directory(tmp_path, [3, 13, 0]) == resources.package_directory(tmp_path, [3, 13, 5])


def test_model_import_identifies_content_and_rejects_wrong_weights(tmp_path, monkeypatch):
    specs = {}
    paths = []
    for index, name in enumerate(("yolov3", "hrnetv2")):
        content = f"weight-{index}".encode()
        file = tmp_path / f"arbitrary-name-{index}.safetensors"
        file.write_bytes(content)
        paths.append(str(file))
        specs[name] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    monkeypatch.setattr(resources, "MODEL_FILES", specs)
    resources.import_models(tmp_path, paths)
    for name, spec in specs.items():
        assert resources.verify_weight(resources.locations(tmp_path)["models"] / f"{name}.safetensors", spec)
    with pytest.raises(ValueError, match="不匹配"):
        resources.import_models(tmp_path, [paths[0], paths[0]])
