"""Shared HTTP session, process lifecycle, and readiness helpers for local TTS servers."""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from ai.tts.server_process import stop_server_process
from sdk.adapters import TTSAdapter

_LOCAL_HOSTS = frozenset({"", "127.0.0.1", "localhost", "0.0.0.0", "::1"})


def is_local_server_url(url: str) -> bool:
    """Return ``True`` when ``url`` targets the loopback/local machine."""
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


def wait_for_http_service_ready(
    probe: Callable[[], bool],
    *,
    service_name: str,
    process: Any,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> None:
    """Poll ``probe`` until the HTTP service responds or ``process`` exits."""
    timeout = max(0.0, float(timeout_seconds))
    interval = max(0.01, float(poll_interval_seconds))
    deadline = time.monotonic() + timeout
    while True:
        if probe():
            return

        poll = getattr(process, "poll", None)
        if callable(poll):
            return_code = poll()
            if return_code is not None:
                raise RuntimeError(
                    f"{service_name} server exited before becoming ready (code {return_code})."
                )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"{service_name} server did not become ready within {timeout:g} seconds."
            )
        time.sleep(min(interval, remaining))


def format_http_error(response: Any, action: str) -> str:
    """Extract a concise diagnostic string from an HTTP error response."""
    try:
        payload = response.json()
        detail = payload.get("Exception") or payload.get("message") or str(payload)
    except ValueError:
        detail = str(getattr(response, "text", "") or "").strip()
    detail = detail.replace("\n", " ").strip()
    return f"{action} failed with HTTP {response.status_code}: {detail[:1000]}"


class LocalHttpTTSAdapter(TTSAdapter):
    """Base helper for HTTP-backed TTS adapters with optional local process management."""

    SERVICE_NAME = "TTS"
    STARTUP_TIMEOUT_SECONDS = 600.0
    STARTUP_POLL_INTERVAL_SECONDS = 0.5

    def _init_http_runtime(self, server_url: str) -> str:
        normalized = str(server_url or "").strip().rstrip("/") + "/"
        self._session = requests.Session()
        if is_local_server_url(normalized):
            # Loopback services must not be routed through HTTP(S)_PROXY.
            self._session.trust_env = False
        self._server_process: Any = None
        return normalized

    def _http_client(self) -> Any:
        session = getattr(self, "_session", None)
        return session if session is not None else requests

    def _server_is_reachable(self) -> bool:
        return False

    def stop_server(self) -> None:
        """Close the HTTP session and terminate any spawned local TTS server process."""
        session = getattr(self, "_session", None)
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        proc = getattr(self, "_server_process", None)
        self._server_process = None
        stop_server_process(proc)

    def wait_until_ready(
        self,
        timeout_seconds: float | None = None,
        *,
        poll_interval_seconds: float | None = None,
    ) -> None:
        """Wait until the TTS server endpoint responds or raise on exit/timeout."""
        wait_for_http_service_ready(
            self._server_is_reachable,
            service_name=self.SERVICE_NAME,
            process=getattr(self, "_server_process", None),
            timeout_seconds=(
                self.STARTUP_TIMEOUT_SECONDS
                if timeout_seconds is None
                else timeout_seconds
            ),
            poll_interval_seconds=(
                self.STARTUP_POLL_INTERVAL_SECONDS
                if poll_interval_seconds is None
                else poll_interval_seconds
            ),
        )
