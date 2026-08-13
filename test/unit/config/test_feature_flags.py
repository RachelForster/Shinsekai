from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.feature_flags import (
    FeatureDisabledError,
    FeatureFlag,
    FeatureFlagConfigManager,
)
from config.schema import SystemConfig


def test_story_system_is_disabled_by_default() -> None:
    manager = FeatureFlagConfigManager(environ={})

    resolution = manager.resolve(FeatureFlag.STORY_SYSTEM)

    assert resolution.enabled is False
    assert resolution.source == "default"


def test_persisted_story_flag_is_resolved_centrally() -> None:
    manager = FeatureFlagConfigManager(
        SimpleNamespace(story_system_enabled=True),
        environ={},
    )

    assert manager.is_enabled(FeatureFlag.STORY_SYSTEM)
    assert manager.resolve(FeatureFlag.STORY_SYSTEM).source == (
        "config:story_system_enabled"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("ON", True), ("0", False), ("no", False)],
)
def test_environment_override_has_deterministic_boolean_parsing(
    value: str,
    expected: bool,
) -> None:
    manager = FeatureFlagConfigManager(
        SimpleNamespace(story_system_enabled=not expected),
        environ={"SHINSEKAI_STORY_SYSTEM_ENABLED": value},
    )

    assert manager.is_enabled(FeatureFlag.STORY_SYSTEM) is expected


def test_invalid_environment_value_fails_closed_with_diagnostic() -> None:
    manager = FeatureFlagConfigManager(
        SimpleNamespace(story_system_enabled=True),
        environ={"SHINSEKAI_STORY_SYSTEM_ENABLED": "sometimes"},
    )

    resolution = manager.resolve(FeatureFlag.STORY_SYSTEM)

    assert resolution.enabled is False
    assert resolution.diagnostic == "invalid boolean value 'sometimes'; failed closed"


def test_invalid_persisted_config_value_fails_closed_with_diagnostic() -> None:
    system_config = SystemConfig.model_validate({"story_system_enabled": "maybe"})
    manager = FeatureFlagConfigManager(system_config, environ={})

    resolution = manager.resolve(FeatureFlag.STORY_SYSTEM)

    assert system_config.story_system_enabled is False
    assert resolution.enabled is False
    assert resolution.source == "config:story_system_enabled"
    assert resolution.diagnostic == "invalid boolean value 'maybe'; failed closed"


def test_explicit_override_has_highest_precedence() -> None:
    manager = FeatureFlagConfigManager(
        SimpleNamespace(story_system_enabled=False),
        environ={"SHINSEKAI_STORY_SYSTEM_ENABLED": "false"},
        overrides={FeatureFlag.STORY_SYSTEM: True},
    )

    assert manager.is_enabled(FeatureFlag.STORY_SYSTEM)
    assert manager.resolve(FeatureFlag.STORY_SYSTEM).source == "override"


def test_require_raises_a_typed_error_when_disabled() -> None:
    manager = FeatureFlagConfigManager(environ={})

    with pytest.raises(FeatureDisabledError) as exc_info:
        manager.require(FeatureFlag.STORY_SYSTEM)

    assert exc_info.value.flag == FeatureFlag.STORY_SYSTEM


def test_unknown_flags_are_rejected() -> None:
    manager = FeatureFlagConfigManager(environ={})

    with pytest.raises(KeyError):
        manager.is_enabled("story_runtime_enabled")
