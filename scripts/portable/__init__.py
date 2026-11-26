"""Cross-platform portable bundle assembly and artifact publishing helpers."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from scripts.portable.targets import (
    DEFAULT_LLAMA_CPP_TAG,
    DEFAULT_MODELS,
    PLATFORM_TARGETS,
    SUPPORTED_MODELS,
    SUPPORTED_TARGETS,
    PlatformTarget,
    default_bundle_dirname,
    default_models_for_target,
    infer_host_target,
    resolve_target,
)

if TYPE_CHECKING:
    from scripts.portable.assembler import BundleReport, build_portable_bundle, read_version
    from scripts.portable.audit import audit_portable_bundle

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "BundleReport": ("scripts.portable.assembler", "BundleReport"),
    "build_portable_bundle": ("scripts.portable.assembler", "build_portable_bundle"),
    "read_version": ("scripts.portable.assembler", "read_version"),
    "audit_portable_bundle": ("scripts.portable.audit", "audit_portable_bundle"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(importlib.import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "BundleReport",
    "DEFAULT_LLAMA_CPP_TAG",
    "DEFAULT_MODELS",
    "PLATFORM_TARGETS",
    "PlatformTarget",
    "SUPPORTED_MODELS",
    "SUPPORTED_TARGETS",
    "audit_portable_bundle",
    "build_portable_bundle",
    "default_bundle_dirname",
    "default_models_for_target",
    "infer_host_target",
    "read_version",
    "resolve_target",
]
