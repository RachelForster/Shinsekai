"""根据适配器 __init__ 签名过滤「额外配置」，避免传入无效关键字参数。"""

from __future__ import annotations

import inspect
from typing import Any


def filter_kwargs_for_ctor(cls: type, extra: dict[str, Any]) -> dict[str, Any]:
    """仅保留目标类构造函数可接受的命名参数；若存在 **kwargs 则返回 extra 的拷贝。"""
    if not extra:
        return {}
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return {}
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return dict(extra)
    return {k: v for k, v in extra.items() if k in sig.parameters}
