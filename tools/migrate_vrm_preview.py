"""Copy a legacy VRM preview workspace and register its model-state dependencies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.media.avatar.state_dependencies import write_state_index
from core.media.avatar.vrm import VrmAssetAdapter
from sdk.path_utils import safe_child_path, safe_existing_file_path


def migrate(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Select a new project root outside the legacy project")
    config = Path("data/config/characters.yaml")
    characters = yaml.safe_load((source / config).read_text(encoding="utf-8"))
    adapter = VrmAssetAdapter()
    legacy = source / "data" / "avatars"

    with tempfile.TemporaryDirectory(prefix=".vrm-migration-", dir=destination.parent) as staging:
        project = Path(staging) / "project"
        # Keep project settings and non-VRM character assets available in the preview copy.
        shutil.copytree(source / "data", project / "data")
        for character in characters:
            bank = character.get("avatars", {}).get("vrm", {})
            if not bank.get("model_path"):
                continue
            original = safe_existing_file_path(source / bank["model_path"], roots=[source])
            if not original.is_relative_to(legacy):
                continue
            prefix = character["sprite_prefix"]
            if not prefix or prefix in {".", ".."} or "/" in prefix or "\\" in prefix:
                raise ValueError("Invalid character sprite prefix")
            package = Path("data/sprite") / prefix / "avatars/vrm" / uuid.uuid4().hex
            target = safe_child_path(project, package)
            target.mkdir(parents=True)
            model = target / adapter.inspect(original).entry.name
            shutil.copy2(original, model)
            bank["model_path"] = str(destination / package / model.name)
            for state in bank.get("sprites", []):
                saved = safe_existing_file_path(source / state["path"], roots=[original.parent])
                parsed = adapter.parse_state(original, json.loads(saved.read_text(encoding="utf-8")))
                for dependency in adapter.state_files(original, parsed):
                    copied = safe_child_path(target, dependency.relative_to(original.parent))
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    if not copied.exists():
                        shutil.copy2(dependency, copied)
                relative = saved.relative_to(original.parent)
                migrated = safe_child_path(target, relative)
                migrated.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, migrated)
                write_state_index(adapter, model, migrated, adapter.parse_state(model, parsed))
                state["path"] = str(destination / package / relative)
            print(f"{character['name']}: {len(bank.get('sprites', []))} states")
        (project / config).write_text(yaml.safe_dump(characters, allow_unicode=True, sort_keys=False), encoding="utf-8")
        project.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    migrate(args.source, args.destination)
