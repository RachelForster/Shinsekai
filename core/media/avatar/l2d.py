"""Cubism 3+ file adapter. No rendering or character mutations live here."""

from __future__ import annotations

import json
import math
from pathlib import Path

from sdk.adapters import ModelAssetAdapter, ModelCapabilities, ModelFiles
from sdk.path_utils import is_portable_relative_path, safe_child_path
from core.media.avatar.l2d_sdk import Live2DRuntimeInstaller


def _file(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not is_portable_relative_path(value) or any(c in value for c in ":?#%\\") or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError("Live2D dependency must be a relative package path")
    path = safe_child_path(root, value)
    if not path.is_file():
        raise FileNotFoundError(value)
    return path


class Live2DAdapter(ModelAssetAdapter):
    format_id = "l2d"
    capabilities = ModelCapabilities(mouth=True, blink=True, motion=True)
    runtime_installer = Live2DRuntimeInstaller()

    def inspect(self, source: Path) -> ModelFiles:
        source = source.resolve(strict=True)
        if source.is_dir():
            entries = list(source.rglob("*.model3.json"))
            if len(entries) != 1:
                raise ValueError("Select one .model3.json explicitly")
            source = entries[0]
        if not source.name.endswith(".model3.json"):
            raise ValueError("Live2D requires a .model3.json entry")
        data = json.loads(source.read_text(encoding="utf-8"))
        refs = data.get("FileReferences")
        if data.get("Version") != 3 or not isinstance(refs, dict):
            raise ValueError("Invalid Cubism model3.json")
        paths = [refs.get("Moc")]
        textures = refs.get("Textures")
        if not isinstance(textures, list) or not textures:
            raise ValueError("Live2D model has no textures")
        paths.extend(textures)
        for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
            if refs.get(key):
                paths.append(refs[key])
        expressions = refs.get("Expressions", [])
        motions = refs.get("Motions", {})
        if not isinstance(expressions, list) or not isinstance(motions, dict):
            raise ValueError("Invalid Live2D expression/motion references")
        for item in expressions:
            if not isinstance(item, dict):
                raise ValueError("Invalid Live2D expression reference")
            paths.append(item.get("File"))
        for group in motions.values():
            if not isinstance(group, list):
                raise ValueError("Invalid Live2D motion group")
            for item in group:
                if not isinstance(item, dict):
                    raise ValueError("Invalid Live2D motion reference")
                paths.append(item.get("File"))
                if item.get("Sound"):
                    paths.append(item["Sound"])
        files = tuple(dict.fromkeys([source, *(_file(source.parent, p) for p in paths)]))
        return ModelFiles(entry=source, files=files)

    def parse_state(self, model: Path, value: object) -> dict:
        if not isinstance(value, dict) or set(value) != {"parameters", "expressions", "motion"}:
            raise ValueError("Live2D state requires parameters, expressions, motion")
        parameters, expressions, motion = value["parameters"], value["expressions"], value["motion"]
        if not isinstance(parameters, dict) or not all(
            isinstance(key, str) and key and isinstance(number, (int, float))
            and not isinstance(number, bool) and math.isfinite(number)
            for key, number in parameters.items()
        ):
            raise ValueError("Live2D parameters must be finite numbers")
        if not isinstance(expressions, list) or not all(isinstance(p, str) for p in expressions):
            raise ValueError("Live2D expressions must be paths")
        if len(expressions) != len(set(expressions)) or not isinstance(motion, str):
            raise ValueError("Invalid Live2D expressions/motion")
        result = {"parameters": dict(parameters), "expressions": list(expressions), "motion": motion}
        refs = json.loads(model.read_text(encoding="utf-8"))["FileReferences"]
        known_expressions = {item["File"] for item in refs.get("Expressions", [])}
        known_motions = {item["File"] for group in refs.get("Motions", {}).values() for item in group}
        if any(path not in known_expressions for path in expressions) or (motion and motion not in known_motions):
            raise ValueError("Unknown Live2D expression/motion")
        for path in self.state_files(model, result):
            json.loads(path.read_text(encoding="utf-8"))
        return result

    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        root = model.resolve(strict=True).parent
        paths = []
        for reference in state["expressions"]:
            if not reference.endswith(".exp3.json"):
                raise ValueError("Expected .exp3.json expression")
            paths.append(_file(root, reference))
        if state["motion"]:
            if not state["motion"].endswith(".motion3.json"):
                raise ValueError("Expected .motion3.json motion")
            paths.append(_file(root, state["motion"]))
        return tuple(dict.fromkeys(paths))
