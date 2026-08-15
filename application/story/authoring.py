"""Versioned story authoring, validation, publication, and preview services."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any
import uuid

from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from sdk.path_utils import safe_child_path
from core.story import (
    CastResolutionContext,
    CastResolutionError,
    CastResolver,
    CharacterRuntimeStatus,
    EnterNode,
    PerformIntent,
    SelectChoice,
    StartStory,
    StoryCompiler,
    StoryRuntime,
    StorySimulator,
    StoryValidationError,
    canonical_json,
    parse_story_project,
)

from .generation import (
    ConfigStoryAuthorModel,
    StoryAuthorModelPort,
    StoryDraftValidator,
    StoryGenerationError,
    StoryPatchApplier,
    story_generation_service_for_state,
)
from .persistence import story_event_to_payload, story_state_to_payload


MAX_HISTORY_ENTRIES = 100
MAX_DIFF_ENTRIES = 300
MAX_PREVIEW_STEPS = 100
DRAFT_COMMIT_DIR = ".commit"
DRAFT_COMMIT_READY = "ready"
PUBLICATION_READY = ".complete"
_STORY_SCOPED_CHARACTER_TYPES = frozenset({"author-generated", "embedded"})
_REGION_REPLACE_OPS = {
    "node": ("replace-node", "nodeId"),
    "character": ("replace-character", "characterId"),
    "variable": ("replace-variable", "variableId"),
    "rule": ("replace-rule-node", "nodeId"),
}


class StoryAuthoringError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class StoryProjectRepository:
    """Atomic draft, history, and immutable publication storage."""

    def __init__(self, flags: FeatureFlagConfigManager, root: str | Path) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.root = Path(root).expanduser().resolve(strict=False)
        self._lock = threading.RLock()

    def list_projects(self) -> list[dict[str, Any]]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        if not self.root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock:
            for directory in sorted(self.root.iterdir(), key=lambda item: item.name):
                if not directory.is_dir():
                    continue
                try:
                    self._recover_pending(directory)
                except StoryAuthoringError:
                    continue
                manifest = directory / "manifest.json"
                if manifest.is_file():
                    try:
                        rows.append(self._read_json(manifest))
                    except StoryAuthoringError:
                        continue
        return rows

    def create(self, source: Mapping[str, Any]) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        payload = _json_copy(source)
        project_id = _safe_id(payload.get("id"), "story id")
        directory = self._project_dir(project_id)
        with self._lock:
            if directory.exists():
                raise StoryAuthoringError(
                    "authoring.project_exists",
                    f"story project {project_id!r} already exists",
                )
            directory.mkdir(parents=True, exist_ok=False)
            now = _now_ms()
            manifest = {
                "id": project_id,
                "title": str(payload.get("title") or project_id),
                "draftRevision": 1,
                "undoCursor": 1,
                "publishedVersion": 0,
                "publishedSourceHash": "",
                "createdAt": now,
                "updatedAt": now,
            }
            self._commit_project_files(directory, payload, manifest)
            return self._load_unlocked(project_id)

    def load(self, project_id: str) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock:
            return self._load_unlocked(project_id)

    def save_draft(
        self,
        project_id: str,
        source: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock:
            current = self._load_unlocked(project_id)
            manifest = current["manifest"]
            actual_revision = int(manifest.get("draftRevision", 0))
            if actual_revision != expected_revision:
                raise StoryAuthoringError(
                    "authoring.revision_conflict",
                    f"expected draft revision {expected_revision}, found {actual_revision}",
                )
            directory = self._project_dir(project_id)
            history = directory / "history"
            history.mkdir(parents=True, exist_ok=True)
            self._write_json(history / f"{actual_revision:08d}.json", current["source"])
            next_source = _json_copy(source)
            next_revision = actual_revision + 1
            next_manifest = {
                **manifest,
                "title": str(
                    next_source.get("title") or manifest.get("title") or project_id
                ),
                "draftRevision": next_revision,
                "undoCursor": next_revision,
                "updatedAt": _now_ms(),
            }
            self._commit_project_files(directory, next_source, next_manifest)
            self._trim_history(history)
            return {"manifest": next_manifest, "source": next_source}

    def undo(self, project_id: str, *, expected_revision: int) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock:
            current = self._load_unlocked(project_id)
            manifest = current["manifest"]
            actual = int(manifest.get("draftRevision", 0))
            if actual != expected_revision:
                raise StoryAuthoringError(
                    "authoring.revision_conflict",
                    f"expected draft revision {expected_revision}, found {actual}",
                )
            cursor = int(manifest.get("undoCursor", actual))
            previous_path = (
                self._project_dir(project_id) / "history" / f"{cursor - 1:08d}.json"
            )
            if not previous_path.is_file():
                raise StoryAuthoringError(
                    "authoring.undo_empty", "there is no earlier draft revision"
                )
            previous = self._read_json(previous_path)
            next_revision = actual + 1
            next_manifest = {
                **manifest,
                "title": str(
                    previous.get("title") or manifest.get("title") or project_id
                ),
                "draftRevision": next_revision,
                "undoCursor": cursor - 1,
                "updatedAt": _now_ms(),
            }
            self._commit_project_files(
                self._project_dir(project_id), previous, next_manifest
            )
            return {"manifest": next_manifest, "source": previous}

    def publish(
        self,
        project_id: str,
        source: Mapping[str, Any],
        *,
        expected_revision: int,
        source_hash: str,
        dependencies: Mapping[str, Any],
        compatibility: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock:
            current = self._load_unlocked(project_id)
            manifest = current["manifest"]
            actual = int(manifest.get("draftRevision", 0))
            if actual != expected_revision:
                raise StoryAuthoringError(
                    "authoring.revision_conflict",
                    f"expected draft revision {expected_revision}, found {actual}",
                )
            version = int(manifest.get("publishedVersion", 0)) + 1
            project_dir = self._project_dir(project_id)
            published_root = project_dir / "published"
            final = published_root / f"v{version}"
            staging = published_root / f".v{version}.staging"
            next_manifest = {
                **manifest,
                "publishedVersion": version,
                "publishedSourceHash": source_hash,
                "updatedAt": _now_ms(),
            }
            result = {
                "projectId": project_id,
                "version": version,
                "sourceHash": source_hash,
                "path": str(final / "story.json"),
                "resourceDependencies": _json_copy(dependencies),
                "saveCompatibility": _json_copy(compatibility),
            }
            if self._publication_is_complete(final):
                self._commit_project_files(project_dir, current["source"], next_manifest)
                return result
            self._remove_path(staging)
            if final.exists():
                self._remove_path(final)
            staging.mkdir(parents=True, exist_ok=False)
            try:
                self._write_json(staging / "story.json", source)
                self._write_json(staging / "resources.json", dependencies)
                self._write_json(staging / "save-compatibility.json", compatibility)
                copy_story_scoped_character_resources(project_dir, staging, source)
                self._write_ready_marker(staging / PUBLICATION_READY)
                os.replace(staging, final)
            except Exception:
                self._remove_path(staging)
                raise
            self._commit_project_files(project_dir, current["source"], next_manifest)
            return result

    def load_published(self, project_id: str, version: int) -> dict[str, Any] | None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock:
            directory = self._project_dir(project_id)
            self._recover_pending(directory)
            path = directory / "published" / f"v{version}" / "story.json"
            return self._read_json(path) if path.is_file() else None

    def copy_story_scoped_resources(
        self, project_id: str, source_root: str | Path, source: Mapping[str, Any]
    ) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock:
            copy_story_scoped_character_resources(
                Path(source_root), self._project_dir(project_id), source
            )

    def _load_unlocked(self, project_id: str) -> dict[str, Any]:
        directory = self._project_dir(project_id)
        self._recover_pending(directory)
        manifest = self._read_json(directory / "manifest.json")
        source = self._read_json(directory / "draft.json")
        return {"manifest": manifest, "source": source}

    def _project_dir(self, project_id: str) -> Path:
        safe = _safe_id(project_id, "story id")
        path = (self.root / safe).resolve(strict=False)
        if path.parent != self.root:
            raise StoryAuthoringError(
                "authoring.invalid_id", "story project path escaped root"
            )
        return path

    def _recover_pending(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        self._apply_draft_commit(directory)
        self._discard_incomplete_publication_staging(directory)

    def _commit_project_files(
        self,
        directory: Path,
        draft: Mapping[str, Any],
        manifest: Mapping[str, Any],
    ) -> None:
        staging = directory / DRAFT_COMMIT_DIR
        self._remove_path(staging)
        staging.mkdir(parents=True, exist_ok=True)
        self._write_json(staging / "draft.json", draft)
        self._write_json(staging / "manifest.json", manifest)
        self._write_ready_marker(staging / DRAFT_COMMIT_READY)
        self._apply_draft_commit(directory)

    def _apply_draft_commit(self, directory: Path) -> None:
        staging = directory / DRAFT_COMMIT_DIR
        ready = staging / DRAFT_COMMIT_READY
        if not staging.is_dir():
            return
        if not ready.is_file():
            self._remove_path(staging)
            return
        draft_src = staging / "draft.json"
        manifest_src = staging / "manifest.json"
        if not draft_src.is_file() or not manifest_src.is_file():
            self._remove_path(staging)
            return
        self._write_json(directory / "draft.json", self._read_json(draft_src))
        self._write_json(directory / "manifest.json", self._read_json(manifest_src))
        self._remove_path(staging)

    def _discard_incomplete_publication_staging(self, directory: Path) -> None:
        published = directory / "published"
        if not published.is_dir():
            return
        for path in published.iterdir():
            if (
                path.is_dir()
                and path.name.startswith(".")
                and path.name.endswith(".staging")
            ):
                self._remove_path(path)

    @staticmethod
    def _publication_is_complete(directory: Path) -> bool:
        return (
            directory.is_dir()
            and (directory / "story.json").is_file()
            and (directory / PUBLICATION_READY).is_file()
        )

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StoryAuthoringError(
                "authoring.storage_read_failed", f"cannot read {path.name}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise StoryAuthoringError(
                "authoring.storage_invalid", f"{path.name} must contain an object"
            )
        return value

    @staticmethod
    def _write_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        encoded = json.dumps(
            value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_ready_marker(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write("1")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _trim_history(history: Path) -> None:
        entries = sorted(history.glob("*.json"))
        for stale in entries[:-MAX_HISTORY_ENTRIES]:
            stale.unlink(missing_ok=True)


class StoryAuthoringService:
    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        repository: StoryProjectRepository,
        *,
        author_model: StoryAuthorModelPort | None = None,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.repository = repository
        self.validator = StoryDraftValidator()
        self.patch_applier = StoryPatchApplier()
        self.author_model = author_model
        self._write_lock = threading.RLock()

    def list_projects(self) -> list[dict[str, Any]]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        return self.repository.list_projects()

    def project_directory(self, project_id: str) -> Path:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        document = self.repository.load(project_id)
        return self.repository._project_dir(str(document["manifest"]["id"]))

    def import_source(self, source: Mapping[str, Any]) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        payload = _json_copy(source)
        _safe_id(payload.get("id"), "story id")
        payload["status"] = "draft"
        document = self.repository.create(payload)
        return self._document_payload(document)

    def get(self, project_id: str) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        return self._document_payload(self.repository.load(project_id))

    def validate(self, project_id: str) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        document = self.repository.load(project_id)
        return self._validation_payload(document["source"])

    def apply_patch(
        self,
        project_id: str,
        patch: Mapping[str, Any],
        *,
        base_revision: int,
        commit: bool,
        allow_invalid: bool = True,
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._write_lock:
            document = self.repository.load(project_id)
            manifest = document["manifest"]
            actual = int(manifest.get("draftRevision", 0))
            if actual != base_revision:
                raise StoryAuthoringError(
                    "authoring.revision_conflict",
                    f"expected draft revision {base_revision}, found {actual}",
                )
            source = document["source"]
            normalized_patch = {
                "baseVersion": int(source.get("version", 1)),
                "operations": patch.get("operations"),
            }
            try:
                candidate = self.patch_applier.apply(
                    source,
                    normalized_patch,
                    base_version=int(source.get("version", 1)),
                )
            except StoryGenerationError as error:
                raise StoryAuthoringError(error.code, str(error)) from error
            validation = self._validation_payload(candidate)
            result = {
                "baseRevision": base_revision,
                "candidateRevision": base_revision + 1,
                "diff": _structural_diff(source, candidate),
                "validation": validation,
                "source": candidate,
                "committed": False,
            }
            if not commit:
                return result
            if not allow_invalid and not validation["valid"]:
                raise StoryAuthoringError(
                    "authoring.patch_invalid",
                    "patch candidate does not pass validation",
                )
            saved = self.repository.save_draft(
                project_id, candidate, expected_revision=base_revision
            )
            return {
                **result,
                "committed": True,
                "document": self._document_payload(saved),
            }

    def undo(self, project_id: str, *, base_revision: int) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._write_lock:
            return self._document_payload(
                self.repository.undo(project_id, expected_revision=base_revision)
            )

    def graph_projection(self, project_id: str) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        source = self.repository.load(project_id)["source"]
        validation = self._validation_payload(source)
        narrative = source.get("narrativeGraph", {})
        logic = source.get("logicGraph", {})
        projection = {
            "narrative": _layout_narrative_graph(narrative),
            "rules": _layout_rule_graph(logic),
            "diagnostics": validation["issues"],
            "sourceMap": {},
        }
        try:
            project = parse_story_project(source)
            compiled = StoryCompiler().compile_with_diagnostics(project)
            if compiled.program is not None:
                projection["sourceMap"] = dict(compiled.program.source_map)
        except StoryValidationError:
            pass
        return projection

    def preview_cast(
        self,
        project_id: str,
        node_id: str,
        *,
        current_cast: Sequence[str] = (),
        statuses: Mapping[str, Mapping[str, Any]] | None = None,
        player_location: str | None = None,
        ai_proposal: Sequence[str] = (),
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        source = self.repository.load(project_id)["source"]
        project = parse_story_project(source)
        node = project.narrative_graph.by_id.get(node_id)
        if node is None:
            raise StoryAuthoringError(
                "authoring.node_not_found", f"story node {node_id!r} was not found"
            )
        runtime_statuses = {
            character_id: CharacterRuntimeStatus(
                available=bool(payload.get("available", True)),
                alive=bool(payload.get("alive", True)),
                location=(
                    str(payload["location"])
                    if payload.get("location") is not None
                    else None
                ),
            )
            for character_id, payload in (statuses or {}).items()
            if isinstance(payload, Mapping)
        }
        context = CastResolutionContext(
            current_cast=tuple(str(item) for item in current_cast),
            statuses=runtime_statuses,
            player_location=player_location,
            ai_proposal=tuple(str(item) for item in ai_proposal),
        )
        try:
            plan = CastResolver().resolve(
                project.character_registry, node.cast_policy, context
            )
            selected = set(plan.active_character_ids)
            candidates = [
                {
                    "characterId": character.id,
                    "accepted": character.id in selected,
                    "reasonCode": (
                        "selected"
                        if character.id in selected
                        else plan.excluded.get(character.id, "eligible-not-selected")
                    ),
                }
                for character in project.character_registry.characters
            ]
            return {
                "valid": True,
                "nodeId": node_id,
                "activeCharacterIds": list(plan.active_character_ids),
                "roleBindings": dict(plan.role_bindings),
                "unresolvedRoles": list(plan.unresolved_roles),
                "candidates": candidates,
                "error": None,
            }
        except CastResolutionError as error:
            return {
                "valid": False,
                "nodeId": node_id,
                "activeCharacterIds": [],
                "roleBindings": {},
                "unresolvedRoles": [],
                "candidates": [
                    {
                        "characterId": character.id,
                        "accepted": False,
                        "reasonCode": "resolution-failed",
                    }
                    for character in project.character_registry.characters
                ],
                "error": {"code": error.code, "message": str(error)},
            }

    def preview_path(
        self,
        project_id: str,
        *,
        ending_id: str | None = None,
        actions: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        source = self.repository.load(project_id)["source"]
        program = StoryCompiler().compile(parse_story_project(source))
        runtime = StoryRuntime(program)
        selected_actions = list(actions)
        if ending_id and not selected_actions:
            report = StorySimulator(runtime, max_states=2_000, max_depth=150).simulate()
            path = report.ending_paths.get(ending_id)
            if path is None:
                raise StoryAuthoringError(
                    "authoring.ending_unreachable",
                    f"ending {ending_id!r} is not reachable",
                )
            selected_actions = [_simulation_step(step) for step in path]
        if len(selected_actions) > MAX_PREVIEW_STEPS:
            raise StoryAuthoringError(
                "authoring.preview_too_long",
                f"path preview supports at most {MAX_PREVIEW_STEPS} steps",
            )
        result = runtime.start(StartStory(f"preview-{uuid.uuid4().hex}"))
        snapshots = [
            {
                "step": 0,
                "action": {"type": "start"},
                "state": story_state_to_payload(result.state),
                "events": [story_event_to_payload(item) for item in result.events],
            }
        ]
        state = result.state
        for index, action in enumerate(selected_actions, start=1):
            action_type = str(action.get("type") or "")
            identifier = str(action.get("id") or "")
            command_id = f"preview-{index}-{uuid.uuid4().hex[:8]}"
            if action_type == "choice":
                command = SelectChoice(
                    command_id, state.revision, identifier, state.current_node_id
                )
            elif action_type == "intent":
                command = PerformIntent(
                    command_id, state.revision, identifier, state.current_node_id
                )
            elif action_type == "enter":
                command = EnterNode(command_id, state.revision, identifier)
            else:
                raise StoryAuthoringError(
                    "authoring.preview_action_invalid",
                    f"unsupported preview action {action_type!r}",
                )
            result = runtime.execute(state, command)
            state = result.state
            snapshots.append(
                {
                    "step": index,
                    "action": _json_copy(action),
                    "state": story_state_to_payload(state),
                    "events": [story_event_to_payload(item) for item in result.events],
                }
            )
        return {
            "branchId": f"editor-test-{uuid.uuid4().hex}",
            "projectId": project_id,
            "endingId": ending_id,
            "snapshots": snapshots,
            "finalState": story_state_to_payload(state),
        }

    def propose_ai_patch(
        self,
        project_id: str,
        *,
        base_revision: int,
        region: str,
        instruction: str,
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        if self.author_model is None:
            raise StoryAuthoringError(
                "authoring.model_unavailable", "authoring model is not configured"
            )
        document = self.repository.load(project_id)
        if int(document["manifest"].get("draftRevision", 0)) != base_revision:
            raise StoryAuthoringError(
                "authoring.revision_conflict",
                "draft changed before AI patch generation",
            )
        source = document["source"]
        selected = _select_authoring_region(source, region)
        request = {
            "protocol": "shinsekai.story-authoring-patch.v1",
            "operation": "regenerate-authoring-region",
            "baseRevision": base_revision,
            "baseVersion": int(source.get("version", 1)),
            "region": region,
            "instruction": str(instruction).strip()[:4_000],
            "selectedSource": selected,
            "diagnostics": self._validation_payload(source)["issues"],
            "constraints": {
                "maxOperations": 32,
                "preserveIds": True,
                "onlyModifySelectedRegion": True,
            },
        }
        model_patch = self.author_model.complete(request)
        operations = model_patch.get("operations")
        if not isinstance(operations, list):
            raise StoryAuthoringError(
                "authoring.patch_invalid", "authoring patch operations must be an array"
            )
        _assert_patch_respects_region(source, operations, region)
        patch = {"operations": operations}
        preview = self.apply_patch(
            project_id,
            patch,
            base_revision=base_revision,
            commit=False,
            allow_invalid=False,
        )
        return {"patch": patch, **preview}

    def publish(self, project_id: str, *, base_revision: int) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._write_lock:
            document = self.repository.load(project_id)
            manifest = document["manifest"]
            if int(manifest.get("draftRevision", 0)) != base_revision:
                raise StoryAuthoringError(
                    "authoring.revision_conflict", "draft changed before publication"
                )
            source = _json_copy(document["source"])
            source["status"] = "published"
            next_version = int(manifest.get("publishedVersion", 0)) + 1
            source["version"] = next_version
            validation = self.validator.validate(source)
            if not validation.valid:
                raise StoryAuthoringError(
                    "authoring.publish_validation_failed",
                    canonical_json(validation.to_payload()),
                )
            compiled = StoryCompiler().compile(parse_story_project(source))
            dependencies = _resource_dependencies(source)
            previous = self.repository.load_published(project_id, next_version - 1)
            compatibility = _save_compatibility(previous, source, compiled.source_hash)
            return self.repository.publish(
                project_id,
                source,
                expected_revision=base_revision,
                source_hash=compiled.source_hash,
                dependencies=dependencies,
                compatibility=compatibility,
            )

    def _document_payload(self, document: Mapping[str, Any]) -> dict[str, Any]:
        source = document["source"]
        return {
            "manifest": _json_copy(document["manifest"]),
            "source": _json_copy(source),
            "validation": self._validation_payload(source),
            "resources": _resource_dependencies(source),
        }

    def _validation_payload(self, source: Mapping[str, Any]) -> dict[str, Any]:
        return self.validator.validate(source).to_payload()


def story_authoring_service_for_state(state: Any) -> StoryAuthoringService:
    flags = state.config_manager.feature_flags
    flags.require(FeatureFlag.STORY_SYSTEM)
    existing = getattr(state, "story_authoring_service", None)
    if existing is not None:
        return existing
    root = Path(state.project_root_dir) / "data" / "stories" / "projects"
    service = StoryAuthoringService(
        flags,
        StoryProjectRepository(flags, root),
        author_model=ConfigStoryAuthorModel(flags, state.config_manager),
    )
    state.story_authoring_service = service
    return service


def import_generation_task_for_state(
    state: Any, generation_task_id: str
) -> dict[str, Any]:
    flags = state.config_manager.feature_flags
    flags.require(FeatureFlag.STORY_SYSTEM)
    generation = story_generation_service_for_state(state)
    task = generation.get(generation_task_id)
    status = str(task.get("status") or "")
    draft_path = Path(str(task.get("draftPath") or "")).resolve(strict=False)
    task_root = generation.repository.task_directory(generation_task_id)
    if status not in {"succeeded", "failed"} or not str(
        task.get("draftPath") or ""
    ).strip():
        raise StoryAuthoringError(
            "authoring.generation_incomplete", "generation task has no completed draft"
        )
    if draft_path.parent != task_root or draft_path.name != "draft.json":
        raise StoryAuthoringError(
            "authoring.generation_path_invalid",
            "generation draft path is outside its task",
        )
    try:
        source = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoryAuthoringError(
            "authoring.generation_draft_invalid",
            f"cannot read generated draft: {error}",
        ) from error
    if not isinstance(source, dict):
        raise StoryAuthoringError(
            "authoring.generation_draft_invalid", "generated draft must be an object"
        )
    service = story_authoring_service_for_state(state)
    document = service.import_source(source)
    service.repository.copy_story_scoped_resources(
        str(document["manifest"]["id"]), task_root, source
    )
    return service.get(str(document["manifest"]["id"]))


def _layout_narrative_graph(source: Any) -> dict[str, Any]:
    graph = source if isinstance(source, Mapping) else {}
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, Mapping)]
    ids = [str(item.get("id") or "") for item in nodes]
    edges: list[dict[str, str]] = []
    adjacency: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        source_id = str(node.get("id") or "")
        for choice in node.get("choices", []):
            if isinstance(choice, Mapping) and choice.get("goto"):
                target = str(choice["goto"])
                edges.append(
                    {
                        "id": f"choice:{source_id}/{choice.get('id', '')}",
                        "from": source_id,
                        "to": target,
                        "label": str(choice.get("label") or choice.get("id") or ""),
                    }
                )
                adjacency[source_id].append(target)
    start = str(graph.get("startNodeId") or (ids[0] if ids else ""))
    layers = _graph_layers(ids, adjacency, (start,))
    positioned = _positioned_nodes(nodes, layers)
    return {"nodes": positioned, "edges": edges}


def _layout_rule_graph(source: Any) -> dict[str, Any]:
    graph = source if isinstance(source, Mapping) else {}
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, Mapping)]
    ids = [str(item.get("id") or "") for item in nodes]
    adjacency: dict[str, list[str]] = defaultdict(list)
    incoming: set[str] = set()
    edges: list[dict[str, Any]] = []
    for index, edge in enumerate(graph.get("edges", [])):
        if not isinstance(edge, Mapping):
            continue
        source_ref = edge.get("from", {})
        target_ref = edge.get("to", {})
        if not isinstance(source_ref, Mapping) or not isinstance(target_ref, Mapping):
            continue
        source_id = str(source_ref.get("nodeId") or "")
        target_id = str(target_ref.get("nodeId") or "")
        adjacency[source_id].append(target_id)
        incoming.add(target_id)
        edges.append(
            {
                "id": f"rule-edge-{index}",
                "from": source_id,
                "fromPort": str(source_ref.get("port") or ""),
                "to": target_id,
                "toPort": str(target_ref.get("port") or ""),
            }
        )
    roots = tuple(identifier for identifier in ids if identifier not in incoming)
    layers = _graph_layers(ids, adjacency, roots)
    return {"nodes": _positioned_nodes(nodes, layers), "edges": edges}


def _graph_layers(
    ids: Sequence[str], adjacency: Mapping[str, Sequence[str]], roots: Sequence[str]
) -> dict[str, int]:
    layers: dict[str, int] = {}
    queue = deque((identifier, 0) for identifier in roots if identifier)
    while queue:
        identifier, layer = queue.popleft()
        if identifier in layers and layers[identifier] <= layer:
            continue
        layers[identifier] = layer
        for target in adjacency.get(identifier, ()):
            queue.append((target, layer + 1))
    fallback = max(layers.values(), default=-1) + 1
    for identifier in ids:
        if identifier not in layers:
            layers[identifier] = fallback
    return layers


def _positioned_nodes(
    nodes: Sequence[Mapping[str, Any]], layers: Mapping[str, int]
) -> list[dict[str, Any]]:
    rows: dict[int, int] = defaultdict(int)
    positioned: list[dict[str, Any]] = []
    for node in sorted(
        nodes,
        key=lambda item: (layers.get(str(item.get("id")), 0), str(item.get("id"))),
    ):
        identifier = str(node.get("id") or "")
        layer = layers.get(identifier, 0)
        row = rows[layer]
        rows[layer] += 1
        positioned.append(
            {
                "id": identifier,
                "title": str(node.get("title") or node.get("type") or identifier),
                "type": str(node.get("type") or "story"),
                "x": layer * 300,
                "y": row * 150,
            }
        )
    return positioned


def _structural_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    def visit(left: Any, right: Any, current: str) -> None:
        if len(changes) >= MAX_DIFF_ENTRIES or left == right:
            return
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left).union(right), key=str):
                child = f"{current}/{key}"
                if key not in left:
                    changes.append(
                        {
                            "op": "add",
                            "path": child,
                            "before": None,
                            "after": right[key],
                        }
                    )
                elif key not in right:
                    changes.append(
                        {
                            "op": "remove",
                            "path": child,
                            "before": left[key],
                            "after": None,
                        }
                    )
                else:
                    visit(left[key], right[key], child)
            return
        if isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                child = f"{current}/{index}"
                if index >= len(left):
                    changes.append(
                        {
                            "op": "add",
                            "path": child,
                            "before": None,
                            "after": right[index],
                        }
                    )
                elif index >= len(right):
                    changes.append(
                        {
                            "op": "remove",
                            "path": child,
                            "before": left[index],
                            "after": None,
                        }
                    )
                else:
                    visit(left[index], right[index], child)
            return
        changes.append(
            {"op": "replace", "path": current or "/", "before": left, "after": right}
        )

    visit(before, after, path)
    return [_json_copy(item) for item in changes]


def copy_story_scoped_character_resources(
    source_root: Path,
    destination_root: Path,
    source: Mapping[str, Any],
) -> None:
    """Copy author-owned character files into a project or published version."""

    source_base = source_root.resolve(strict=False)
    destination_base = destination_root.resolve(strict=False)
    characters_dir = source_base / "characters"
    if characters_dir.is_dir():
        _copy_tree(characters_dir, destination_base / "characters")
    cast = source.get("cast", {})
    if not isinstance(cast, Mapping):
        return
    for character in cast.get("characters", []):
        if not isinstance(character, Mapping):
            continue
        origin = character.get("source", {})
        if not isinstance(origin, Mapping):
            continue
        if str(origin.get("type") or "") not in _STORY_SCOPED_CHARACTER_TYPES:
            continue
        relative = str(origin.get("path") or "").strip()
        if not relative:
            continue
        try:
            src_file = safe_child_path(source_base, relative)
            dest_file = safe_child_path(destination_base, relative)
        except (OSError, PermissionError, ValueError):
            continue
        if not src_file.is_file():
            continue
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest_file)


def _copy_tree(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in {".", ".."} for part in relative.parts):
            continue
        try:
            target = safe_child_path(destination, relative.as_posix())
        except (OSError, PermissionError, ValueError):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _resource_dependencies(source: Mapping[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata", {})
    cast = source.get("cast", {})
    characters: list[dict[str, Any]] = []
    if isinstance(cast, Mapping):
        for character in cast.get("characters", []):
            if isinstance(character, Mapping):
                characters.append(
                    {
                        "characterId": character.get("id"),
                        "source": _json_copy(character.get("source", {})),
                    }
                )
    bindings = (
        metadata.get("resourceBindings", {}) if isinstance(metadata, Mapping) else {}
    )
    return {"bindings": _json_copy(bindings), "characters": characters}


def _save_compatibility(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    source_hash: str,
) -> dict[str, Any]:
    breaking: list[dict[str, str]] = []
    previous_variables = previous.get("variables", {}) if previous else {}
    current_variables = current.get("variables", {})
    if isinstance(previous_variables, Mapping) and isinstance(
        current_variables, Mapping
    ):
        for identifier, definition in previous_variables.items():
            if identifier not in current_variables:
                breaking.append({"code": "variable.removed", "id": str(identifier)})
            elif isinstance(definition, Mapping) and isinstance(
                current_variables[identifier], Mapping
            ):
                if definition.get("type") != current_variables[identifier].get("type"):
                    breaking.append(
                        {"code": "variable.type_changed", "id": str(identifier)}
                    )
    previous_nodes = {
        str(item.get("id"))
        for item in (previous or {}).get("narrativeGraph", {}).get("nodes", [])
        if isinstance(item, Mapping)
    }
    current_nodes = {
        str(item.get("id"))
        for item in current.get("narrativeGraph", {}).get("nodes", [])
        if isinstance(item, Mapping)
    }
    for identifier in sorted(previous_nodes.difference(current_nodes)):
        breaking.append({"code": "node.removed", "id": identifier})
    return {
        "schemaVersion": int(current.get("schemaVersion", 1)),
        "storyVersion": int(current.get("version", 1)),
        "sourceHash": source_hash,
        "compatibleWithPrevious": not breaking,
        "breakingChanges": breaking,
    }


def _pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _region_path_prefix(source: Mapping[str, Any], region: str) -> tuple[str, str, str]:
    kind, separator, identifier = region.partition(":")
    if not separator or not identifier:
        raise StoryAuthoringError(
            "authoring.region_invalid", "region must be kind:stable-id"
        )
    if kind == "node":
        items = source.get("narrativeGraph", {}).get("nodes", [])
        prefix_root = "/narrativeGraph/nodes"
    elif kind == "character":
        items = source.get("cast", {}).get("characters", [])
        prefix_root = "/cast/characters"
    elif kind == "signal":
        items = source.get("semanticSignals", [])
        prefix_root = "/semanticSignals"
    elif kind == "rule":
        items = source.get("logicGraph", {}).get("nodes", [])
        prefix_root = "/logicGraph/nodes"
    elif kind == "variable":
        variables = source.get("variables", {})
        if isinstance(variables, Mapping) and identifier in variables:
            return kind, identifier, f"/variables/{_pointer_escape(identifier)}"
        raise StoryAuthoringError(
            "authoring.region_not_found", f"authoring region {region!r} was not found"
        )
    else:
        raise StoryAuthoringError(
            "authoring.region_invalid", f"unsupported region {kind!r}"
        )
    if isinstance(items, list):
        for index, item in enumerate(items):
            if isinstance(item, Mapping) and item.get("id") == identifier:
                return kind, identifier, f"{prefix_root}/{index}"
    raise StoryAuthoringError(
        "authoring.region_not_found", f"authoring region {region!r} was not found"
    )


def _path_in_region(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _assert_patch_respects_region(
    source: Mapping[str, Any],
    operations: Sequence[Any],
    region: str,
) -> None:
    kind, identifier, prefix = _region_path_prefix(source, region)
    expected_replace = _REGION_REPLACE_OPS.get(kind)
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            raise StoryAuthoringError(
                "authoring.patch_invalid", f"operation {index} must be an object"
            )
        op = str(operation.get("op") or "")
        if op.startswith("replace-"):
            if expected_replace is None or op != expected_replace[0]:
                raise StoryAuthoringError(
                    "authoring.patch_region_violation",
                    f"operation {index} is outside authoring region {region!r}",
                )
            object_id = str(operation.get(expected_replace[1]) or "")
            if object_id != identifier:
                raise StoryAuthoringError(
                    "authoring.patch_region_violation",
                    f"operation {index} is outside authoring region {region!r}",
                )
            value = operation.get("value")
            if (
                isinstance(value, Mapping)
                and "id" in value
                and str(value.get("id")) != identifier
            ):
                raise StoryAuthoringError(
                    "authoring.patch_identity_changed",
                    f"operation {index} cannot change object identity",
                )
            continue
        raw_path = operation.get("path")
        if not isinstance(raw_path, str) or not _path_in_region(raw_path, prefix):
            raise StoryAuthoringError(
                "authoring.patch_region_violation",
                f"operation {index} is outside authoring region {region!r}",
            )
        if op == "remove" and raw_path == prefix:
            raise StoryAuthoringError(
                "authoring.patch_identity_changed",
                f"operation {index} cannot remove the selected region",
            )
        if raw_path == f"{prefix}/id":
            raise StoryAuthoringError(
                "authoring.patch_identity_changed",
                f"operation {index} cannot change object identity",
            )
        value = operation.get("value")
        if (
            op in {"add", "replace"}
            and raw_path == prefix
            and isinstance(value, Mapping)
            and "id" in value
            and str(value.get("id")) != identifier
        ):
            raise StoryAuthoringError(
                "authoring.patch_identity_changed",
                f"operation {index} cannot change object identity",
            )


def _select_authoring_region(source: Mapping[str, Any], region: str) -> Any:
    kind, separator, identifier = region.partition(":")
    if not separator or not identifier:
        raise StoryAuthoringError(
            "authoring.region_invalid", "region must be kind:stable-id"
        )
    collections: dict[str, Any] = {
        "node": source.get("narrativeGraph", {}).get("nodes", []),
        "character": source.get("cast", {}).get("characters", []),
        "variable": source.get("variables", {}),
        "signal": source.get("semanticSignals", []),
        "rule": source.get("logicGraph", {}).get("nodes", []),
    }
    if kind not in collections:
        raise StoryAuthoringError(
            "authoring.region_invalid", f"unsupported region {kind!r}"
        )
    collection = collections[kind]
    if isinstance(collection, Mapping) and identifier in collection:
        return _json_copy({identifier: collection[identifier]})
    if isinstance(collection, list):
        for item in collection:
            if isinstance(item, Mapping) and item.get("id") == identifier:
                return _json_copy(item)
    raise StoryAuthoringError(
        "authoring.region_not_found", f"authoring region {region!r} was not found"
    )


def _simulation_step(value: str) -> dict[str, str]:
    kind, _, remainder = value.partition(":")
    if kind in {"choice", "intent"}:
        _, _, identifier = remainder.partition("/")
        return {"type": kind, "id": identifier}
    if kind == "enter":
        return {"type": "enter", "id": remainder}
    raise StoryAuthoringError(
        "authoring.preview_path_invalid", f"unsupported simulation step {value!r}"
    )


def _safe_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", text):
        raise StoryAuthoringError(
            "authoring.invalid_id", f"{label} must be a stable safe identifier"
        )
    return text


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _now_ms() -> int:
    return int(time.time() * 1_000)
