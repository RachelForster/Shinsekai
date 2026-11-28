"""Chat-stage event protocol, snapshot reducer, and application sink contracts.

设计文档《chat_ui_react_migration_and_theme_system.md》"参考接口输出 · D"。

``ChatEventSink`` 是演出输出的抽象出口；具体 HTTP/WebSocket 传输适配器位于
``frontend_bridge_core.transport``，由进程入口注入 application。
"""

from __future__ import annotations

import itertools
import time
from typing import Any, Dict, Protocol, runtime_checkable

from application.chat.stage_events import (
    fold_event_into_snapshot,
    make_empty_chat_snapshot,
)

#: 事件协议版本，与前端 ``ChatStageEvent`` 的 ``v`` 字段一致。
EVENT_PROTOCOL_VERSION = 1


@runtime_checkable
class ChatEventSink(Protocol):
    """演出事件出口契约。"""

    def emit(self, payload: Dict[str, Any]) -> None:
        """发送一个事件。

        ``payload`` 是业务字段（至少含 ``type``），实现负责补信封 ``v``/``seq``/``ts``
        （见 ``build_event``）。
        """
        ...

    def snapshot(self) -> Dict[str, Any]:
        """返回累积的舞台全量状态，供新连接/重连的 viewer 首帧 hydrate。"""
        ...


def build_event(seq: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """把业务字段组装成带信封（v/seq/ts）的完整事件。

    ``payload`` 至少包含 ``type``，其余为该事件类型的字段。
    """
    event = {
        "v": EVENT_PROTOCOL_VERSION,
        "seq": seq,
        "ts": int(time.time() * 1000),
    }
    event.update(payload)
    if event.get("type") == "sprite.show":
        event["avatarType"] = str(event.get("avatarType") or "static")
        event["modelUrl"] = str(event.get("modelUrl") or "")
    return event


class BaseEventSink:
    """共享 seq 计数 + 最新快照累积的基类。"""

    def __init__(self) -> None:
        self._seq = itertools.count(1)
        self._snapshot: Dict[str, Any] = make_empty_chat_snapshot()

    def _next(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_event(next(self._seq), payload)

    def _remember(self, event: Dict[str, Any]) -> None:
        """把事件折叠进快照，便于 ``snapshot()`` 给新 viewer。"""
        self._snapshot = fold_event_into_snapshot(self._snapshot, event)

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._snapshot)


class NullEventSink(BaseEventSink):
    """丢弃所有事件的 sink（无 stream 端点时的默认实现，等价 headless）。"""

    def emit(self, payload: Dict[str, Any]) -> None:
        self._remember(self._next(payload))


__all__ = [
    "BaseEventSink",
    "ChatEventSink",
    "EVENT_PROTOCOL_VERSION",
    "NullEventSink",
    "build_event",
    "fold_event_into_snapshot",
    "make_empty_chat_snapshot",
]
