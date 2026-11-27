"""Unit tests for the generic thread-safe AdapterRegistry."""

from __future__ import annotations

import threading

import pytest

from core.adapters import AdapterRegistration, AdapterRegistry


class _BaseDummy:
    def __init__(self, required: str, optional: str = "default") -> None:
        self.required = required
        self.optional = optional


class _OtherDummy:
    def __init__(self, flag: bool = False) -> None:
        self.flag = flag


def test_isolated_registries_and_idempotent_builtins() -> None:
    calls = 0

    def register_builtins(reg: AdapterRegistry[_BaseDummy]) -> None:
        nonlocal calls
        calls += 1
        reg.register_builtin("alpha", _BaseDummy, label="Alpha", order=10)

    first = AdapterRegistry("Dummy", builtin_registrar=register_builtins)
    second = AdapterRegistry("Dummy")

    first.configure_builtins()
    first.configure_builtins()

    assert calls == 1
    assert "alpha" in first
    assert "alpha" not in second
    assert first.is_builtin("alpha") is True
    assert first.keys() == ("alpha",)


def test_configure_plugins_atomically_replaces_and_protects_builtins() -> None:
    reg = AdapterRegistry("Dummy", key_normalizer=lambda key: key.strip().lower())
    reg.register_builtin("alpha", _BaseDummy, label="Alpha", order=10)

    reg.configure_plugins(
        {
            "beta": _OtherDummy,
            "alpha": _OtherDummy,  # blocked unless allow_override_builtin=True
            "": _OtherDummy,
        }
    )
    assert reg.get("alpha") is _BaseDummy
    assert reg.get("BETA") is _OtherDummy
    assert reg.keys() == ("alpha", "beta")

    # Reloading plugins removes stale entries and allows explicit opt-in override.
    reg.configure_plugins(
        {
            "gamma": AdapterRegistration(key="gamma", adapter_cls=_OtherDummy, label="Gamma"),
            "alpha": _OtherDummy,
        },
        allow_override_builtin=True,
    )
    assert reg.get("beta") is None
    assert reg.get("alpha") is _OtherDummy
    assert reg.get("gamma") is _OtherDummy

    reg.clear_plugins()
    assert reg.get("gamma") is None
    assert reg.get("alpha") is _BaseDummy


def test_lazy_loader_caches_resolved_class_once() -> None:
    loads = 0

    def load_dummy() -> type[_BaseDummy]:
        nonlocal loads
        loads += 1
        return _BaseDummy

    reg = AdapterRegistry("Dummy")
    reg.register_builtin("lazy", loader=load_dummy, label="Lazy")

    assert "lazy" in reg
    assert loads == 0

    first = reg.get("lazy")
    second = reg.get("lazy")
    assert first is _BaseDummy
    assert second is _BaseDummy
    assert loads == 1


def test_create_merges_default_kwargs_filters_ctor_and_supports_custom_factory() -> None:
    reg = AdapterRegistry("Dummy")
    reg.register_builtin(
        "configured",
        _BaseDummy,
        default_kwargs={"required": "from-default", "optional": "preset"},
    )
    reg.register(
        "custom-factory",
        _OtherDummy,
        factory=lambda flag=False, **_extra: _OtherDummy(flag=not flag),
    )

    instance = reg.create("configured", optional="caller", unknown_extra=123)
    assert isinstance(instance, _BaseDummy)
    assert instance.required == "from-default"
    assert instance.optional == "caller"

    custom = reg.create("custom-factory", flag=False, unused="ignored")
    assert isinstance(custom, _OtherDummy)
    assert custom.flag is True

    with pytest.raises(ValueError, match="Unsupported Dummy adapter: 'missing'"):
        reg.create("missing")


def test_mutable_mapping_view_supports_legacy_mutations_and_monkeypatch(monkeypatch) -> None:
    reg = AdapterRegistry("Dummy", key_normalizer=lambda key: key.strip().lower())
    reg.register_builtin("builtin", _BaseDummy, label="Built-in")
    view = reg.as_mutable_mapping()

    assert "BUILTIN" in view
    assert view["builtin"] is _BaseDummy

    with monkeypatch.context() as mp:
        mp.setitem(view, "builtin", _OtherDummy)
        mp.setitem(view, "plugin-x", _OtherDummy)
        assert reg.get("builtin") is _OtherDummy
        assert reg.get("plugin-x") is _OtherDummy

    # Monkeypatch teardown restores built-in entry and deletes temporary plugin key.
    assert reg.get("builtin") is _BaseDummy
    assert "plugin-x" not in reg

    view["temp"] = _OtherDummy
    assert view.pop("temp") is _OtherDummy
    assert "temp" not in reg

    with pytest.raises(KeyError):
        del view["builtin"]


def test_concurrent_reads_and_plugin_updates_remain_consistent() -> None:
    reg = AdapterRegistry("Dummy", key_normalizer=lambda key: key.strip().lower())
    reg.register_builtin("core", _BaseDummy)
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for idx in range(50):
                reg.configure_plugins({f"plugin_{idx % 5}": _OtherDummy})
        except BaseException as exc:  # pragma: no cover - defensive check
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(100):
                keys = reg.keys()
                assert "core" in keys
                assert reg.get("core") is _BaseDummy
        except BaseException as exc:  # pragma: no cover - defensive check
            errors.append(exc)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
