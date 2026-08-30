"""HTTP-facing adapters for effect management use cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from application.media.effects import (
    EffectExportResult,
    EffectOperation,
    EffectRequest,
    EffectUseCase,
    EffectUseCaseResult,
)
from application.runtime.state import BridgeState

from .tools import _local_file_access_roots


def parse_effect_request(
    operation: EffectOperation | str,
    body: Mapping[str, Any] | None = None,
    *,
    name: str = "",
) -> EffectRequest:
    """Convert transport values into the application request contract."""

    payload = dict(body or {})
    if name:
        payload["name"] = name
    return EffectRequest(operation=EffectOperation(operation), payload=payload)


def effect_use_case(
    state: BridgeState,
    *,
    additional_file_roots: Sequence[str] = (),
) -> EffectUseCase:
    """Compose the use case from bridge-owned runtime state."""

    roots = (*_local_file_access_roots(state), *additional_file_roots)
    project_root = str(getattr(state, "project_root_dir", "") or "").strip() or None
    return EffectUseCase(
        state.config_manager,
        local_file_access_roots=roots,
        project_root=project_root,
    )


def effect_response_payload(result: EffectUseCaseResult) -> Any:
    """Project application results onto the existing HTTP response shape."""

    if isinstance(result, EffectExportResult):
        return {
            "downloadUrl": f"/api/download?path={result.path}",
            "path": result.path,
        }
    return result
