"""Application use case for chat-coupled mobile access lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sdk.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class MobileAccessInfo:
    host: str
    http_port: int
    websocket_port: int
    url: str
    websocket_url: str
    qr_code_data_url: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "host": self.host,
            "httpPort": self.http_port,
            "websocketPort": self.websocket_port,
            "url": self.url,
            "websocketUrl": self.websocket_url,
            "qrCodeDataUrl": self.qr_code_data_url,
        }


class MobileAccessPort(Protocol):
    """Transport port injected by the frontend bridge composition root."""

    def snapshot(self) -> MobileAccessInfo | None: ...

    def start(self) -> MobileAccessInfo: ...

    def stop(self) -> None: ...


def _mobile_access_port(state: object) -> MobileAccessPort | None:
    return getattr(state, "mobile_access_service", None)


def get_mobile_access_info(state: object) -> MobileAccessInfo | None:
    port = _mobile_access_port(state)
    return port.snapshot() if port is not None else None


def configure_mobile_access(
    state: object,
    *,
    enabled: bool,
) -> MobileAccessInfo | None:
    """Apply the requested mobile-access state after chat lifecycle changes."""

    port = _mobile_access_port(state)
    if port is None:
        if enabled:
            raise RuntimeError("移动访问服务不可用。")
        return None
    if not enabled:
        port.stop()
        return None

    info = port.start()
    print(
        "移动访问已启用："
        f"{info.url}\n"
        "请在系统防火墙中允许 TCP 端口 "
        f"{info.http_port} 和 {info.websocket_port}。"
    )
    logger.info(
        "Mobile chat access started",
        extra={
            "event": "mobile_access.started",
            "host": info.host,
            "http_port": info.http_port,
            "websocket_port": info.websocket_port,
        },
    )
    return info


def stop_mobile_access(state: object) -> None:
    port = _mobile_access_port(state)
    if port is not None:
        port.stop()
