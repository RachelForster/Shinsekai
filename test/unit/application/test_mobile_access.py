from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.chat.mobile_access import (
    MobileAccessInfo,
    configure_mobile_access,
    get_mobile_access_info,
    stop_mobile_access,
)


class _MobileAccessPort:
    def __init__(self) -> None:
        self.info = MobileAccessInfo(
            host="192.168.1.20",
            http_port=8789,
            websocket_port=8790,
            url="http://192.168.1.20:8789/#/chat",
            websocket_url="ws://192.168.1.20:8790/ws",
            qr_code_data_url="data:image/png;base64,dGVzdA==",
        )
        self.started = 0
        self.stopped = 0
        self.active = False

    def snapshot(self) -> MobileAccessInfo | None:
        return self.info if self.active else None

    def start(self) -> MobileAccessInfo:
        self.started += 1
        self.active = True
        return self.info

    def stop(self) -> None:
        self.stopped += 1
        self.active = False


def test_configure_mobile_access_owns_enable_and_disable_lifecycle(capsys) -> None:
    port = _MobileAccessPort()
    state = SimpleNamespace(mobile_access_service=port)

    info = configure_mobile_access(state, enabled=True)

    assert info is port.info
    assert port.started == 1
    assert get_mobile_access_info(state) is port.info
    assert "TCP 端口 8789 和 8790" in capsys.readouterr().out

    assert configure_mobile_access(state, enabled=False) is None
    assert port.stopped == 1
    assert get_mobile_access_info(state) is None


def test_configure_mobile_access_requires_an_injected_transport_when_enabled() -> None:
    state = SimpleNamespace(mobile_access_service=None)

    with pytest.raises(RuntimeError, match="移动访问服务不可用"):
        configure_mobile_access(state, enabled=True)

    assert configure_mobile_access(state, enabled=False) is None


def test_stop_mobile_access_is_safe_without_an_injected_transport() -> None:
    stop_mobile_access(SimpleNamespace())
