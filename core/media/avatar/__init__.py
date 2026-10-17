"""模型形象格式的后端注册表与查询入口。

契约类型（``ModelAssetAdapter`` 等）定义在 :mod:`sdk.adapters.avatar`，
第三方插件通过 sdk 注册；本包只持有运行时快照。
"""

from core.media.avatar.registry import (
    adapter_for,
    capabilities_for,
    configure_registered_formats,
    is_registered_format,
    register_adapter,
    registered_format_ids,
)

__all__ = [
    "adapter_for",
    "capabilities_for",
    "configure_registered_formats",
    "is_registered_format",
    "register_adapter",
    "registered_format_ids",
]
