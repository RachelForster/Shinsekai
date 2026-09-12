"""Resumable, feature-gated AI story compilation pipeline.

The author model only produces authoring artifacts.  Existing schema parsing,
compilation, simulation, and cast resolution remain the authority for anything
that can become a playable story.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Protocol
import uuid

import yaml

from ai.llm.template.story import (
    AUTHOR_COMPILER_TEMPLATE,
    StoryRequestContext,
    build_story_author_user_section,
)
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from core.story import (
    DiagnosticSeverity,
    StoryCompiler,
    StoryRuntime,
    StorySimulator,
    StoryValidationError,
    canonical_json,
    parse_story_project,
)


MAX_SYNOPSIS_CHARS = 20_000
MAX_ARTIFACT_BYTES = 2_000_000
MAX_PATCH_OPERATIONS = 32
MAX_REPAIR_ATTEMPTS = 3
_NATIVE_JSON_ADAPTERS = frozenset({"DeepSeekAdapter", "OpenAIAdapter", "ClaudeAdapter"})


class StoryGenerationStage(str, Enum):
    FOUNDATION = "foundation"
    CHARACTERS = "characters"
    NARRATIVE = "narrative"


GENERATION_STAGES = tuple(StoryGenerationStage)


class StoryGenerationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"


class StoryGenerationError(RuntimeError):
    def __init__(self, code: str, message: str, *, rejected_output: str = "") -> None:
        self.code = code
        self.rejected_output = rejected_output[:12_000]
        super().__init__(message)


class StoryGenerationCancelled(StoryGenerationError):
    def __init__(self) -> None:
        super().__init__("generation.cancelled", "story generation was cancelled")


class StoryAuthorModelPort(Protocol):
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class GenerationValidationIssue:
    code: str
    message: str
    path: str = ""
    severity: str = "error"

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class GenerationValidationReport:
    valid: bool
    issues: tuple[GenerationValidationIssue, ...]
    reachable_node_ids: tuple[str, ...] = ()
    ending_node_ids: tuple[str, ...] = ()
    reachable_ending_ids: tuple[str, ...] = ()
    cast_failure_node_ids: tuple[str, ...] = ()
    explored_states: int = 0
    source_hash: str = ""

    @property
    def ending_coverage(self) -> float:
        if not self.ending_node_ids:
            return 0.0
        return len(self.reachable_ending_ids) / len(self.ending_node_ids)

    def to_payload(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [item.to_payload() for item in self.issues],
            "reachableNodeIds": list(self.reachable_node_ids),
            "endingNodeIds": list(self.ending_node_ids),
            "reachableEndingIds": list(self.reachable_ending_ids),
            "castFailureNodeIds": list(self.cast_failure_node_ids),
            "exploredStates": self.explored_states,
            "endingCoverage": self.ending_coverage,
            "sourceHash": self.source_hash,
        }


class ConfigStoryAuthorModel:
    """Lazy adapter over the existing configured LLM JSON interface."""

    def __init__(self, flags: FeatureFlagConfigManager, config_manager: Any) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.config_manager = config_manager
        self._manager: Any = None
        self._signature: tuple[tuple[str, str], ...] = ()

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        manager = self._llm_manager()
        adapter = getattr(manager, "llm_adapter", None)
        if adapter is None or not hasattr(adapter, "chat"):
            raise StoryGenerationError(
                "generation.model_not_configured",
                "story author LLM adapter is missing",
            )
        prompt = build_story_author_user_section().render(StoryRequestContext(request))
        messages = [
            {"role": "system", "content": AUTHOR_COMPILER_TEMPLATE},
            {"role": "user", "content": prompt},
        ]
        chat_kwargs: dict[str, Any] = {}
        if type(adapter).__name__ in _NATIVE_JSON_ADAPTERS:
            chat_kwargs["response_format"] = {"type": "json_object"}
        response = adapter.chat(messages, stream=False, **chat_kwargs)
        return _parse_json_mapping(_adapter_text_content(response))

    def _llm_manager(self) -> Any:
        provider, model, base_url, api_key = self.config_manager.get_llm_api_config()
        if not provider or not model or not api_key:
            raise StoryGenerationError(
                "generation.model_not_configured",
                "story author LLM provider, model, or API key is missing",
            )
        factory_kwargs = self.config_manager.merged_llm_factory_kwargs(
            provider,
            {
                "llm_provider": provider,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            },
        )
        signature = tuple(
            sorted((str(key), repr(value)) for key, value in factory_kwargs.items())
        )
        if self._manager is None or signature != self._signature:
            from ai.llm.llm_manager import LLMAdapterFactory, LLMManager

            adapter = LLMAdapterFactory.create_adapter(**factory_kwargs)
            self._manager = LLMManager(
                adapter=adapter,
                user_template=AUTHOR_COMPILER_TEMPLATE,
            )
            self._signature = signature
        return self._manager


class StoryGenerationRepository:
    """Atomic on-disk task and artifact checkpoints."""

    def __init__(self, flags: FeatureFlagConfigManager, root: str | Path) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.root = Path(root).expanduser().resolve(strict=False)
        self._save_lock = threading.RLock()

    def create(self, task: Mapping[str, Any]) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        task_id = _safe_id(task.get("id"), "task id")
        directory = self.root / task_id
        if directory.exists():
            raise StoryGenerationError(
                "generation.task_exists", f"generation task {task_id!r} already exists"
            )
        directory.mkdir(parents=True, exist_ok=False)
        payload = _json_copy(task)
        self._write_json(directory / "task.json", payload)
        return payload

    def load(self, task_id: str) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        path = self._task_dir(task_id) / "task.json"
        if not path.is_file():
            raise StoryGenerationError(
                "generation.task_not_found",
                f"generation task {task_id!r} was not found",
            )
        return self._read_json(path)

    def save(
        self, task: Mapping[str, Any], *, preserve_cancel: bool = True
    ) -> dict[str, Any]:
        with self._save_lock:
            self.flags.require(FeatureFlag.STORY_SYSTEM)
            task_id = _safe_id(task.get("id"), "task id")
            payload = _json_copy(task)
            existing: dict[str, Any] = {}
            path = self._task_dir(task_id) / "task.json"
            if path.is_file():
                existing = self._read_json(path)
            if preserve_cancel:
                if existing.get("cancelRequested"):
                    payload["cancelRequested"] = True
                    payload["status"] = StoryGenerationStatus.CANCELLED.value
            payload["updatedAt"] = max(_now_ms(), int(existing.get("updatedAt", 0)) + 1)
            self._write_json(self._task_dir(task_id) / "task.json", payload)
            return payload

    def save_artifact(
        self,
        task_id: str,
        stage: StoryGenerationStage,
        artifact: Mapping[str, Any],
    ) -> str:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        payload = _json_copy(artifact)
        encoded = canonical_json(payload).encode("utf-8")
        if len(encoded) > MAX_ARTIFACT_BYTES:
            raise StoryGenerationError(
                "generation.artifact_too_large",
                f"{stage.value} artifact exceeds {MAX_ARTIFACT_BYTES} bytes",
            )
        directory = self._task_dir(task_id) / "artifacts"
        directory.mkdir(parents=True, exist_ok=True)
        self._write_json(directory / f"{stage.value}.json", payload)
        return hashlib.sha256(encoded).hexdigest()

    def load_artifact(
        self, task_id: str, stage: StoryGenerationStage
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        path = self._task_dir(task_id) / "artifacts" / f"{stage.value}.json"
        if not path.is_file():
            raise StoryGenerationError(
                "generation.artifact_missing",
                f"artifact {stage.value!r} is missing for task {task_id!r}",
            )
        return self._read_json(path)

    def delete_artifacts_from(self, task_id: str, stage: StoryGenerationStage) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        start = GENERATION_STAGES.index(stage)
        directory = self._task_dir(task_id) / "artifacts"
        for item in GENERATION_STAGES[start:]:
            (directory / f"{item.value}.json").unlink(missing_ok=True)
        (self._task_dir(task_id) / "draft.json").unlink(missing_ok=True)
        if start <= GENERATION_STAGES.index(StoryGenerationStage.CHARACTERS):
            characters_dir = self._task_dir(task_id) / "characters"
            if characters_dir.is_dir():
                shutil.rmtree(characters_dir)

    def save_character_profile(
        self, task_id: str, character_id: str, profile: Mapping[str, Any]
    ) -> Path:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        path = self._task_dir(task_id) / "characters" / f"{character_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = yaml.safe_dump(
            _json_copy(profile),
            allow_unicode=True,
            sort_keys=True,
        )
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def save_draft(self, task_id: str, source: Mapping[str, Any]) -> Path:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        path = self._task_dir(task_id) / "draft.json"
        self._write_json(path, source)
        return path

    def load_draft(self, task_id: str) -> dict[str, Any] | None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        path = self._task_dir(task_id) / "draft.json"
        if not path.is_file():
            return None
        return self._read_json(path)

    def task_directory(self, task_id: str) -> Path:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        return self._task_dir(task_id)

    def _task_dir(self, task_id: str) -> Path:
        safe = _safe_id(task_id, "task id")
        target = (self.root / safe).resolve(strict=False)
        if target.parent != self.root:
            raise StoryGenerationError(
                "generation.invalid_task_id", "task path escaped generation root"
            )
        return target

    def _read_json(self, path: Path) -> dict[str, Any]:
        with self._save_lock:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise StoryGenerationError(
                    "generation.checkpoint_invalid", f"cannot read {path.name}: {error}"
                ) from error
            if not isinstance(value, dict):
                raise StoryGenerationError(
                    "generation.checkpoint_invalid",
                    f"{path.name} must contain an object",
                )
            return value

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        with self._save_lock:
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
                for attempt in range(6):
                    try:
                        os.replace(temporary, path)
                        break
                    except PermissionError:
                        # Windows readers or scanners may briefly deny replacement.
                        if attempt == 5:
                            raise
                        time.sleep(0.02 * (2 ** attempt))
            finally:
                temporary.unlink(missing_ok=True)


class StoryPatchApplier:
    """Apply a bounded authoring patch; never execute model-provided code."""

    _TOP_LEVEL = frozenset(
        {
            "metadata",
            "cast",
            "narrativeGraph",
        }
    )
    _IMMUTABLE_PREFIXES = (
        ("metadata", "resourceBindings"),
        ("metadata", "backgrounds"),
        ("cast", "defaults"),
        ("cast", "initialCast"),
    )

    def apply(
        self,
        source: Mapping[str, Any],
        patch: Mapping[str, Any],
        *,
        base_version: int,
    ) -> dict[str, Any]:
        candidate = _json_copy(source)
        if patch.get("baseVersion") != base_version:
            raise StoryGenerationError(
                "generation.patch_version_mismatch", "patch baseVersion is stale"
            )
        operations = patch.get("operations")
        if not isinstance(operations, list) or not operations:
            raise StoryGenerationError(
                "generation.patch_invalid", "patch operations must be a non-empty array"
            )
        if len(operations) > MAX_PATCH_OPERATIONS:
            raise StoryGenerationError(
                "generation.patch_too_large",
                f"patch has more than {MAX_PATCH_OPERATIONS} operations",
            )
        for index, operation in enumerate(operations):
            if not isinstance(operation, Mapping):
                raise StoryGenerationError(
                    "generation.patch_invalid", f"operation {index} must be an object"
                )
            self._apply_operation(candidate, operation, index)
        candidate["version"] = base_version + 1
        return candidate

    def _apply_operation(
        self, source: dict[str, Any], operation: Mapping[str, Any], index: int
    ) -> None:
        op = str(operation.get("op") or "")
        if op.startswith("replace-"):
            self._replace_domain_object(source, operation, index)
            return
        if op not in {"add", "replace", "remove"}:
            raise StoryGenerationError(
                "generation.patch_op_forbidden",
                f"operation {index} uses forbidden op {op!r}",
            )
        raw_path = operation.get("path")
        if not isinstance(raw_path, str) or not raw_path.startswith("/"):
            raise StoryGenerationError(
                "generation.patch_invalid", f"operation {index} has an invalid path"
            )
        tokens = [_decode_pointer(item) for item in raw_path.split("/")[1:]]
        if not tokens or tokens[0] not in self._TOP_LEVEL:
            raise StoryGenerationError(
                "generation.patch_path_forbidden",
                f"operation {index} cannot modify {raw_path!r}",
            )
        token_path = tuple(tokens)
        if any(
            token_path[: len(prefix)] == prefix
            or prefix[: len(token_path)] == token_path
            for prefix in self._IMMUTABLE_PREFIXES
        ):
            raise StoryGenerationError(
                "generation.patch_path_forbidden",
                f"operation {index} cannot modify derived path {raw_path!r}",
            )
        if any(item in {"", ".", ".."} for item in tokens):
            raise StoryGenerationError(
                "generation.patch_path_forbidden",
                f"operation {index} has an unsafe path",
            )
        parent, key = _resolve_pointer_parent(source, tokens)
        if isinstance(parent, list):
            position = _list_position(key, len(parent), allow_end=op == "add")
            if op == "add":
                parent.insert(position, _json_value(operation.get("value")))
            elif op == "replace":
                parent[position] = _json_value(operation.get("value"))
            else:
                parent.pop(position)
        elif isinstance(parent, dict):
            exists = key in parent
            if op in {"replace", "remove"} and not exists:
                raise StoryGenerationError(
                    "generation.patch_path_missing", f"path {raw_path!r} does not exist"
                )
            if op == "remove":
                del parent[key]
            else:
                parent[key] = _json_value(operation.get("value"))
        else:
            raise StoryGenerationError(
                "generation.patch_path_invalid", f"path {raw_path!r} has no container"
            )

    @staticmethod
    def _replace_domain_object(
        source: dict[str, Any], operation: Mapping[str, Any], index: int
    ) -> None:
        specs = {
            "replace-node": ("nodeId", source.get("narrativeGraph", {}).get("nodes")),
            "replace-character": (
                "characterId",
                source.get("cast", {}).get("characters"),
            ),
        }
        op = str(operation.get("op") or "")
        if op not in specs:
            raise StoryGenerationError(
                "generation.patch_op_forbidden",
                f"operation {index} uses forbidden op {op!r}",
            )
        id_field, collection = specs[op]
        object_id = _safe_id(operation.get(id_field), id_field)
        value = operation.get("value")
        if not isinstance(value, Mapping):
            raise StoryGenerationError(
                "generation.patch_invalid", f"operation {index} value must be an object"
            )
        if isinstance(collection, list):
            for position, item in enumerate(collection):
                if isinstance(item, Mapping) and item.get("id") == object_id:
                    replacement = _json_copy(value)
                    if replacement.get("id", object_id) != object_id:
                        raise StoryGenerationError(
                            "generation.patch_identity_changed",
                            f"operation {index} cannot change object identity",
                        )
                    replacement["id"] = object_id
                    collection[position] = replacement
                    return
        elif isinstance(collection, dict) and object_id in collection:
            collection[object_id] = _json_copy(value)
            return
        raise StoryGenerationError(
            "generation.patch_target_missing", f"operation {index} target was not found"
        )


class StoryDraftValidator:
    def validate(
        self,
        source: Mapping[str, Any],
        *,
        foundation: Mapping[str, Any] | None = None,
    ) -> GenerationValidationReport:
        issues: list[GenerationValidationIssue] = []
        source_hash = hashlib.sha256(canonical_json(source).encode("utf-8")).hexdigest()
        try:
            project = parse_story_project(source)
        except StoryValidationError as error:
            for diagnostic in error.diagnostics:
                issues.append(
                    GenerationValidationIssue(
                        code=diagnostic.code,
                        message=diagnostic.message,
                        path=diagnostic.path,
                        severity=diagnostic.severity.value,
                    )
                )
            return GenerationValidationReport(
                valid=False, issues=tuple(issues), source_hash=source_hash
            )

        compile_result = StoryCompiler().compile_with_diagnostics(project)
        for diagnostic in compile_result.diagnostics:
            issues.append(
                GenerationValidationIssue(
                    code=diagnostic.code,
                    message=diagnostic.message,
                    path=diagnostic.path,
                    severity=diagnostic.severity.value,
                )
            )
        if compile_result.program is None:
            return GenerationValidationReport(
                valid=False, issues=tuple(issues), source_hash=source_hash
            )

        runtime = StoryRuntime(compile_result.program)
        try:
            simulation = StorySimulator(
                runtime, max_states=2_000, max_depth=150
            ).simulate()
        except Exception as error:
            issues.append(
                GenerationValidationIssue(
                    "simulation.failed", str(error), "/narrativeGraph"
                )
            )
            return GenerationValidationReport(
                valid=False, issues=tuple(issues), source_hash=source_hash
            )
        node_ids = {node.id for node in compile_result.program.nodes}
        ending_ids = {
            node.id
            for node in compile_result.program.nodes
            if node.type in {"ending", "ending_node"}
        }
        unreachable = node_ids.difference(simulation.reachable_node_ids)
        if unreachable:
            issues.append(
                GenerationValidationIssue(
                    "simulation.unreachable_nodes",
                    f"unreachable nodes: {', '.join(sorted(unreachable))}",
                    "/narrativeGraph/nodes",
                )
            )
        if not ending_ids:
            issues.append(
                GenerationValidationIssue(
                    "simulation.no_ending",
                    "story must define at least one ending",
                    "/narrativeGraph",
                )
            )
        unreachable_endings = ending_ids.difference(simulation.ending_paths)
        if unreachable_endings:
            issues.append(
                GenerationValidationIssue(
                    "simulation.unreachable_endings",
                    f"unreachable endings: {', '.join(sorted(unreachable_endings))}",
                    "/narrativeGraph/nodes",
                )
            )
        for node_id, code in simulation.cast_resolution_failures.items():
            issues.append(
                GenerationValidationIssue(
                    "cast.simulation_failed",
                    f"cast resolution failed with {code}",
                    f"/narrativeGraph/nodes/{node_id}/castPolicy",
                )
            )
        issues.extend(_secret_isolation_issues(source, foundation or {}))
        if simulation.truncated:
            issues.append(
                GenerationValidationIssue(
                    "simulation.truncated",
                    "path simulation reached its configured limit",
                    "/narrativeGraph",
                    "warning",
                )
            )
        valid = not any(
            item.severity == DiagnosticSeverity.ERROR.value for item in issues
        )
        return GenerationValidationReport(
            valid=valid,
            issues=tuple(issues),
            reachable_node_ids=tuple(sorted(simulation.reachable_node_ids)),
            ending_node_ids=tuple(sorted(ending_ids)),
            reachable_ending_ids=tuple(sorted(simulation.ending_paths)),
            cast_failure_node_ids=tuple(sorted(simulation.cast_resolution_failures)),
            explored_states=simulation.explored_states,
            source_hash=source_hash,
        )


class StoryGenerationService:
    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        repository: StoryGenerationRepository,
        model: StoryAuthorModelPort,
        *,
        validator: StoryDraftValidator | None = None,
        patch_applier: StoryPatchApplier | None = None,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.repository = repository
        self.model = model
        self.validator = validator or StoryDraftValidator()
        self.patch_applier = patch_applier or StoryPatchApplier()
        self._guard = threading.Lock()
        self._task_locks: dict[str, threading.Lock] = {}
        self._active_runs: set[str] = set()

    def _lock_for(self, task_id: str) -> threading.Lock:
        with self._guard:
            return self._task_locks.setdefault(task_id, threading.Lock())

    def create(
        self,
        synopsis: str,
        *,
        options: Mapping[str, Any] | None = None,
        resource_catalog: Mapping[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        normalized = str(synopsis).strip()
        if not normalized:
            raise StoryGenerationError(
                "generation.synopsis_required", "story synopsis is required"
            )
        if len(normalized) > MAX_SYNOPSIS_CHARS:
            raise StoryGenerationError(
                "generation.synopsis_too_large",
                f"story synopsis exceeds {MAX_SYNOPSIS_CHARS} characters",
            )
        now = _now_ms()
        payload = {
            "id": _safe_id(task_id or uuid.uuid4().hex, "task id"),
            "synopsis": normalized,
            "options": _json_copy(options or {}),
            "resourceCatalog": {
                "backgrounds": list(_background_ids(resource_catalog)),
                **(
                    {"characters": _json_value(resource_catalog["characters"])}
                    if resource_catalog and resource_catalog.get("characters")
                    else {}
                ),
            },
            "status": StoryGenerationStatus.QUEUED.value,
            "currentStage": StoryGenerationStage.FOUNDATION.value,
            "completedStages": [],
            "artifactHashes": {},
            "assumptions": [],
            "validation": None,
            "cost": {
                "requests": 0,
                "inputChars": 0,
                "outputChars": 0,
                "estimatedTokens": 0,
            },
            "repairAttempts": 0,
            "cancelRequested": False,
            "error": None,
            "draftPath": "",
            "createdAt": now,
            "updatedAt": now,
        }
        return self.repository.create(payload)

    def get(self, task_id: str) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        return self._public_task(self.repository.load(task_id))

    def cancel(self, task_id: str) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock_for(task_id):
            task = self.repository.load(task_id)
            if task["status"] not in {
                StoryGenerationStatus.SUCCEEDED.value,
            }:
                task["cancelRequested"] = True
                task["status"] = StoryGenerationStatus.CANCELLED.value
                task = self.repository.save(task, preserve_cancel=False)
            return self._public_task(task)

    def regenerate_from(
        self, task_id: str, stage: StoryGenerationStage | str
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        selected = StoryGenerationStage(stage)
        with self._lock_for(task_id):
            if task_id in self._active_runs:
                raise StoryGenerationError(
                    "generation.already_running",
                    f"generation task {task_id!r} is already running",
                )
            task = self.repository.load(task_id)
            start = GENERATION_STAGES.index(selected)
            completed = [
                item.value
                for item in GENERATION_STAGES[:start]
                if item.value in task.get("completedStages", [])
            ]
            hashes = task.get("artifactHashes")
            task["artifactHashes"] = {
                key: value
                for key, value in (hashes.items() if isinstance(hashes, dict) else [])
                if key in completed
            }
            task.update(
                {
                    "status": StoryGenerationStatus.QUEUED.value,
                    "currentStage": selected.value,
                    "completedStages": completed,
                    "validation": None,
                    "repairAttempts": 0,
                    "cancelRequested": False,
                    "error": None,
                    "draftPath": "",
                    "recovery": None,
                    "recoveryContext": None,
                }
            )
            task = self.repository.save(task, preserve_cancel=False)
            self.repository.delete_artifacts_from(task_id, selected)
            return self._public_task(task)

    def run(
        self,
        task_id: str,
        *,
        resume: bool = False,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        with self._lock_for(task_id):
            if task_id in self._active_runs:
                raise StoryGenerationError(
                    "generation.already_running",
                    f"generation task {task_id!r} is already running",
                )
            self._active_runs.add(task_id)
        try:
            task = self.repository.load(task_id)
            return self._run_locked(
                task_id,
                task,
                resume=resume,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
            )
        finally:
            with self._lock_for(task_id):
                self._active_runs.discard(task_id)

    def _run_locked(
        self,
        task_id: str,
        task: dict[str, Any],
        *,
        resume: bool,
        is_cancelled: Callable[[], bool] | None,
        on_progress: Callable[[Mapping[str, Any]], None] | None,
    ) -> dict[str, Any]:
        if task.get("status") == StoryGenerationStatus.SUCCEEDED.value:
            return self._public_task(task)
        if not resume and (
            task.get("cancelRequested") or (is_cancelled and is_cancelled())
        ):
            task.update(
                {
                    "status": StoryGenerationStatus.CANCELLED.value,
                    "cancelRequested": True,
                    "error": {"code": "generation.cancelled", "message": "cancelled"},
                }
            )
            self.repository.save(task, preserve_cancel=False)
            raise StoryGenerationCancelled()
        task.update(
            {
                "status": StoryGenerationStatus.RUNNING.value,
                "error": None,
            }
        )
        if resume:
            task["cancelRequested"] = False
        task = self.repository.save(task, preserve_cancel=not resume)
        if task.get("cancelRequested") and not resume:
            raise StoryGenerationCancelled()
        request: Mapping[str, Any] = {}
        response: Mapping[str, Any] = {}
        try:
            for stage in GENERATION_STAGES:
                if stage.value in task.get("completedStages", []):
                    continue
                self._check_cancel(task_id, is_cancelled)
                task["currentStage"] = stage.value
                task = self.repository.save(task)
                self._notify(on_progress, task, stage)
                request = self._stage_request(task, stage)
                response = {}
                response = self._complete(task, request)
                self._check_cancel(task_id, is_cancelled)
                artifact = self._validate_stage_response(
                    stage,
                    response,
                    resource_catalog=task.get("resourceCatalog", {}),
                )
                digest = self.repository.save_artifact(task_id, stage, artifact)
                completed = list(task.get("completedStages", []))
                completed.append(stage.value)
                task["completedStages"] = completed
                task.setdefault("artifactHashes", {})[stage.value] = digest
                if stage is StoryGenerationStage.FOUNDATION:
                    task["assumptions"] = list(artifact.get("assumptions") or [])
                if stage is StoryGenerationStage.CHARACTERS:
                    self._materialize_author_characters(task_id, artifact)
                task["recoveryContext"] = None
                task = self.repository.save(task)
                self._notify(on_progress, task, stage)

            self._check_cancel(task_id, is_cancelled)
            source = self._compose_source(task_id)
            report = self.validator.validate(
                source,
                foundation=self.repository.load_artifact(
                    task_id, StoryGenerationStage.FOUNDATION
                ),
            )
            task["validation"] = report.to_payload()
            self.repository.save_draft(task_id, source)
            task = self.repository.save(task)
            repairs_this_run = 0
            while not report.valid and repairs_this_run < MAX_REPAIR_ATTEMPTS:
                self._check_cancel(task_id, is_cancelled)
                task["currentStage"] = "repair"
                request = self._repair_request(task, source, report)
                task["repairAttempts"] = int(task.get("repairAttempts", 0)) + 1
                repairs_this_run += 1
                task = self.repository.save(task)
                self._notify(on_progress, task, None)
                response = {}
                response = self._complete(task, request)
                self._check_cancel(task_id, is_cancelled)
                source = self.patch_applier.apply(
                    source, response, base_version=int(source["version"])
                )
                self._checkpoint_repaired_source(task, source)
                task["recoveryContext"] = None
                report = self.validator.validate(
                    source,
                    foundation=self.repository.load_artifact(
                        task_id, StoryGenerationStage.FOUNDATION
                    ),
                )
                task["validation"] = report.to_payload()
                task = self.repository.save(task)
                self._notify(on_progress, task, None)
            task["validation"] = report.to_payload()
            if not report.valid:
                raise StoryGenerationError(
                    "generation.validation_failed",
                    "generated story did not pass validation after bounded repair",
                )
            self._materialize_author_characters(
                task_id,
                self.repository.load_artifact(task_id, StoryGenerationStage.CHARACTERS),
            )
            draft_path = self.repository.save_draft(task_id, source)
            self._check_cancel(task_id, is_cancelled)
            task.update(
                {
                    "status": StoryGenerationStatus.SUCCEEDED.value,
                    "currentStage": "complete",
                    "draftPath": str(draft_path),
                    "error": None,
                    "recovery": None,
                    "recoveryContext": None,
                }
            )
            task = self.repository.save(task)
            self._notify(on_progress, task, None)
            return self._public_task(task)
        except StoryGenerationCancelled:
            task = self.repository.load(task_id)
            task.update(
                {
                    "status": StoryGenerationStatus.CANCELLED.value,
                    "cancelRequested": True,
                    "error": {"code": "generation.cancelled", "message": "cancelled"},
                }
            )
            self.repository.save(task, preserve_cancel=False)
            raise
        except Exception as error:
            task = self.repository.load(task_id)
            code = getattr(error, "code", "generation.stage_failed")
            task.update(
                {
                    "status": StoryGenerationStatus.FAILED.value,
                    "error": {"code": str(code), "message": str(error)},
                    "recoveryContext": {
                        "operation": request.get("operation", "validate"),
                        "stage": task.get("currentStage"),
                        "error": {"code": str(code), "message": str(error)},
                        "validationIssues": (task.get("validation") or {}).get(
                            "issues", []
                        ),
                        "rejectedOutput": getattr(error, "rejected_output", "")
                        or json.dumps(response, ensure_ascii=False)[:12_000],
                        "instruction": "Correct the reported errors in your next response. Preserve the supplied resources and all valid completed stages.",
                    },
                }
            )
            self.repository.save(task)
            raise

    def _complete(
        self, task: dict[str, Any], request: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        # Count unsuccessful author calls as well as accepted artifacts.
        response: Mapping[str, Any] = {}
        try:
            response = self.model.complete(request)
            return response
        except StoryGenerationError:
            raise
        except Exception as error:
            # Network TimeoutError/ConnectionError also inherit OSError. Keep them
            # distinct from storage failures so the recovery worker retries them.
            raise StoryGenerationError(
                "generation.model_request_failed", str(error)
            ) from error
        finally:
            task["cost"] = _updated_cost(task.get("cost"), request, response)
            self.repository.save(task)

    def _stage_request(
        self, task: Mapping[str, Any], stage: StoryGenerationStage
    ) -> dict[str, Any]:
        completed: dict[str, Any] = {}
        for item in GENERATION_STAGES:
            if item.value in task.get("completedStages", []):
                completed[item.value] = self.repository.load_artifact(
                    str(task["id"]), item
                )
        constraints: dict[str, Any] = {
            "maxNodes": 25,
            "maxCharacters": 128,
            "charactersAreAStoryWidePool": True,
            "doNotAssignCharactersToIndividualNodes": True,
            "doNotOverrideChatTemplateOrOutputFormat": True,
        }
        resource_catalog: dict[str, Any] = {}
        selected_characters = task.get("resourceCatalog", {}).get("characters")
        if selected_characters:
            resource_catalog["characters"] = selected_characters
            constraints["charactersAreNarrativeReferences"] = True
            constraints["respectPrimaryAndSecondaryCharacterSettings"] = True
        if stage is StoryGenerationStage.NARRATIVE:
            constraints["backgroundsAreOptionalNarrativeHints"] = True
            resource_catalog.update(task.get("resourceCatalog", {}))
        return {
            "protocol": "shinsekai.story-generation.v1",
            "operation": "generate-stage",
            "stage": stage.value,
            "synopsis": task["synopsis"],
            "options": task.get("options", {}),
            "resourceCatalog": resource_catalog,
            "completedArtifacts": completed,
            "constraints": constraints,
            "responseSchema": _stage_schema(stage),
            "correctionFeedback": task.get("recoveryContext"),
        }

    def _repair_request(
        self,
        task: Mapping[str, Any],
        source: Mapping[str, Any],
        report: GenerationValidationReport,
    ) -> dict[str, Any]:
        return {
            "protocol": "shinsekai.story-patch.v1",
            "operation": "repair",
            "baseVersion": source["version"],
            "story": source,
            "validationIssues": [item.to_payload() for item in report.issues],
            "constraints": {
                "maxOperations": MAX_PATCH_OPERATIONS,
                "allowedOperations": [
                    "add",
                    "replace",
                    "remove",
                    "replace-node",
                    "replace-character",
                ],
                "immutablePaths": [
                    "/schemaVersion",
                    "/id",
                    "/status",
                    "/startNodeId",
                    "/variables",
                    "/semanticSignals",
                    "/logicGraph",
                    "/metadata/backgrounds",
                    "/metadata/resourceBindings",
                    "/cast/defaults",
                    "/cast/initialCast",
                ],
            },
            "responseSchema": {
                "baseVersion": "integer matching request",
                "operations": "1..32 bounded patch operation objects",
            },
            "attempt": int(task.get("repairAttempts", 0)) + 1,
            "correctionFeedback": task.get("recoveryContext"),
        }

    def _compose_source(self, task_id: str) -> dict[str, Any]:
        draft = self.repository.load_draft(task_id)
        if draft is not None:
            return draft
        foundation = self.repository.load_artifact(
            task_id, StoryGenerationStage.FOUNDATION
        )
        characters = self.repository.load_artifact(
            task_id, StoryGenerationStage.CHARACTERS
        )
        narrative = self.repository.load_artifact(
            task_id, StoryGenerationStage.NARRATIVE
        )
        story_id = _safe_id(foundation.get("id") or f"story-{task_id[:12]}", "story id")
        character_rows = list(characters.get("characters") or [])
        task = self.repository.load(task_id)
        selected = task.get("resourceCatalog", {}).get("characters", [])
        character_ids = [
            str(character.get("id"))
            for character in character_rows
            if isinstance(character, Mapping) and character.get("id")
        ]
        from .selection import TEMPLATE_OPTION_KEYS

        source = {
            "schemaVersion": 1,
            "id": story_id,
            "version": 1,
            "title": _required_text(foundation.get("title"), "foundation.title", 200),
            "status": "draft",
            "startNodeId": narrative.get("startNodeId"),
            "metadata": {
                **(
                    {
                        "resourceBindings": {
                            "openingBackground": task["options"].get(
                                "backgroundName", ""
                            ),
                            "characters": task["options"].get("characters", []),
                            "primaryCharacters": task["options"].get(
                                "primaryCharacters", []
                            ),
                            "characterPromptMode": task["options"].get(
                                "characterPromptMode", "full"
                            ),
                            "scenario": task["synopsis"],
                            "templateOptions": {
                                key: task["options"][key]
                                for key in TEMPLATE_OPTION_KEYS if key in task["options"]
                            },
                        }
                    }
                    if selected
                    else {}
                ),
                "language": foundation.get("language", "zh-CN"),
                "estimatedMinutes": foundation.get("estimatedMinutes"),
                "generationMode": "ai",
                "backgrounds": list(
                    _background_ids(
                        self.repository.load(task_id).get("resourceCatalog")
                    )
                ),
            },
            "variables": {},
            "semanticSignals": [],
            "cast": {
                "defaults": {
                    "maxActive": max(1, len(character_ids)),
                    "preserveCurrentCast": True,
                },
                "initialCast": character_ids,
                "characters": character_rows,
            },
            "narrativeGraph": narrative,
            "logicGraph": {"version": 1, "nodes": [], "edges": []},
        }
        return _json_copy(source)

    def _checkpoint_repaired_source(
        self, task: dict[str, Any], source: Mapping[str, Any]
    ) -> None:
        task_id = str(task["id"])
        hashes = task.setdefault("artifactHashes", {})
        folded = self._artifacts_from_source(task_id, source)
        for stage, artifact in folded.items():
            hashes[stage.value] = self.repository.save_artifact(
                task_id, stage, artifact
            )
            if stage is StoryGenerationStage.CHARACTERS:
                self._materialize_author_characters(task_id, artifact)
        draft_path = self.repository.save_draft(task_id, source)
        task["draftPath"] = str(draft_path)

    def _artifacts_from_source(
        self, task_id: str, source: Mapping[str, Any]
    ) -> dict[StoryGenerationStage, dict[str, Any]]:
        foundation = self.repository.load_artifact(
            task_id, StoryGenerationStage.FOUNDATION
        )
        foundation.update(
            {
                "id": source.get("id", foundation.get("id")),
                "title": source.get("title", foundation.get("title")),
                "language": (source.get("metadata") or {}).get(
                    "language", foundation.get("language")
                ),
                "estimatedMinutes": (source.get("metadata") or {}).get(
                    "estimatedMinutes", foundation.get("estimatedMinutes")
                ),
            }
        )
        cast = source.get("cast") if isinstance(source.get("cast"), Mapping) else {}
        return {
            StoryGenerationStage.FOUNDATION: _json_copy(foundation),
            StoryGenerationStage.CHARACTERS: _json_copy(
                {
                    "characters": list(cast.get("characters") or []),
                }
            ),
            StoryGenerationStage.NARRATIVE: _json_copy(
                source.get("narrativeGraph")
                if isinstance(source.get("narrativeGraph"), Mapping)
                else {}
            ),
        }

    def _materialize_author_characters(
        self, task_id: str, artifact: Mapping[str, Any]
    ) -> None:
        characters = artifact.get("characters")
        if not isinstance(characters, list):
            return
        for character in characters:
            if not isinstance(character, Mapping):
                continue
            source = character.get("source")
            if not isinstance(source, Mapping):
                continue
            if str(source.get("type") or "") != "author-generated":
                continue
            character_id = _safe_id(character.get("id"), "character id")
            self.repository.save_character_profile(
                task_id,
                character_id,
                {
                    "id": character_id,
                    "name": str(character.get("name") or character_id).strip()
                    or character_id,
                    "characterSetting": str(
                        character.get("responsibility")
                        or character.get("characterSetting")
                        or ""
                    ).strip(),
                    "sprites": [],
                    "live2d": {},
                    "tts": {},
                    "toolPermissions": [],
                },
            )

    def _validate_stage_response(
        self,
        stage: StoryGenerationStage,
        response: Mapping[str, Any],
        *,
        resource_catalog: Mapping[str, Any],
    ) -> dict[str, Any]:
        artifact = response.get("artifact", response)
        if not isinstance(artifact, Mapping):
            raise StoryGenerationError(
                "generation.stage_protocol_invalid",
                f"{stage.value} response must contain an artifact object",
            )
        value = _json_copy(artifact)
        validators: dict[StoryGenerationStage, Callable[[dict[str, Any]], None]] = {
            StoryGenerationStage.FOUNDATION: _validate_foundation,
            StoryGenerationStage.CHARACTERS: _validate_characters,
        }
        if stage is StoryGenerationStage.NARRATIVE:
            _validate_narrative(value, backgrounds=_background_ids(resource_catalog))
        else:
            validators[stage](value)
        return value

    def _check_cancel(
        self, task_id: str, is_cancelled: Callable[[], bool] | None
    ) -> None:
        task = self.repository.load(task_id)
        if task.get("cancelRequested") or (is_cancelled and is_cancelled()):
            raise StoryGenerationCancelled()

    @staticmethod
    def _notify(
        callback: Callable[[Mapping[str, Any]], None] | None,
        task: Mapping[str, Any],
        stage: StoryGenerationStage | None,
    ) -> None:
        if callback is None:
            return
        completed = len(task.get("completedStages", []))
        callback(
            {
                "phase": str(
                    task.get("currentStage") or (stage.value if stage else "running")
                ),
                "progress": min(completed / (len(GENERATION_STAGES) + 1), 0.95),
                "message": f"Story generation: {task.get('currentStage', 'running')}",
                "generationTask": StoryGenerationService._public_task(task),
            }
        )

    @staticmethod
    def _public_task(task: Mapping[str, Any]) -> dict[str, Any]:
        return _json_copy(task)


_service_creation_lock = threading.Lock()


def story_generation_service_for_state(state: Any) -> StoryGenerationService:
    with _service_creation_lock:
        return _create_story_generation_service(state)


def _create_story_generation_service(state: Any) -> StoryGenerationService:
    flags = state.config_manager.feature_flags
    flags.require(FeatureFlag.STORY_SYSTEM)
    existing = getattr(state, "story_generation_service", None)
    if existing is not None:
        return existing
    root = Path(state.project_root_dir) / "data" / "stories" / ".generation"
    repository = StoryGenerationRepository(flags, root)
    service = StoryGenerationService(
        flags,
        repository,
        ConfigStoryAuthorModel(flags, state.config_manager),
    )
    state.story_generation_service = service
    return service


def run_story_generation_background(
    state: Any,
    bridge_task_id: str,
    generation_task_id: str,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    from application.runtime.tasks import (
        TaskCancelled,
        _is_task_cancel_requested,
        _update_task,
    )

    service = story_generation_service_for_state(state)

    def progress(update: Mapping[str, Any]) -> None:
        _update_task(state, bridge_task_id, **dict(update))

    try:
        from application.story.generation_recovery import recovery_for

        result = recovery_for(service).wait(
            generation_task_id,
            resume=resume,
            is_cancelled=lambda: _is_task_cancel_requested(state, bridge_task_id),
            on_progress=progress,
        )
        progress({"generationTask": result})
        return result
    except StoryGenerationCancelled as error:
        progress({"generationTask": service.get(generation_task_id)})
        raise TaskCancelled() from error
    except Exception:
        progress({"generationTask": service.get(generation_task_id)})
        raise


def _stage_schema(stage: StoryGenerationStage) -> Mapping[str, Any]:
    schemas: dict[StoryGenerationStage, Mapping[str, Any]] = {
        StoryGenerationStage.FOUNDATION: {
            "id": "stable kebab-case story id",
            "title": "string",
            "language": "BCP-47 string",
            "estimatedMinutes": "positive integer",
            "assumptions": "string[]",
            "premise": "string",
            "themes": "string[]",
            "worldRules": "string[]",
            "immutableFacts": "string[]",
            "secrets": (
                "string[]; disclose each secret only in the instruction of the node "
                "where it becomes knowable"
            ),
        },
        StoryGenerationStage.CHARACTERS: {
            "characters": (
                "story-wide CharacterDraft[] with id, name, responsibility, roles, "
                "tags, source; this is an available character list, not a scene cast"
            ),
        },
        StoryGenerationStage.NARRATIVE: {
            "startNodeId": "node id",
            "nodes": (
                "SimpleStoryNode[] using only limited_turn_node, free_chat_node, or "
                "ending_node. Interactive nodes contain instruction and natural-language "
                "transitions [{to, when}]. limited_turn_node also contains maxRounds and "
                "may contain defaultTo. Do not generate choices, freeformIntents, "
                "castPolicy, or per-node character lists. When resourceCatalog.backgrounds "
                "is supplied, treat it as optional setting inspiration; background is an optional location hint, not a media command."
            ),
        },
    }
    return schemas[stage]


def _validate_foundation(value: dict[str, Any]) -> None:
    _safe_id(value.get("id"), "foundation.id")
    _required_text(value.get("title"), "foundation.title", 200)
    assumptions = value.get("assumptions", [])
    if not isinstance(assumptions, list) or any(
        not isinstance(item, str) for item in assumptions
    ):
        raise StoryGenerationError(
            "generation.foundation_invalid", "assumptions must be a string array"
        )
    _required_text(value.get("premise"), "foundation.premise", 10_000)
    for key in ("themes", "worldRules", "immutableFacts", "secrets"):
        items = value.get(key, [])
        if not isinstance(items, list) or any(
            not isinstance(item, str) for item in items
        ):
            raise StoryGenerationError(
                "generation.foundation_invalid",
                f"foundation.{key} must be a string array",
            )


def _validate_characters(value: dict[str, Any]) -> None:
    forbidden = [field for field in ("initialCast", "defaults") if field in value]
    if forbidden:
        raise StoryGenerationError(
            "generation.characters_invalid",
            f"characters stage only accepts the story-wide list; remove {', '.join(forbidden)}",
        )
    characters = value.get("characters")
    if not isinstance(characters, list) or not characters or len(characters) > 128:
        raise StoryGenerationError(
            "generation.characters_invalid", "characters must contain 1..128 drafts"
        )
    ids: set[str] = set()
    for index, character in enumerate(characters):
        if not isinstance(character, dict):
            raise StoryGenerationError(
                "generation.characters_invalid", f"character {index} must be an object"
            )
        character_id = _safe_id(character.get("id"), f"characters[{index}].id")
        if character_id in ids:
            raise StoryGenerationError(
                "generation.characters_invalid", f"duplicate character {character_id!r}"
            )
        ids.add(character_id)
        _required_text(
            character.get("responsibility"), "character responsibility", 2_000
        )
        source = character.get("source")
        if not isinstance(source, Mapping):
            character["source"] = {
                "type": "author-generated",
                "path": f"characters/{character_id}.yaml",
            }
            continue
        source_type = str(source.get("type") or "").strip()
        if source_type == "author-generated":
            path = str(source.get("path") or "").strip()
            if not path:
                character["source"] = {
                    **dict(source),
                    "type": "author-generated",
                    "path": f"characters/{character_id}.yaml",
                }
            continue
        if (
            source_type in {"embedded", "user-imported"}
            and not str(source.get("path") or "").strip()
        ):
            raise StoryGenerationError(
                "generation.characters_invalid",
                f"character {character_id!r} is missing a source path",
            )


def _validate_narrative(
    value: dict[str, Any], *, backgrounds: tuple[str, ...] = ()
) -> None:
    start = _safe_id(value.get("startNodeId"), "narrative.startNodeId")
    nodes = value.get("nodes")
    if not isinstance(nodes, list) or not nodes or len(nodes) > 100:
        raise StoryGenerationError(
            "generation.narrative_invalid", "narrative nodes must contain 1..100 nodes"
        )
    ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise StoryGenerationError(
                "generation.narrative_invalid", f"node {index} must be an object"
            )
        node_id = _safe_id(node.get("id"), f"nodes[{index}].id")
        if node_id in ids:
            raise StoryGenerationError(
                "generation.narrative_invalid", f"duplicate node {node_id!r}"
            )
        ids.add(node_id)
        node_type = str(node.get("type") or "")
        if node_type not in {
            "limited_turn_node",
            "free_chat_node",
            "ending_node",
        }:
            raise StoryGenerationError(
                "generation.narrative_invalid",
                f"node {node_id!r} has an unsupported type",
            )
        forbidden = [
            field
            for field in (
                "choices",
                "freeformIntents",
                "castPolicy",
                "characters",
            )
            if field in node
        ]
        if forbidden:
            raise StoryGenerationError(
                "generation.narrative_invalid",
                f"simple node {node_id!r} cannot contain {', '.join(forbidden)}",
            )
        if node_type in {"limited_turn_node", "free_chat_node"}:
            _required_text(node.get("instruction"), f"nodes[{index}].instruction", 8000)
            transitions = node.get("transitions")
            if not isinstance(transitions, list):
                raise StoryGenerationError(
                    "generation.narrative_invalid",
                    f"node {node_id!r} transitions must be an array",
                )
            if node_type == "limited_turn_node":
                max_rounds = node.get("maxRounds")
                if (
                    isinstance(max_rounds, bool)
                    or not isinstance(max_rounds, int)
                    or max_rounds < 1
                ):
                    raise StoryGenerationError(
                        "generation.narrative_invalid",
                        f"node {node_id!r} needs a positive maxRounds",
                    )
                if not transitions:
                    raise StoryGenerationError(
                        "generation.narrative_invalid",
                        f"node {node_id!r} needs at least one transition",
                    )
            elif node.get("maxRounds") is not None:
                raise StoryGenerationError(
                    "generation.narrative_invalid",
                    f"free chat node {node_id!r} cannot define maxRounds",
                )
        if node_type == "ending_node" and (
            node.get("transitions") or node.get("defaultTo") is not None
        ):
            raise StoryGenerationError(
                "generation.narrative_invalid",
                f"ending node {node_id!r} cannot define transitions",
            )
    if start not in ids:
        raise StoryGenerationError(
            "generation.narrative_invalid",
            "startNodeId must reference a generated node",
        )
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        transitions = node.get("transitions", [])
        targets: set[str] = set()
        for transition_index, transition in enumerate(
            transitions if isinstance(transitions, list) else []
        ):
            if not isinstance(transition, dict):
                raise StoryGenerationError(
                    "generation.narrative_invalid",
                    f"nodes[{index}].transitions[{transition_index}] must be an object",
                )
            target = _safe_id(
                transition.get("to"),
                f"nodes[{index}].transitions[{transition_index}].to",
            )
            _required_text(
                transition.get("when"),
                f"nodes[{index}].transitions[{transition_index}].when",
                1000,
            )
            if target not in ids:
                raise StoryGenerationError(
                    "generation.narrative_invalid",
                    f"transition target {target!r} does not exist",
                )
            targets.add(target)
        default_to = node.get("defaultTo")
        if default_to is not None and default_to not in targets:
            raise StoryGenerationError(
                "generation.narrative_invalid",
                f"nodes[{index}].defaultTo must reference one of its transitions",
            )


def _background_ids(value: Any) -> tuple[str, ...]:
    catalog = value if isinstance(value, Mapping) else {}
    raw_backgrounds = catalog.get("backgrounds", ())
    if not isinstance(raw_backgrounds, Sequence) or isinstance(
        raw_backgrounds, (str, bytes, bytearray)
    ):
        return ()
    result: list[str] = []
    for item in raw_backgrounds:
        if isinstance(item, Mapping):
            identifier = item.get("id") or item.get("name")
        else:
            identifier = item
        text = str(identifier or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _secret_isolation_issues(
    source: Mapping[str, Any], foundation: Mapping[str, Any]
) -> list[GenerationValidationIssue]:
    secrets = {
        item.strip()
        for item in foundation.get("secrets", [])
        if isinstance(item, str) and len(item.strip()) >= 4
    }
    if not secrets:
        return []
    issues: list[GenerationValidationIssue] = []
    nodes = source.get("narrativeGraph", {}).get("nodes", [])
    for index, node in enumerate(nodes if isinstance(nodes, list) else []):
        if not isinstance(node, Mapping):
            continue
        # A simple node's instruction is its disclosure boundary: it is sent to
        # the scene model only after that node is entered. Legacy exposedContext
        # remains public throughout its scene and still needs leak detection.
        if str(node.get("type") or "") in {
            "limited_turn_node",
            "free_chat_node",
            "ending_node",
        }:
            continue
        visible_fields = (
            ("title", node.get("title", "")),
            ("exposedContext", node.get("exposedContext", {})),
        )
        for field_name, value in visible_fields:
            rendered = value if isinstance(value, str) else canonical_json(value)
            for secret in secrets:
                if secret in rendered:
                    issues.append(
                        GenerationValidationIssue(
                            "secret.exposed",
                            f"story bible secret leaked into {field_name}",
                            f"/narrativeGraph/nodes/{index}/{field_name}",
                        )
                    )
        choices = node.get("choices", [])
        for choice_index, choice in enumerate(
            choices if isinstance(choices, list) else []
        ):
            if not isinstance(choice, Mapping):
                continue
            label = str(choice.get("label") or "")
            for secret in secrets:
                if secret in label:
                    issues.append(
                        GenerationValidationIssue(
                            "secret.exposed",
                            "story bible secret leaked into choice label",
                            f"/narrativeGraph/nodes/{index}/choices/{choice_index}/label",
                        )
                    )
    return issues


def _updated_cost(
    current: Any, request: Mapping[str, Any], response: Mapping[str, Any]
) -> dict[str, int]:
    base = dict(current) if isinstance(current, Mapping) else {}
    input_chars = len(canonical_json(request))
    output_chars = len(canonical_json(response))
    usage = response.get("usage")
    explicit_tokens = 0
    if isinstance(usage, Mapping):
        for key in (
            "inputTokens",
            "outputTokens",
            "prompt_tokens",
            "completion_tokens",
        ):
            raw = usage.get(key)
            if isinstance(raw, int) and raw > 0:
                explicit_tokens += raw
    return {
        "requests": int(base.get("requests", 0)) + 1,
        "inputChars": int(base.get("inputChars", 0)) + input_chars,
        "outputChars": int(base.get("outputChars", 0)) + output_chars,
        "estimatedTokens": int(base.get("estimatedTokens", 0))
        + (explicit_tokens or (input_chars + output_chars + 3) // 4),
    }


def _adapter_text_content(response: Any) -> Any:
    if isinstance(response, (str, Mapping)):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if getattr(block, "type", None) == "text":
                texts.append(getattr(block, "text", "") or "")
            elif isinstance(block, Mapping) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
        if texts:
            return "".join(texts)
    choices = getattr(response, "choices", None)
    if choices:
        return getattr(choices[0].message, "content", None) or ""
    return response


def _parse_json_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "content"):
        value = value.content
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        value = "".join(str(getattr(item, "text", item)) for item in value)
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise StoryGenerationError(
            "generation.model_json_invalid",
            f"story author returned invalid JSON: {error}",
            rejected_output=text,
        ) from error
    if not isinstance(parsed, Mapping):
        raise StoryGenerationError(
            "generation.model_json_invalid",
            "story author must return a JSON object",
            rejected_output=text,
        )
    return parsed


def _resolve_pointer_parent(root: Any, tokens: list[str]) -> tuple[Any, str]:
    if not tokens:
        raise StoryGenerationError("generation.patch_invalid", "patch path is empty")
    current = root
    for token in tokens[:-1]:
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list):
            current = current[_list_position(token, len(current), allow_end=False)]
        else:
            raise StoryGenerationError(
                "generation.patch_path_missing", "patch parent path does not exist"
            )
    return current, tokens[-1]


def _list_position(value: str, length: int, *, allow_end: bool) -> int:
    if value == "-" and allow_end:
        return length
    if not value.isdigit():
        raise StoryGenerationError(
            "generation.patch_path_invalid", f"invalid array index {value!r}"
        )
    position = int(value)
    maximum = length if allow_end else length - 1
    if position < 0 or position > maximum:
        raise StoryGenerationError(
            "generation.patch_path_invalid", f"array index {position} is out of range"
        )
    return position


def _decode_pointer(value: str) -> str:
    if re.search(r"~(?![01])", value):
        raise StoryGenerationError(
            "generation.patch_path_invalid", "invalid JSON pointer escape"
        )
    return value.replace("~1", "/").replace("~0", "~")


def _safe_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", text):
        raise StoryGenerationError(
            "generation.invalid_id", f"{label} must be a stable safe identifier"
        )
    return text


def _required_text(value: Any, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise StoryGenerationError(
            "generation.invalid_text", f"{label} must contain 1..{maximum} characters"
        )
    return text


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _now_ms() -> int:
    return int(time.time() * 1_000)
