"""Thread-safe adapter registry with built-in/plugin isolation and lazy loading."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
import logging
import threading
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from config.adapter_extra_kwargs import filter_kwargs_for_ctor

T = TypeVar("T")

logger = logging.getLogger(__name__)


def _default_key_normalizer(key: str) -> str:
    return str(key or "").strip()


def _freeze_kwargs(values: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not values:
        return MappingProxyType({})
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class AdapterRegistration(Generic[T]):
    """Immutable descriptor for a registered adapter backend or factory."""

    key: str
    adapter_cls: type[T] | Callable[..., T] | None = None
    loader: Callable[[], type[T] | Callable[..., T]] | None = None
    factory: Callable[..., T] | None = None
    label: str = ""
    order: int = 100
    source: str = "builtin"
    default_kwargs: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.adapter_cls is not None and not callable(self.adapter_cls):
            raise TypeError(f"adapter_cls for {self.key!r} must be callable")
        if self.loader is not None and not callable(self.loader):
            raise TypeError(f"loader for {self.key!r} must be callable")
        if self.factory is not None and not callable(self.factory):
            raise TypeError(f"factory for {self.key!r} must be callable")
        if self.adapter_cls is None and self.loader is None and self.factory is None:
            raise ValueError(
                f"AdapterRegistration({self.key!r}) requires adapter_cls, loader, or factory"
            )
        object.__setattr__(self, "default_kwargs", _freeze_kwargs(self.default_kwargs))

    def resolve_class(self) -> type[T] | Callable[..., T]:
        """Return the concrete adapter class or callable, loading lazily if needed."""
        if self.adapter_cls is not None:
            return self.adapter_cls
        if self.loader is not None:
            return self.loader()
        assert self.factory is not None
        return self.factory


class _RegistryMutableView(MutableMapping[str, Any]):
    """Live mapping facade keeping legacy ``_adapters`` dicts synced with a registry."""

    def __init__(self, registry: AdapterRegistry[Any]) -> None:
        self._registry = registry

    def __getitem__(self, key: str) -> Any:
        target = self._registry.get(key)
        if target is None:
            raise KeyError(key)
        return target

    def __setitem__(self, key: str, value: Any) -> None:
        self._registry._set_compat_entry(key, value)

    def __delitem__(self, key: str) -> None:
        if not self._registry._delete_compat_entry(key):
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._registry.keys())

    def __len__(self) -> int:
        return len(self._registry.keys())

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in self._registry


class AdapterRegistry(Generic[T]):
    """Thread-safe registry separating built-in adapters from plugin contributions."""

    def __init__(
        self,
        domain: str,
        *,
        key_normalizer: Callable[[str], str] | None = None,
        builtin_registrar: Callable[[AdapterRegistry[T]], None] | None = None,
    ) -> None:
        self.domain = str(domain or "adapter").strip() or "adapter"
        self._normalize_key = key_normalizer or _default_key_normalizer
        self._builtin_registrar = builtin_registrar
        self._lock = threading.RLock()
        self._builtin: dict[str, AdapterRegistration[T]] = {}
        self._plugin: dict[str, AdapterRegistration[T]] = {}
        self._compat_overrides: dict[str, AdapterRegistration[T]] = {}
        self._builtins_configured = False

    def _ensure_builtins(self) -> None:
        if self._builtins_configured:
            return
        with self._lock:
            if self._builtins_configured:
                return
            self._builtins_configured = True
            if self._builtin_registrar is not None:
                try:
                    self._builtin_registrar(self)
                except Exception:
                    self._builtins_configured = False
                    raise

    def configure_builtins(self) -> None:
        """Idempotently register all built-in entries for this domain."""
        self._ensure_builtins()

    def normalize_key(self, key: str) -> str:
        """Normalize ``key`` using this registry's canonical key normalizer."""
        return self._normalize_key(key)

    def _normalize_non_empty(self, key: str) -> str:
        norm = self._normalize_key(key)
        if not norm:
            raise ValueError(f"{self.domain} adapter key cannot be empty")
        return norm

    def register(
        self,
        key: str,
        adapter_cls: type[T] | Callable[..., T] | None = None,
        *,
        loader: Callable[[], type[T] | Callable[..., T]] | None = None,
        factory: Callable[..., T] | None = None,
        label: str = "",
        order: int = 100,
        default_kwargs: Mapping[str, Any] | None = None,
        builtin: bool = False,
        replace_existing: bool = True,
    ) -> AdapterRegistration[T]:
        """Register an adapter class, lazy loader, or factory function."""
        if not builtin:
            self._ensure_builtins()
        norm_key = self._normalize_non_empty(key)
        canonical_key = norm_key if builtin else str(key or "").strip() or norm_key
        registration = AdapterRegistration(
            key=canonical_key,
            adapter_cls=adapter_cls,
            loader=loader,
            factory=factory,
            label=str(label or "").strip(),
            order=int(order),
            source="builtin" if builtin else "plugin",
            default_kwargs=_freeze_kwargs(default_kwargs),
        )
        with self._lock:
            if builtin:
                if norm_key in self._builtin and not replace_existing:
                    return self._builtin[norm_key]
                self._builtin[norm_key] = registration
                self._compat_overrides.pop(norm_key, None)
                return registration
            if norm_key in self._builtin:
                if not replace_existing:
                    raise ValueError(
                        f"{self.domain} adapter {norm_key!r} conflicts with a built-in adapter"
                    )
                self._compat_overrides[norm_key] = replace(
                    registration,
                    key=self._builtin[norm_key].key,
                    source="override",
                )
                return self._compat_overrides[norm_key]
            if norm_key in self._plugin and not replace_existing:
                raise ValueError(f"Duplicate {self.domain} adapter: {norm_key!r}")
            self._plugin[norm_key] = registration
            return registration

    def register_builtin(
        self,
        key: str,
        adapter_cls: type[T] | Callable[..., T] | None = None,
        *,
        loader: Callable[[], type[T] | Callable[..., T]] | None = None,
        factory: Callable[..., T] | None = None,
        label: str = "",
        order: int = 100,
        default_kwargs: Mapping[str, Any] | None = None,
    ) -> AdapterRegistration[T]:
        """Register a built-in adapter entry (idempotent if already present)."""
        return self.register(
            key,
            adapter_cls,
            loader=loader,
            factory=factory,
            label=label,
            order=order,
            default_kwargs=default_kwargs,
            builtin=True,
            replace_existing=False,
        )

    def unregister(self, key: str, *, include_builtin: bool = False) -> bool:
        """Remove a plugin (or optionally built-in) registration."""
        self._ensure_builtins()
        norm_key = self._normalize_key(key)
        if not norm_key:
            return False
        with self._lock:
            removed = False
            if norm_key in self._compat_overrides:
                del self._compat_overrides[norm_key]
                removed = True
            if norm_key in self._plugin:
                del self._plugin[norm_key]
                removed = True
            if include_builtin and norm_key in self._builtin:
                del self._builtin[norm_key]
                removed = True
            return removed

    def configure_plugins(
        self,
        entries: Mapping[str, Any] | Iterable[AdapterRegistration[T]],
        *,
        allow_override_builtin: bool = False,
    ) -> None:
        """Atomically replace plugin registrations while keeping built-ins isolated."""
        self._ensure_builtins()
        prepared_plugins: dict[str, AdapterRegistration[T]] = {}
        prepared_overrides: dict[str, AdapterRegistration[T]] = {}

        if isinstance(entries, Mapping):
            raw_items: Iterable[tuple[str, Any]] = entries.items()
        else:
            raw_items = ((item.key, item) for item in entries)

        for raw_key, raw_value in raw_items:
            norm_key = self._normalize_key(raw_key)
            if not norm_key:
                logger.error("Invalid %s adapter key: %r", self.domain, raw_key)
                continue
            try:
                if isinstance(raw_value, AdapterRegistration):
                    entry = replace(
                        raw_value,
                        key=str(raw_value.key or "").strip() or norm_key,
                        source="plugin",
                    )
                else:
                    entry = AdapterRegistration(
                        key=str(raw_key or "").strip() or norm_key,
                        adapter_cls=raw_value,
                        source="plugin",
                    )
            except Exception:
                logger.exception(
                    "Invalid %s adapter registration for %r", self.domain, raw_key
                )
                continue

            with self._lock:
                builtin_entry = self._builtin.get(norm_key)
            if builtin_entry is not None:
                if not allow_override_builtin:
                    logger.error(
                        "%s plugin adapter %r conflicts with built-in adapter; skipping",
                        self.domain,
                        raw_key,
                    )
                    continue
                prepared_overrides[norm_key] = replace(
                    entry,
                    key=builtin_entry.key,
                    label=entry.label or builtin_entry.label,
                    order=builtin_entry.order,
                    source="override",
                )
            else:
                prepared_plugins[norm_key] = entry

        with self._lock:
            self._plugin.clear()
            self._plugin.update(prepared_plugins)
            self._compat_overrides.clear()
            self._compat_overrides.update(prepared_overrides)

    def clear_plugins(self) -> None:
        """Drop all plugin entries and temporary compatibility overrides."""
        with self._lock:
            self._plugin.clear()
            self._compat_overrides.clear()

    def reset_for_tests(self, *, restore_builtins: bool = True) -> None:
        """Test helper: reset registry state and optionally re-register built-ins."""
        with self._lock:
            self._builtin.clear()
            self._plugin.clear()
            self._compat_overrides.clear()
            self._builtins_configured = False
        if restore_builtins:
            self._ensure_builtins()

    def _set_compat_entry(self, key: str, value: Any) -> None:
        self._ensure_builtins()
        norm_key = self._normalize_non_empty(key)
        with self._lock:
            builtin_entry = self._builtin.get(norm_key)
            if builtin_entry is not None:
                try:
                    builtin_cls = self._resolve_and_cache(
                        self._builtin, norm_key, builtin_entry
                    )
                except Exception:
                    builtin_cls = builtin_entry.adapter_cls
                if value is builtin_cls:
                    self._compat_overrides.pop(norm_key, None)
                    return
                self._compat_overrides[norm_key] = AdapterRegistration(
                    key=builtin_entry.key,
                    adapter_cls=value,
                    label=builtin_entry.label,
                    order=builtin_entry.order,
                    source="override",
                    default_kwargs=builtin_entry.default_kwargs,
                )
                return
            self._plugin[norm_key] = AdapterRegistration(
                key=str(key or "").strip() or norm_key,
                adapter_cls=value,
                source="plugin",
            )

    def _delete_compat_entry(self, key: str) -> bool:
        self._ensure_builtins()
        norm_key = self._normalize_key(key)
        if not norm_key:
            return False
        with self._lock:
            if norm_key in self._compat_overrides:
                del self._compat_overrides[norm_key]
                return True
            if norm_key in self._plugin:
                del self._plugin[norm_key]
                return True
            return False

    def _resolve_and_cache(
        self,
        slot: dict[str, AdapterRegistration[T]],
        norm_key: str,
        registration: AdapterRegistration[T],
    ) -> type[T] | Callable[..., T]:
        if registration.adapter_cls is not None:
            return registration.adapter_cls
        resolved = registration.resolve_class()
        with self._lock:
            current = slot.get(norm_key)
            if current is registration and current.adapter_cls is None:
                slot[norm_key] = replace(registration, adapter_cls=resolved)
        return resolved

    def get_registration(self, key: str) -> AdapterRegistration[T] | None:
        """Look up a registration entry by key (after normalization)."""
        self._ensure_builtins()
        norm_key = self._normalize_key(key)
        if not norm_key:
            return None
        with self._lock:
            for slot in (self._compat_overrides, self._plugin, self._builtin):
                reg = slot.get(norm_key)
                if reg is not None:
                    target_slot = slot
                    break
            else:
                return None
        if reg.adapter_cls is None and reg.loader is not None:
            resolved = self._resolve_and_cache(target_slot, norm_key, reg)
            return replace(reg, adapter_cls=resolved)
        return reg

    def get(self, key: str) -> type[T] | Callable[..., T] | None:
        """Return the resolved adapter class or callable for ``key``, or ``None``."""
        reg = self.get_registration(key)
        if reg is None:
            return None
        return reg.resolve_class()

    def is_builtin(self, key: str) -> bool:
        """Return ``True`` when ``key`` corresponds to a built-in registration."""
        self._ensure_builtins()
        norm_key = self._normalize_key(key)
        if not norm_key:
            return False
        with self._lock:
            return norm_key in self._builtin

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        self._ensure_builtins()
        norm_key = self._normalize_key(key)
        if not norm_key:
            return False
        with self._lock:
            return (
                norm_key in self._compat_overrides
                or norm_key in self._plugin
                or norm_key in self._builtin
            )

    def entries(self) -> tuple[AdapterRegistration[T], ...]:
        """Return all registrations in deterministic UI/listing order."""
        self._ensure_builtins()
        with self._lock:
            builtins = [
                self._compat_overrides.get(norm_key, reg)
                for norm_key, reg in self._builtin.items()
            ]
            builtins.sort(key=lambda item: (item.order, item.key.lower()))
            plugins = sorted(
                self._plugin.values(),
                key=lambda item: (item.order, item.key.lower()),
            )
        return tuple([*builtins, *plugins])

    def keys(self) -> tuple[str, ...]:
        """Return canonical registered keys in deterministic order."""
        return tuple(entry.key for entry in self.entries())

    def snapshot(self) -> dict[str, type[T] | Callable[..., T]]:
        """Return a copy mapping canonical keys to resolved adapter classes."""
        return {entry.key: entry.resolve_class() for entry in self.entries()}

    def builtin_snapshot(self) -> dict[str, type[T] | Callable[..., T]]:
        """Return a copy mapping built-in keys to resolved adapter classes."""
        self._ensure_builtins()
        with self._lock:
            ordered = sorted(
                self._builtin.values(),
                key=lambda item: (item.order, item.key.lower()),
            )
        return {entry.key: entry.resolve_class() for entry in ordered}

    def create(
        self,
        key: str,
        *,
        filter_ctor_kwargs: bool = True,
        **kwargs: Any,
    ) -> T:
        """Construct an adapter instance for ``key`` with optional ctor filtering."""
        registration = self.get_registration(key)
        if registration is None:
            raise ValueError(
                f"Unsupported {self.domain} adapter: '{key}'. "
                f"Supported adapters are: {list(self.keys())}"
            )

        merged_kwargs: dict[str, Any] = dict(registration.default_kwargs)
        merged_kwargs.update(kwargs)

        try:
            if registration.factory is not None:
                return registration.factory(**merged_kwargs)
            target = registration.resolve_class()
            if isinstance(target, type) and filter_ctor_kwargs:
                ctor_kwargs = filter_kwargs_for_ctor(target, merged_kwargs)
                return target(**ctor_kwargs)
            return target(**merged_kwargs)
        except TypeError:
            logger.exception(
                "Error creating %s adapter %r; check constructor arguments",
                self.domain,
                key,
            )
            raise

    def as_mutable_mapping(self) -> MutableMapping[str, Any]:
        """Return a live mapping view for legacy ``Factory._adapters`` callers."""
        return _RegistryMutableView(self)
