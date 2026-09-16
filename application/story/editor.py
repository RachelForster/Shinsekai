"""Reviewable graph revisions. Reading and proposing never alter a playable story."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

from application.story.generation import (
    MAX_ARTIFACT_BYTES,
    StoryDraftValidator,
    StoryGenerationStage,
    StoryGenerationError,
    _stage_schema,
    _validate_narrative,
    story_generation_service_for_state,
)
from application.story.library import _read_project, supports_graph_editing
from application.story.project_loader import StoryProjectLoader
from application.story.selection import generation_selection
from sdk.path_utils import safe_child_path, safe_existing_file_path


def _hash(source: dict) -> str:
    encoded = json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authoring_brief(source: dict) -> str:
    metadata = source.get("metadata", {})
    return str(
        metadata.get("authoringBrief")
        or metadata.get("resourceBindings", {}).get("scenario")
        or ""
    )


def _validate_graph(graph: dict) -> None:
    try:
        _validate_narrative(graph)
    except StoryGenerationError as error:
        raise ValueError(f"节点图校验未通过：{error}") from error


def _load(state: Any, story_path: str) -> tuple[Path, dict]:
    path, project, _ = _read_project(state, story_path)
    if not supports_graph_editing(project):
        raise ValueError("此旧版剧本暂不支持节点编辑，仍可正常游玩。")
    if path.is_dir():
        path = path / "manifest.yaml"
    source = StoryProjectLoader().load_source(path)
    # The visual editor supports the simple node format. Never flatten legacy
    # choice/logic nodes into simple nodes and silently lose their behavior.
    graph = source.get("narrativeGraph", {})
    graph.setdefault("startNodeId", source.get("startNodeId"))
    _validate_graph(graph)
    return path, source


def _document(path: Path, source: dict) -> dict:
    return {
        "storyPath": path.as_posix(),
        "title": source["title"],
        "version": source["version"],
        "sourceHash": _hash(source),
        "graph": deepcopy(source["narrativeGraph"]),
        "authoringBrief": _authoring_brief(source),
    }


def read_story_document(state: Any, story_path: str) -> dict:
    return _document(*_load(state, story_path))


def _draft(state: Any, request: dict) -> tuple[Path, dict]:
    path, source = _load(state, str(request.get("storyPath") or ""))
    if request.get("sourceHash") != _hash(source):
        raise ValueError("剧本源文件已变化，请重新打开编辑器后再修改。")
    title = request.get("title")
    graph = request.get("graph")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("剧本名称需为 1–200 个字符。")
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    if len(json.dumps(graph, ensure_ascii=False).encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("节点图过大，请减少内容后重试。")
    source["title"] = title.strip()
    source["narrativeGraph"] = deepcopy(graph)
    source["startNodeId"] = graph.get("startNodeId")
    return path, source


def _validate(source: dict) -> dict:
    _validate_graph(source["narrativeGraph"])
    for node in source["narrativeGraph"]["nodes"]:
        if (
            not isinstance(node.get("title"), str)
            or not node["title"].strip()
            or len(node["title"]) > 200
        ):
            raise ValueError(f"节点 {node['id']} 需要 1–200 个字符的标题。")
    report = StoryDraftValidator().validate(source)
    if not report.valid:
        raise ValueError(
            "剧本校验未通过：\n" + "\n".join(issue.message for issue in report.issues)
        )
    return report.to_payload()


def _durable_rename(temporary: Path, destination: Path) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        # MOVEFILE_WRITE_THROUGH: finish persisting the rename before publishing
        # a manifest that references it. All targets are new, unique siblings.
        if not move(str(temporary), str(destination), 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _publish_bytes(destination: Path, data: bytes) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _durable_rename(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def save_story_document(state: Any, request: dict) -> dict:
    path, source = _draft(state, request)
    source["version"] += 1
    # Relative resources remain relative to the same directory. A new path and
    # version keep all existing conversations and saved progress on their source.
    destination = path.with_name(f"edited-{uuid.uuid4().hex}.json")
    profiles = []
    for index, character in enumerate(source.get("cast", {}).get("characters", [])):
        binding = character.get("source", {})
        if binding.get("type") != "author-generated":
            continue
        # Regenerating the original project replaces its characters directory.
        # Keep the generated profiles used by this saved version independent.
        original = safe_existing_file_path(
            safe_child_path(path.parent, binding["path"]),
            roots=(path.parent,), field="generated character",
        )
        target = path.with_name(f"{destination.stem}-character-{index}{original.suffix}")
        profiles.append((target, original.read_bytes()))
        binding["path"] = target.name
    _validate(source)
    encoded = json.dumps(source, ensure_ascii=False, indent=2) + "\n"
    # Check the base again after validation, which can be expensive.
    if _hash(_load(state, str(path))[1]) != request.get("sourceHash"):
        raise ValueError("剧本源文件已变化，请重新打开编辑器后再修改。")
    created_profiles = []
    try:
        for target, data in profiles:
            created_profiles.append(target)
            _publish_bytes(target, data)
        # The manifest is the commit point. Every referenced copy is durable
        # before this becomes visible; a crash earlier leaves only orphan copies.
        _publish_bytes(destination, encoded.encode("utf-8"))
    except Exception:
        # A rename may succeed before directory synchronization reports failure.
        # Never remove dependencies of a manifest that is already visible.
        if not destination.exists():
            for target in created_profiles:
                target.unlink(missing_ok=True)
        raise
    return _document(destination, source)


def suggest_story_graph(state: Any, request: dict) -> dict:
    _, source = _draft(state, request)
    instructions = request.get("instructions")
    if (
        not isinstance(instructions, str)
        or not instructions.strip()
        or len(instructions) > 20_000
    ):
        raise ValueError("请填写 1–20000 个字符的修改要求。")
    scope = request.get("scope")
    if scope not in {"node", "graph"}:
        raise ValueError("scope must be node or graph")
    graph = source["narrativeGraph"]
    if (
        not isinstance(graph.get("nodes"), list)
        or not 1 <= len(graph["nodes"]) <= 100
        or any(not isinstance(node, dict) for node in graph["nodes"])
    ):
        raise ValueError("节点图需包含 1–100 个节点。")
    node_id = request.get("nodeId")
    if scope == "node" and not any(node.get("id") == node_id for node in graph["nodes"]):
        raise ValueError("请选择要修改的节点。")
    metadata = source.get("metadata", {})
    bindings = metadata.get("resourceBindings", {})
    catalog = {
        "characters": source.get("cast", {}).get("characters", []),
        "backgrounds": metadata.get("backgrounds", []),
    }
    if bindings.get("characters"):
        _, catalog = generation_selection(
            state,
            {**bindings, "backgroundName": bindings.get("openingBackground", "")},
        )
    response_schema = {
        "summary": "brief explanation in the language of editInstructions",
        "nodeFormat": _stage_schema(StoryGenerationStage.NARRATIVE)["nodes"],
    }
    if scope == "node":
        response_schema["node"] = "one complete SimpleStoryNode with the same selected id"
    else:
        response_schema["graph"] = _stage_schema(StoryGenerationStage.NARRATIVE)
    model_request = {
        "protocol": "shinsekai.story-editor.v1",
        "operation": "revise-node" if scope == "node" else "revise-graph",
        "scope": scope,
        "nodeId": node_id if scope == "node" else None,
        "editInstructions": instructions.strip(),
        "synopsis": _authoring_brief(source),
        "title": source["title"],
        "graph": deepcopy(graph),
        "resourceCatalog": catalog,
        "constraints": {
            "maxNodes": 100,
            "preserveExistingIds": True,
            "selectedNodeOnly": scope == "node",
            "allowAddRemoveAndReconnectNodes": scope == "graph",
            "preserveStoryWideCharacterPool": True,
            "doNotOverrideChatTemplateOrOutputFormat": True,
            "allNodesAndEndingsMustBeReachable": True,
            "defaultToMustBeATransitionTarget": True,
            "discloseSecretsOnlyWhenCurrentNodeMakesThemKnowable": True,
        },
        "responseSchema": response_schema,
    }
    response = story_generation_service_for_state(state).model.complete(model_request)
    if not isinstance(response, Mapping):
        raise ValueError("LLM 返回的修改格式无效。")
    response = dict(response)
    if len(json.dumps(response).encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("LLM 返回的修改格式无效。")
    if scope == "node":
        node = response.get("node")
        if not isinstance(node, dict) or node.get("id") != node_id:
            raise ValueError("LLM 修改了节点标识，请重新生成。")
        graph["nodes"] = [
            deepcopy(node) if item.get("id") == node_id else item
            for item in graph["nodes"]
        ]
    else:
        graph = response.get("graph")
        if not isinstance(graph, dict):
            raise ValueError("LLM 未返回完整节点图。")
    source["narrativeGraph"] = graph
    source["startNodeId"] = graph.get("startNodeId")
    validation = _validate(source)
    return {
        "graph": graph,
        "summary": str(response.get("summary") or "")[:4000],
        "validation": validation,
    }
