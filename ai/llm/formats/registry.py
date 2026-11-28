"""Auto-discovery and registration of built-in LLM dialog output formats."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from types import ModuleType
from typing import TypeVar

from core.messaging.formats.registry import (
    register_dialog_format,
    set_builtin_dialog_formats_registrar,
)
from sdk.adapters.dialog_format import DialogOutputFormat

F = TypeVar("F", bound=DialogOutputFormat)

_BUILTIN_FORMAT_ATTR = "__shinsekai_builtin_dialog_format__"
_SKIP_MODULES = frozenset({"prompt_support", "registry"})


def builtin_dialog_format(*, order: int | None = None) -> Callable[[type[F]], type[F]]:
    """Mark a `DialogOutputFormat` subclass for package auto-discovery without side effects."""

    def _decorator(cls: type[F]) -> type[F]:
        if order is not None:
            cls.order = int(order)
        setattr(cls, _BUILTIN_FORMAT_ATTR, True)
        return cls

    return _decorator


def _iter_package_modules(pkg: ModuleType, *, skip_root: bool = False) -> list[ModuleType]:
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        raise ValueError(f"{getattr(pkg, '__name__', pkg)!r} is not a Python package")
    modules: list[ModuleType] = []
    for mod_info in sorted(pkgutil.iter_modules(pkg_path), key=lambda item: item.name):
        if mod_info.name.startswith("_"):
            continue
        if skip_root and mod_info.name in _SKIP_MODULES:
            continue
        module = importlib.import_module(f"{pkg.__name__}.{mod_info.name}")
        modules.append(module)
        if mod_info.ispkg:
            modules.extend(_iter_package_modules(module, skip_root=False))
    return modules


def discover_builtin_dialog_formats(
    package: ModuleType | str = "ai.llm.formats",
) -> tuple[type[DialogOutputFormat], ...]:
    """Discover `@builtin_dialog_format` subclasses inside `package` sorted by `(order, format_id)`."""
    pkg = importlib.import_module(package) if isinstance(package, str) else package
    modules = _iter_package_modules(pkg, skip_root=True)
    seen_objects: set[int] = set()
    seen_ids: dict[str, type[DialogOutputFormat]] = {}

    for module in modules:
        for obj in list(vars(module).values()):
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            obj_id = id(obj)
            if obj_id in seen_objects:
                continue
            seen_objects.add(obj_id)
            obj_dict = getattr(obj, "__dict__", None)
            if obj_dict is None or not obj_dict.get(_BUILTIN_FORMAT_ATTR):
                continue
            if not isinstance(obj, type) or not issubclass(obj, DialogOutputFormat):
                raise TypeError(
                    f"@builtin_dialog_format requires a DialogOutputFormat subclass, got {obj!r}"
                )
            format_id = str(getattr(obj, "format_id", "") or "").strip().lower()
            if not format_id:
                raise ValueError(
                    f"Built-in dialog format {module.__name__}.{obj.__qualname__} has empty format_id"
                )
            existing = seen_ids.get(format_id)
            if existing is not None and existing is not obj:
                raise ValueError(
                    f"Duplicate built-in dialog format id {format_id!r}: "
                    f"{existing.__module__}.{existing.__qualname__} and "
                    f"{module.__name__}.{obj.__qualname__}"
                )
            seen_ids[format_id] = obj

    discovered = sorted(
        seen_ids.values(),
        key=lambda cls: (int(getattr(cls, "order", 100)), str(cls.format_id).strip().lower()),
    )
    return tuple(discovered)


def configure_builtin_dialog_formats() -> None:
    """Discover and register all built-in dialog formats idempotently."""
    set_builtin_dialog_formats_registrar(configure_builtin_dialog_formats)
    for fmt_cls in discover_builtin_dialog_formats("ai.llm.formats"):
        register_dialog_format(fmt_cls(), builtin=True, replace_existing=False)


set_builtin_dialog_formats_registrar(configure_builtin_dialog_formats)


__all__ = [
    "builtin_dialog_format",
    "configure_builtin_dialog_formats",
    "discover_builtin_dialog_formats",
]
