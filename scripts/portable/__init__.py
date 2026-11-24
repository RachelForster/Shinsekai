"""Cross-platform portable bundle assembly and artifact publishing helpers."""

from __future__ import annotations

from scripts.portable.assembler import BundleReport, build_portable_bundle, read_version
from scripts.portable.audit import audit_portable_bundle
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
