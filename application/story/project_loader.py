"""Filesystem orchestration for loading story project YAML and JSON documents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

import yaml

from core.story.diagnostics import StoryDiagnostic, StoryValidationError
from core.story.models import StoryProject
from core.story.schema import parse_story_project
from sdk.path_utils import (
    is_portable_relative_path,
    safe_child_path,
    safe_existing_file_path,
)

_JSON_STORY_FILENAMES = ("story.json", "draft.json")


class StoryProjectLoader:
    """Load a packaged YAML story or an authoring JSON document without path escape."""

    def load(self, path: str | Path) -> StoryProject:
        requested = Path(path)
        if requested.is_dir():
            return self._load_directory(requested.resolve())
        if requested.suffix.lower() == ".json":
            root = requested.parent.resolve()
            return parse_story_project(self._read_document(requested.resolve(), root))
        return self._load_yaml_package(requested.resolve())

    def _load_directory(self, root: Path) -> StoryProject:
        yaml_manifest = root / "manifest.yaml"
        if yaml_manifest.is_file():
            return self._load_yaml_package(yaml_manifest)
        for name in _JSON_STORY_FILENAMES:
            candidate = root / name
            if candidate.is_file():
                return parse_story_project(self._read_document(candidate, root))
        return self._load_yaml_package(yaml_manifest)

    def _load_yaml_package(self, manifest_path: Path) -> StoryProject:
        root = manifest_path.parent.resolve()
        manifest = self._read_document(manifest_path.resolve(), root)
        aggregate = dict(manifest)
        self._merge_ref(aggregate, manifest, "variablesRef", "variables", root)
        self._merge_ref(aggregate, manifest, "castRef", "cast", root)
        self._merge_ref(
            aggregate, manifest, "narrativeGraphRef", "narrativeGraph", root
        )
        self._merge_ref(aggregate, manifest, "logicGraphRef", "logicGraph", root)
        self._merge_chapter_refs(aggregate, manifest, root)
        return parse_story_project(aggregate)

    def _merge_chapter_refs(
        self,
        aggregate: dict[str, Any],
        manifest: Mapping[str, Any],
        root: Path,
    ) -> None:
        references = manifest.get("chaptersRef")
        if references is None:
            return
        if not isinstance(references, Sequence) or isinstance(
            references, (str, bytes, bytearray)
        ):
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.ref", "chaptersRef must be a list", "$.chaptersRef"
                    )
                ]
            )
        graph = aggregate.setdefault("narrativeGraph", {})
        if not isinstance(graph, dict):
            graph = dict(graph) if isinstance(graph, Mapping) else {}
            aggregate["narrativeGraph"] = graph
        nodes = graph.setdefault("nodes", [])
        if not isinstance(nodes, list):
            nodes = list(nodes) if isinstance(nodes, Sequence) else []
            graph["nodes"] = nodes
        for index, reference in enumerate(references):
            reference_path = f"$.chaptersRef[{index}]"
            if not isinstance(reference, str) or not reference:
                raise StoryValidationError(
                    [
                        StoryDiagnostic(
                            "schema.ref",
                            "chapter reference must be a string",
                            reference_path,
                        )
                    ]
                )
            document = self._read_reference(root, reference, reference_path)
            chapter = document.get("narrativeGraph", document)
            if not isinstance(chapter, Mapping):
                raise StoryValidationError(
                    [
                        StoryDiagnostic(
                            "schema.document",
                            "chapter document must be an object",
                            reference,
                        )
                    ]
                )
            chapter_nodes = chapter.get("nodes", ())
            if not isinstance(chapter_nodes, Sequence) or isinstance(
                chapter_nodes, (str, bytes, bytearray)
            ):
                raise StoryValidationError(
                    [
                        StoryDiagnostic(
                            "schema.document",
                            "chapter nodes must be a list",
                            reference,
                        )
                    ]
                )
            nodes.extend(chapter_nodes)

    def _merge_ref(
        self,
        aggregate: dict[str, Any],
        manifest: Mapping[str, Any],
        ref_key: str,
        destination_key: str,
        root: Path,
    ) -> None:
        reference = manifest.get(ref_key)
        if reference is None:
            return
        reference_path = f"$.{ref_key}"
        if not isinstance(reference, str) or not reference:
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.ref", "reference must be a string", reference_path
                    )
                ]
            )
        document = self._read_reference(root, reference, reference_path)
        aggregate[destination_key] = document.get(destination_key, document)

    def _read_reference(
        self,
        root: Path,
        reference: str,
        diagnostic_path: str,
    ) -> Mapping[str, Any]:
        normalized = reference.replace("\\", "/")
        if not is_portable_relative_path(reference):
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.path_escape",
                        "reference must stay inside the story root",
                        diagnostic_path,
                    )
                ]
            )
        try:
            target = safe_child_path(root, normalized)
        except (PermissionError, ValueError) as error:
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.path_escape",
                        "reference escapes story root",
                        diagnostic_path,
                    )
                ]
            ) from error
        return self._read_document(target, root)

    def _read_document(self, path: Path, root: Path) -> Mapping[str, Any]:
        try:
            safe_path = safe_existing_file_path(path, roots=(root,), field="story file")
        except PermissionError as error:
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.path_escape", "reference escapes story root", str(path)
                    )
                ]
            ) from error
        except (FileNotFoundError, ValueError) as error:
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.missing_file", "story file does not exist", str(path)
                    )
                ]
            ) from error
        suffix = safe_path.suffix.lower()
        try:
            text = safe_path.read_text(encoding="utf-8")
            value = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
        except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as error:
            raise StoryValidationError(
                [StoryDiagnostic("schema.read_failed", str(error), str(safe_path))]
            ) from error
        if not isinstance(value, Mapping):
            kind = "JSON" if suffix == ".json" else "YAML"
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.document",
                        f"{kind} document must be an object",
                        str(safe_path),
                    )
                ]
            )
        return value


def load_story_project(path: str | Path) -> StoryProject:
    return StoryProjectLoader().load(path)
