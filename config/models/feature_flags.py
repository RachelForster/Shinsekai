"""Centralized, fail-closed feature flag resolution for Shinsekai."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import os
from types import MappingProxyType
from typing import Any


class FeatureFlag(str, Enum):
    """Registered host feature flags.

    Story capabilities intentionally share one master switch while the staged
    implementation is experimental. New story sub-flags must not be added in
    individual modules.
    """

    STORY_SYSTEM = "story_system"


@dataclass(frozen=True, slots=True)
class FeatureFlagResolution:
    enabled: bool
    source: str
    diagnostic: str | None = None


class FeatureDisabledError(RuntimeError):
    def __init__(self, flag: FeatureFlag, resolution: FeatureFlagResolution) -> None:
        self.flag = flag
        self.resolution = resolution
        super().__init__(f"feature {flag.value!r} is disabled ({resolution.source})")


class FeatureFlagConfigManager:
    """Resolve registered flags from overrides, environment, and app config.

    Precedence is explicit process override, environment variable, persisted
    ``SystemConfig``, then the registry default. Invalid values fail closed and
    retain a diagnostic so callers never have to interpret raw configuration.
    """

    _CONFIG_FIELDS: Mapping[FeatureFlag, str] = MappingProxyType(
        {FeatureFlag.STORY_SYSTEM: "story_system_enabled"}
    )
    _ENVIRONMENT_FIELDS: Mapping[FeatureFlag, str] = MappingProxyType(
        {FeatureFlag.STORY_SYSTEM: "SHINSEKAI_STORY_SYSTEM_ENABLED"}
    )
    _DEFAULTS: Mapping[FeatureFlag, bool] = MappingProxyType(
        {FeatureFlag.STORY_SYSTEM: False}
    )

    def __init__(
        self,
        system_config: object | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        overrides: Mapping[FeatureFlag | str, bool] | None = None,
    ) -> None:
        self._system_config = system_config
        self._environ = os.environ if environ is None else environ
        self._overrides = self._normalize_overrides(overrides or {})

    def is_enabled(self, flag: FeatureFlag | str) -> bool:
        return self.resolve(flag).enabled

    def resolve(self, flag: FeatureFlag | str) -> FeatureFlagResolution:
        registered = self._registered(flag)
        if registered in self._overrides:
            return FeatureFlagResolution(
                enabled=self._overrides[registered],
                source="override",
            )

        environment_name = self._ENVIRONMENT_FIELDS[registered]
        raw_environment = self._environ.get(environment_name)
        if raw_environment is not None:
            parsed = self._parse_bool(raw_environment)
            if parsed is None:
                return FeatureFlagResolution(
                    enabled=False,
                    source=f"environment:{environment_name}",
                    diagnostic=f"invalid boolean value {raw_environment!r}; failed closed",
                )
            return FeatureFlagResolution(
                enabled=parsed,
                source=f"environment:{environment_name}",
            )

        config_field = self._CONFIG_FIELDS[registered]
        if self._system_config is not None and hasattr(
            self._system_config, config_field
        ):
            configured = getattr(self._system_config, config_field)
            load_diagnostic = getattr(
                self._system_config, f"{config_field}_diagnostic", None
            )
            if isinstance(load_diagnostic, str) and load_diagnostic.strip():
                return FeatureFlagResolution(
                    enabled=False,
                    source=f"config:{config_field}",
                    diagnostic=load_diagnostic,
                )
            if isinstance(configured, bool):
                return FeatureFlagResolution(
                    enabled=configured,
                    source=f"config:{config_field}",
                )
            return FeatureFlagResolution(
                enabled=False,
                source=f"config:{config_field}",
                diagnostic=f"non-boolean config value {configured!r}; failed closed",
            )

        return FeatureFlagResolution(
            enabled=self._DEFAULTS[registered],
            source="default",
        )

    def require(self, flag: FeatureFlag | str) -> None:
        registered = self._registered(flag)
        resolution = self.resolve(registered)
        if not resolution.enabled:
            raise FeatureDisabledError(registered, resolution)

    def snapshot(self) -> Mapping[FeatureFlag, FeatureFlagResolution]:
        return MappingProxyType({flag: self.resolve(flag) for flag in FeatureFlag})

    @classmethod
    def environment_name(cls, flag: FeatureFlag | str) -> str:
        return cls._ENVIRONMENT_FIELDS[cls._registered(flag)]

    @classmethod
    def config_field(cls, flag: FeatureFlag | str) -> str:
        return cls._CONFIG_FIELDS[cls._registered(flag)]

    @classmethod
    def _normalize_overrides(
        cls,
        overrides: Mapping[FeatureFlag | str, bool],
    ) -> Mapping[FeatureFlag, bool]:
        normalized: dict[FeatureFlag, bool] = {}
        for flag, value in overrides.items():
            registered = cls._registered(flag)
            if not isinstance(value, bool):
                raise TypeError(f"override for {registered.value!r} must be a boolean")
            normalized[registered] = value
        return MappingProxyType(normalized)

    @staticmethod
    def _registered(flag: FeatureFlag | str) -> FeatureFlag:
        if isinstance(flag, FeatureFlag):
            return flag
        try:
            return FeatureFlag(str(flag))
        except ValueError as error:
            raise KeyError(f"unregistered feature flag {flag!r}") from error

    @classmethod
    def coerce_persisted_value(cls, value: Any) -> tuple[bool, str | None]:
        """Coerce a persisted flag value without raising.

        Invalid values fail closed (``False``) and return a diagnostic. ``None``
        uses the registry default and is not treated as a load error.
        """
        if value is None:
            return False, None
        if isinstance(value, bool):
            return value, None
        parsed = cls._parse_bool(value)
        if parsed is None:
            return False, f"invalid boolean value {value!r}; failed closed"
        return parsed, None

    @staticmethod
    def _parse_bool(value: Any) -> bool | None:
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return None
