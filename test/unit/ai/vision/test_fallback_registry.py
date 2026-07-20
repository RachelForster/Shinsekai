from __future__ import annotations

import pytest

from ai.vision import fallback_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    fallback_registry.clear_preferred_fallback()
    yield
    fallback_registry.clear_preferred_fallback()


def test_set_then_active_returns_registration():
    manager = object()
    fallback_registry.set_preferred_fallback("plugin.a", lambda: manager, lambda: True)

    pref = fallback_registry.active_preferred_fallback()

    assert pref is not None
    assert pref.label == "plugin.a"
    assert pref.factory() is manager


def test_unavailable_registration_is_hidden():
    fallback_registry.set_preferred_fallback("plugin.a", lambda: object(), lambda: False)

    assert fallback_registry.active_preferred_fallback() is None


def test_availability_probe_error_is_swallowed():
    def boom() -> bool:
        raise RuntimeError("probe failed")

    fallback_registry.set_preferred_fallback("plugin.a", lambda: object(), boom)

    assert fallback_registry.active_preferred_fallback() is None


def test_set_replaces_existing_registration():
    fallback_registry.set_preferred_fallback("plugin.a", lambda: "a", lambda: True)
    fallback_registry.set_preferred_fallback("plugin.b", lambda: "b", lambda: True)

    pref = fallback_registry.active_preferred_fallback()
    assert pref is not None
    assert pref.label == "plugin.b"


def test_clear_with_non_matching_label_is_noop():
    fallback_registry.set_preferred_fallback("plugin.a", lambda: object(), lambda: True)

    fallback_registry.clear_preferred_fallback("plugin.other")
    assert fallback_registry.active_preferred_fallback() is not None

    fallback_registry.clear_preferred_fallback("plugin.a")
    assert fallback_registry.active_preferred_fallback() is None


def test_clear_without_label_clears_any():
    fallback_registry.set_preferred_fallback("plugin.a", lambda: object(), lambda: True)
    fallback_registry.clear_preferred_fallback()
    assert fallback_registry.active_preferred_fallback() is None


def test_empty_label_is_rejected():
    with pytest.raises(ValueError):
        fallback_registry.set_preferred_fallback("   ", lambda: object(), lambda: True)


def test_non_callable_is_rejected():
    with pytest.raises(TypeError):
        fallback_registry.set_preferred_fallback("plugin.a", object(), lambda: True)
