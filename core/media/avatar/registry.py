"""运行时的模型形象格式注册表。

内置格式通过 :func:`register_adapter` 注册；插件通过 sdk 的
``register_avatar_format`` 贡献，由插件宿主调用
:func:`configure_registered_formats` 汇入。共享代码只通过
:func:`adapter_for` / :func:`capabilities_for` 查询，不直接 import 具体格式。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable

from sdk.adapters import (
    AvatarFormatContribution,
    ModelAssetAdapter,
    ModelCapabilities,
)

logger = logging.getLogger(__name__)

_STATIC_AVATAR_TYPE = "static"

_lock = threading.RLock()
_builtin: dict[str, ModelAssetAdapter] = {}
_plugin: dict[str, ModelAssetAdapter] = {}


def _normalize_format_id(format_id: object) -> str:
    return str(format_id or "").strip().lower()


def register_adapter(adapter: ModelAssetAdapter) -> None:
    """注册一个内置格式 adapter（PR B/C 的各格式在模块导入时调用）。"""
    format_id = _normalize_format_id(getattr(adapter, "format_id", ""))
    if not format_id:
        raise ValueError("avatar adapter requires a non-empty format_id")
    if format_id == _STATIC_AVATAR_TYPE:
        raise ValueError("'static' is a reserved avatar type")
    with _lock:
        if format_id in _builtin:
            raise ValueError(f"duplicate avatar format: {format_id}")
        _builtin[format_id] = adapter


def configure_registered_formats(
    contributions: Iterable[AvatarFormatContribution],
) -> None:
    """原子替换插件提供的格式集合（由插件宿主调用）。"""
    registered: dict[str, ModelAssetAdapter] = {}
    for contribution in contributions:
        try:
            adapter = contribution.factory()
        except Exception:
            logger.exception(
                "avatar format factory failed for %r",
                contribution.format_id,
            )
            continue
        format_id = _normalize_format_id(
            getattr(adapter, "format_id", "") or contribution.format_id
        )
        if (
            not format_id
            or format_id == _STATIC_AVATAR_TYPE
            or format_id in _builtin
        ):
            continue
        registered[format_id] = adapter
    with _lock:
        _plugin.clear()
        _plugin.update(registered)


def adapter_for(format_id: str) -> ModelAssetAdapter:
    """按格式 id 返回 adapter；未知 id 抛 KeyError。"""
    key = _normalize_format_id(format_id)
    with _lock:
        adapter = _builtin.get(key)
        if adapter is None:
            adapter = _plugin.get(key)
    if adapter is None:
        raise KeyError(f"unknown avatar format: {format_id}")
    return adapter


def registered_format_ids() -> tuple[str, ...]:
    with _lock:
        keys = set(_builtin) | set(_plugin)
    return tuple(sorted(keys))


def capabilities_for(format_id: str) -> ModelCapabilities:
    return adapter_for(format_id).capabilities


def is_registered_format(format_id: str) -> bool:
    key = _normalize_format_id(format_id)
    with _lock:
        return key in _builtin or key in _plugin


def _reset_for_tests() -> None:
    """仅测试使用：清空内置与插件注册表。"""
    with _lock:
        _builtin.clear()
        _plugin.clear()
