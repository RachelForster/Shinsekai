"""Declarative registry for Python runtime dependency bundles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeDependencySpec:
    """Declarative specification for checking and installing a Python runtime bundle."""

    key: str
    package_specs: tuple[str, ...]
    pytorch_specs: tuple[str, ...] = ()
    pin_installed_torch: bool = False
    install_only_unsatisfied: bool = False
    install_spec_overrides: Mapping[str, str] = field(default_factory=dict)
    requires_target_python: bool = False
    target_python: str | Path | Callable[[Any], str | Path | None] | None = None
    default_label: str = ""
    secondary_group_label: str = ""
    success_message: str = ""

    def __post_init__(self) -> None:
        cleaned_key = str(self.key or "").strip()
        if not cleaned_key:
            raise ValueError("RuntimeDependencySpec.key is required")
        cleaned_specs = tuple(
            str(item).strip() for item in self.package_specs if str(item).strip()
        )
        if not cleaned_specs:
            raise ValueError("RuntimeDependencySpec.package_specs must not be empty")
        cleaned_torch = tuple(
            str(item).strip() for item in self.pytorch_specs if str(item).strip()
        )
        if (
            self.target_python is not None
            and not isinstance(self.target_python, (str, Path))
            and not callable(self.target_python)
        ):
            raise TypeError(
                "RuntimeDependencySpec.target_python must be a path or callable"
            )
        object.__setattr__(self, "key", cleaned_key)
        object.__setattr__(self, "package_specs", cleaned_specs)
        object.__setattr__(self, "pytorch_specs", cleaned_torch)
        object.__setattr__(
            self,
            "install_spec_overrides",
            dict(self.install_spec_overrides or {}),
        )


class RuntimeDependencyRegistry:
    """Thread-safe registry mapping runtime/module keys to ``RuntimeDependencySpec``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._builtins: dict[str, RuntimeDependencySpec] = {}
        self._custom: dict[str, RuntimeDependencySpec] = {}

    def register_builtin(self, spec: RuntimeDependencySpec) -> None:
        with self._lock:
            self._builtins[spec.key] = spec

    def register(self, spec: RuntimeDependencySpec) -> None:
        with self._lock:
            if spec.key in self._builtins:
                raise ValueError(
                    f"'{spec.key}' is a reserved built-in runtime dependency key"
                )
            self._custom[spec.key] = spec

    def unregister(self, key: str) -> bool:
        cleaned = str(key or "").strip()
        with self._lock:
            return self._custom.pop(cleaned, None) is not None

    def get(self, module_name: str) -> RuntimeDependencySpec | None:
        cleaned = str(module_name or "").strip()
        if not cleaned:
            return None
        top_level = cleaned.split(".", 1)[0]
        with self._lock:
            return (
                self._custom.get(cleaned)
                or self._builtins.get(cleaned)
                or self._custom.get(top_level)
                or self._builtins.get(top_level)
            )

    def list_specs(self) -> tuple[RuntimeDependencySpec, ...]:
        with self._lock:
            merged = {**self._custom, **self._builtins}
            return tuple(merged[key] for key in sorted(merged))


RUNTIME_DEPENDENCY_REGISTRY = RuntimeDependencyRegistry()


def register_runtime_dependency(spec: RuntimeDependencySpec) -> None:
    """Register an extension or plugin runtime dependency bundle."""
    RUNTIME_DEPENDENCY_REGISTRY.register(spec)


__all__ = [
    "RUNTIME_DEPENDENCY_REGISTRY",
    "RuntimeDependencyRegistry",
    "RuntimeDependencySpec",
    "register_runtime_dependency",
]
