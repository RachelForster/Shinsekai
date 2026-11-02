from __future__ import annotations

import pytest

from ai.vision import fallback_registry
from sdk.adapters import VisionFallbackContribution


@pytest.fixture(autouse=True)
def _clean_registry():
    fallback_registry.configure_registered_fallbacks([])
    yield
    fallback_registry.configure_registered_fallbacks([])


def _fallback(
    provider: str,
    result: object,
    *,
    available=True,
    priority: int = 100,
) -> VisionFallbackContribution:
    probe = available if callable(available) else lambda: bool(available)
    return VisionFallbackContribution(provider, lambda: result, probe, priority)


def test_configure_then_active_returns_registration():
    manager = object()
    fallback_registry.configure_registered_fallbacks([_fallback("plugin.a", manager)])

    preferred = fallback_registry.active_vision_fallback()

    assert preferred is not None
    assert preferred.provider == "plugin.a"
    assert preferred.factory() is manager


def test_unavailable_registration_falls_through_to_next_provider():
    fallback_registry.configure_registered_fallbacks(
        [
            _fallback("plugin.primary", object(), available=False, priority=10),
            _fallback("plugin.secondary", object(), priority=20),
        ]
    )

    preferred = fallback_registry.active_vision_fallback()

    assert preferred is not None
    assert preferred.provider == "plugin.secondary"


def test_availability_probe_error_is_swallowed_and_next_provider_is_used():
    def boom() -> bool:
        raise RuntimeError("probe failed")

    fallback_registry.configure_registered_fallbacks(
        [
            _fallback("plugin.broken", object(), available=boom, priority=10),
            _fallback("plugin.healthy", object(), priority=20),
        ]
    )

    preferred = fallback_registry.active_vision_fallback()

    assert preferred is not None
    assert preferred.provider == "plugin.healthy"


def test_lower_priority_value_wins_regardless_of_registration_order():
    fallback_registry.configure_registered_fallbacks(
        [
            _fallback("plugin.later", object(), priority=200),
            _fallback("plugin.preferred", object(), priority=5),
        ]
    )

    preferred = fallback_registry.active_vision_fallback()

    assert preferred is not None
    assert preferred.provider == "plugin.preferred"


def test_empty_configuration_clears_snapshot():
    fallback_registry.configure_registered_fallbacks([_fallback("plugin.a", object())])
    fallback_registry.configure_registered_fallbacks([])

    assert fallback_registry.active_vision_fallback() is None
