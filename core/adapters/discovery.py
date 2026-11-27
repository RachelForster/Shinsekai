"""Side-effect-free ``@builtin_adapter`` decorator and package auto-discovery."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
import importlib
import pkgutil
from types import MappingProxyType, ModuleType
from typing import Any, TypeVar

from core.adapters.registry import AdapterRegistry

F = TypeVar("F")

_BUILTIN_SPECS_ATTR = "__shinsekai_builtin_adapters__"


def _freeze_default_kwargs(values: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not values:
        return MappingProxyType({})
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class BuiltinAdapterSpec:
    """Metadata attached directly to a self-declaring built-in adapter."""

    key: str
    label: str = ""
    order: int = 100
    default_kwargs: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    factory: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if not str(self.key or "").strip():
            raise ValueError("Built-in adapter key cannot be empty")
        if self.factory is not None and not callable(self.factory):
            raise TypeError(f"factory for {self.key!r} must be callable")
        object.__setattr__(
            self, "default_kwargs", _freeze_default_kwargs(self.default_kwargs)
        )


def builtin_adapter(
    key: str,
    *,
    label: str = "",
    order: int = 100,
    default_kwargs: Mapping[str, Any] | None = None,
    factory: Callable[..., Any] | None = None,
) -> Callable[[F], F]:
    """Attach built-in adapter registration metadata without touching any global state."""
    clean_key = str(key or "").strip()
    if not clean_key:
        raise ValueError("Built-in adapter key cannot be empty")
    spec = BuiltinAdapterSpec(
        key=clean_key,
        label=str(label or "").strip(),
        order=int(order),
        default_kwargs=_freeze_default_kwargs(default_kwargs),
        factory=factory,
    )

    def _decorator(target: F) -> F:
        target_dict = getattr(target, "__dict__", None)
        existing: tuple[BuiltinAdapterSpec, ...] = ()
        if target_dict is not None:
            existing = tuple(target_dict.get(_BUILTIN_SPECS_ATTR, ()))
        # Prepend so stacked decorators register in top-to-bottom source order.
        setattr(target, _BUILTIN_SPECS_ATTR, (spec, *existing))
        return target

    return _decorator


def get_builtin_adapter_specs(target: Any) -> tuple[BuiltinAdapterSpec, ...]:
    """Return specs declared directly on ``target`` (never inherited from subclasses)."""
    target_dict = getattr(target, "__dict__", None)
    if target_dict is None:
        return ()
    return tuple(target_dict.get(_BUILTIN_SPECS_ATTR, ()))


def discover_builtin_adapters(
    package: ModuleType | str,
    registry: AdapterRegistry[Any],
    *,
    skip_modules: Collection[str] = (),
) -> int:
    """Import adapter submodules in ``package`` and register ``@builtin_adapter`` classes."""
    pkg = importlib.import_module(package) if isinstance(package, str) else package
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        raise ValueError(f"{getattr(pkg, '__name__', pkg)!r} is not a Python package")

    skipped = set(skip_modules)
    seen_objects: set[int] = set()
    seen_keys: dict[str, str] = {}
    registered_count = 0

    for mod_info in sorted(pkgutil.iter_modules(pkg_path), key=lambda item: item.name):
        if mod_info.name.startswith("_") or mod_info.name in skipped:
            continue
        module_name = f"{pkg.__name__}.{mod_info.name}"
        module = importlib.import_module(module_name)

        for obj in list(vars(module).values()):
            obj_id = id(obj)
            if obj_id in seen_objects:
                continue
            seen_objects.add(obj_id)

            if getattr(obj, "__module__", None) != module.__name__:
                continue
            specs = get_builtin_adapter_specs(obj)
            if not specs:
                continue

            owner = f"{module.__name__}.{getattr(obj, '__qualname__', repr(obj))}"
            for spec in specs:
                norm_key = registry.normalize_key(spec.key)
                if not norm_key:
                    raise ValueError(
                        f"Empty normalized key for built-in adapter {spec.key!r} on {owner}"
                    )
                if norm_key in seen_keys:
                    raise ValueError(
                        f"Duplicate built-in {registry.domain} adapter key {spec.key!r}: "
                        f"{seen_keys[norm_key]} and {owner}"
                    )
                seen_keys[norm_key] = owner
                registry.register_builtin(
                    spec.key,
                    obj,
                    factory=spec.factory,
                    label=spec.label,
                    order=spec.order,
                    default_kwargs=spec.default_kwargs,
                )
                registered_count += 1

        hook = vars(module).get("register_builtin_adapters")
        if callable(hook) and getattr(hook, "__module__", None) == module.__name__:
            hook(registry)

    return registered_count


__all__ = [
    "BuiltinAdapterSpec",
    "builtin_adapter",
    "discover_builtin_adapters",
    "get_builtin_adapter_specs",
]
