from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ClassVar


@dataclass(frozen=True, slots=True)
class ModelFiles:
    """一个模型入口及其导入所需的完整依赖文件。"""

    entry: Path
    files: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """一个模型形象格式对共享层声明的能力。

    共享层据此降级（例如不驱动嘴型、不提供动态采样），而不是按格式名硬编码假设。
    """

    mouth: bool = False  # 语音音量可驱动嘴型
    blink: bool = False  # 支持自动眨眼
    motion: bool = False  # 支持一次性动作
    sampling: str = "none"  # none | single | multi（预览采样）


class ModelAssetAdapter(ABC):
    """模型形象格式的后端文件能力。

    无角色、无会话状态：inspect 不复制文件，parse_state 不保存文件，adapter 不修改角色。
    实现放在各格式自己的模块里，通过
    :meth:`sdk.register.PluginCapabilityRegistry.register_avatar_format`（插件）或
    :func:`core.media.avatar.registry.register_adapter`（内置格式）注册。
    子类以类属性声明 ``format_id`` 与 ``capabilities``。
    """

    format_id: ClassVar[str] = ""
    capabilities: ClassVar[ModelCapabilities] = ModelCapabilities()

    @abstractmethod
    def inspect(self, source: Path) -> ModelFiles:
        """识别一个模型入口，并列出导入时需要的完整依赖。"""

    @abstractmethod
    def parse_state(self, model: Path, value: object) -> dict:
        """校验结构、有限数值和文件引用，返回规范化状态。"""

    @abstractmethod
    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        """列出状态额外引用的动作、表情等文件，供角色包打包。"""


@dataclass(frozen=True, slots=True)
class AvatarFormatContribution:
    """插件提供的模型形象格式。

    工厂延迟实例化 adapter，便于把重型 SDK 导入推迟到真正加载时。
    """

    format_id: str
    factory: Callable[[], ModelAssetAdapter]
    label: str = ""
    priority: int = 100
