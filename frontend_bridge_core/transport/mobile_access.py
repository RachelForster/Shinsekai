"""Concrete LAN HTTP/WebSocket transport for temporary mobile chat access."""

from __future__ import annotations

import base64
import ipaddress
import socket
import threading
from io import BytesIO
from typing import Any, Callable
from urllib.parse import quote

from application.chat.mobile_access import MobileAccessInfo


class MobileAccessError(RuntimeError):
    """Raised when temporary mobile access cannot be started."""


def _usable_lan_ipv4(raw_host: str) -> str:
    try:
        address = ipaddress.ip_address(str(raw_host or "").strip())
    except ValueError:
        return ""
    if (
        address.version != 4
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        return ""
    return str(address)


def discover_lan_ipv4() -> str:
    """Return the preferred non-loopback IPv4 address for this machine."""

    candidates: list[str] = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects an outbound interface without sending traffic.
        probe.connect(("1.1.1.1", 80))
        candidates.append(str(probe.getsockname()[0]))
    except OSError:
        pass
    finally:
        probe.close()

    try:
        _host, _aliases, addresses = socket.gethostbyname_ex(socket.gethostname())
        candidates.extend(addresses)
    except OSError:
        pass

    for candidate in candidates:
        if usable := _usable_lan_ipv4(candidate):
            return usable
    raise MobileAccessError(
        "未检测到可用的局域网 IPv4 地址。请连接 Wi-Fi 或有线网络后重试。"
    )


def generate_qr_data_url(value: str) -> str:
    """Generate a PNG QR code as a browser-ready data URL."""

    target = str(value or "").strip()
    if not target:
        raise ValueError("QR code target is required")
    try:
        import qrcode
    except ImportError as exc:  # pragma: no cover - dependency failure is environment-specific
        raise MobileAccessError(
            "二维码组件未安装，请重新运行安装程序或执行 `pip install qrcode`。"
        ) from exc

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=4,
        )
        qr.add_data(target)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
    except ImportError as exc:  # pragma: no cover - dependency failure is environment-specific
        raise MobileAccessError(
            "二维码组件或 Pillow 未安装，请重新运行安装程序。"
        ) from exc
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


HttpServerFactory = Callable[[str, int], Any]
WebSocketStarter = Callable[[str, int], str]
WebSocketStopper = Callable[[], None]


class MobileAccessTransport:
    """Own the temporary LAN HTTP/WebSocket listeners and their QR payload."""

    def __init__(
        self,
        *,
        auth_token: str,
        http_server_factory: HttpServerFactory,
        preferred_http_port: int,
        start_websocket: WebSocketStarter,
        stop_websocket: WebSocketStopper,
        advertised_host_factory: Callable[[], str] = discover_lan_ipv4,
        port_attempts: int = 20,
    ) -> None:
        token = str(auth_token or "").strip()
        if not token:
            raise ValueError("Mobile access requires an auth token")
        self._auth_token = token
        self._http_server_factory = http_server_factory
        self._preferred_http_port = max(1, int(preferred_http_port))
        self._start_websocket = start_websocket
        self._stop_websocket = stop_websocket
        self._advertised_host_factory = advertised_host_factory
        self._port_attempts = max(1, int(port_attempts))
        self._lock = threading.RLock()
        self._http_server: Any = None
        self._http_thread: threading.Thread | None = None
        self._info: MobileAccessInfo | None = None

    def snapshot(self) -> MobileAccessInfo | None:
        with self._lock:
            return self._info

    def start(self) -> MobileAccessInfo:
        with self._lock:
            if self._info is not None:
                return self._info

            host = _usable_lan_ipv4(self._advertised_host_factory())
            if not host:
                raise MobileAccessError("检测到的局域网地址不可用。")

            last_error: Exception | None = None
            for offset in range(self._port_attempts):
                http_port = self._preferred_http_port + offset * 2
                websocket_port = http_port + 1
                http_server = None
                websocket_started = False
                try:
                    http_server = self._http_server_factory("0.0.0.0", http_port)
                    websocket_url = self._start_websocket(host, websocket_port)
                    websocket_started = True
                    url = (
                        f"http://{host}:{http_port}/"
                        f"?shinsekai_bridge_token={quote(self._auth_token, safe='')}#/chat"
                    )
                    info = MobileAccessInfo(
                        host=host,
                        http_port=http_port,
                        websocket_port=websocket_port,
                        url=url,
                        websocket_url=websocket_url,
                        qr_code_data_url=generate_qr_data_url(url),
                    )
                except Exception as exc:
                    last_error = exc
                    if websocket_started:
                        try:
                            self._stop_websocket()
                        except Exception:
                            pass
                    if http_server is not None:
                        try:
                            http_server.server_close()
                        except Exception:
                            pass
                    if isinstance(exc, MobileAccessError):
                        raise
                    continue

                thread = threading.Thread(
                    target=http_server.serve_forever,
                    name=f"shinsekai-mobile-http-{http_port}",
                    daemon=True,
                )
                self._http_server = http_server
                self._http_thread = thread
                self._info = info
                thread.start()
                return info

            detail = f": {last_error}" if last_error else ""
            raise MobileAccessError(
                f"无法打开移动访问端口，请检查防火墙或端口占用{detail}"
            )

    def stop(self) -> None:
        with self._lock:
            http_server = self._http_server
            http_thread = self._http_thread
            self._http_server = None
            self._http_thread = None
            self._info = None

        try:
            self._stop_websocket()
        except Exception:
            pass
        if http_server is not None:
            try:
                http_server.shutdown()
            except Exception:
                pass
            try:
                http_server.server_close()
            except Exception:
                pass
        if http_thread is not None and http_thread is not threading.current_thread():
            http_thread.join(timeout=2.0)
