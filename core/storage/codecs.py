"""Reusable Pydantic codecs for YAML and JSON storage backends."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
import yaml

M = TypeVar("M", bound=BaseModel)


class _BasePydanticCodec(Generic[M]):
    """Shared validation, pre-decode normalization, and serialization behavior."""

    def __init__(
        self,
        model_type: type[M],
        *,
        default_factory: Callable[[], M] | None = None,
        pre_decode: Callable[[Any], Any] | None = None,
        by_alias: bool = True,
        exclude_none: bool = False,
    ) -> None:
        self._model_type = model_type
        self._default_factory = default_factory
        self._pre_decode = pre_decode
        self._by_alias = by_alias
        self._exclude_none = exclude_none

    def default(self) -> M:
        if self._default_factory is not None:
            return self._default_factory()
        return self._model_type()

    def decode(self, raw: bytes) -> M:
        text = raw.decode("utf-8").strip()
        if not text:
            return self.default()
        parsed = self._parse_text(text)
        if parsed is None:
            return self.default()
        if self._pre_decode is not None:
            parsed = self._pre_decode(parsed)
            if parsed is None:
                return self.default()
        return self._model_type.model_validate(parsed)

    def encode(self, value: M) -> bytes:
        payload = value.model_dump(
            mode="json",
            by_alias=self._by_alias,
            exclude_none=self._exclude_none,
        )
        return self._dump_text(payload).encode("utf-8")

    def _parse_text(self, text: str) -> Any:
        raise NotImplementedError

    def _dump_text(self, payload: Any) -> str:
        raise NotImplementedError


class PydanticYamlCodec(_BasePydanticCodec[M]):
    """Codec bridging Pydantic models and UTF-8 YAML documents."""

    def _parse_text(self, text: str) -> Any:
        return yaml.safe_load(text)

    def _dump_text(self, payload: Any) -> str:
        return yaml.safe_dump(
            payload,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


class PydanticJsonCodec(_BasePydanticCodec[M]):
    """Codec bridging Pydantic models and UTF-8 JSON documents."""

    def _parse_text(self, text: str) -> Any:
        return json.loads(text)

    def _dump_text(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


__all__ = ["PydanticJsonCodec", "PydanticYamlCodec"]
