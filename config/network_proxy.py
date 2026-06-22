"""Apply user-configured network proxy settings to the current process."""

from __future__ import annotations

import logging
import os
import platform as platform_module
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_HTTP_PROXY_ENV_NAMES = ("HTTP_PROXY", "http_proxy")
_HTTPS_PROXY_ENV_NAMES = ("HTTPS_PROXY", "https_proxy")
_SOCKS_PROXY_ENV_NAMES = ("ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy")
_MANAGED_PROXY_ENV_NAMES = _HTTP_PROXY_ENV_NAMES + _HTTPS_PROXY_ENV_NAMES + _SOCKS_PROXY_ENV_NAMES
_ORIGINAL_PROXY_ENV = {name: os.environ.get(name) for name in _MANAGED_PROXY_ENV_NAMES}


@dataclass(frozen=True)
class NetworkProxyValues:
    http: str
    https: str
    socks5: str


@dataclass(frozen=True)
class NetworkProxyDetection:
    http_proxy_url: str
    https_proxy_url: str
    socks5_proxy_url: str
    source: str

    @property
    def detected(self) -> bool:
        return bool(self.http_proxy_url or self.https_proxy_url or self.socks5_proxy_url)

    def as_payload(self) -> dict[str, str]:
        return {
            "http_proxy_url": self.http_proxy_url,
            "https_proxy_url": self.https_proxy_url,
            "socks5_proxy_url": self.socks5_proxy_url,
            "source": self.source,
        }


def normalize_proxy_url(value: Any, *, allowed_schemes: set[str], field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in allowed_schemes or not parsed.netloc:
        allowed = "/".join(sorted(allowed_schemes))
        example_scheme = next(iter(sorted(allowed_schemes)))
        raise ValueError(
            f"{field_name} must be a {allowed} URL, "
            f"for example {example_scheme}://127.0.0.1:7890"
        )
    return raw


def resolved_network_proxy_values(config: Any) -> NetworkProxyValues:
    if not bool(getattr(config, "network_proxy_enabled", False)):
        return NetworkProxyValues(http="", https="", socks5="")
    return NetworkProxyValues(
        http=str(getattr(config, "http_proxy_url", "") or "").strip(),
        https=str(getattr(config, "https_proxy_url", "") or "").strip(),
        socks5=str(getattr(config, "socks5_proxy_url", "") or "").strip(),
    )


def apply_network_proxy_environment(config: Any) -> NetworkProxyValues:
    values = resolved_network_proxy_values(config)
    _set_proxy_env(_HTTP_PROXY_ENV_NAMES, values.http)
    _set_proxy_env(_HTTPS_PROXY_ENV_NAMES, values.https)
    _set_proxy_env(_SOCKS_PROXY_ENV_NAMES, values.socks5)
    logger.info(
        "Network proxy environment applied",
        extra={
            "event": "network.proxy.applied",
            "http_proxy": _redact_proxy(values.http),
            "https_proxy": _redact_proxy(values.https),
            "socks5_proxy": _redact_proxy(values.socks5),
        },
    )
    return values


def apply_network_proxy_environment_from_system_config(path: str | Path | None = None) -> NetworkProxyValues:
    """Apply proxy env early without constructing the full ConfigManager."""
    try:
        import yaml
        from config.schema import SystemConfig

        config_path = Path(path or "data/config/system_config.yaml")
        raw = {}
        if config_path.is_file():
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw = loaded if isinstance(loaded, dict) else {}
        return apply_network_proxy_environment(SystemConfig.model_validate(raw))
    except Exception as exc:
        logger.warning(
            "Falling back to empty network proxy configuration after config read failed: %s",
            exc,
            extra={"event": "network.proxy.fallback"},
        )
        return apply_network_proxy_environment(_FallbackNetworkProxyConfig())


def detect_network_proxy_configuration() -> NetworkProxyDetection:
    system_name = platform_module.system().lower()
    system_detectors = []
    if system_name == "windows":
        system_detectors.append(_detect_windows_proxy)
    elif system_name == "darwin":
        system_detectors.append(_detect_macos_proxy)
    elif system_name == "linux":
        system_detectors.extend((_detect_gnome_proxy, _detect_kde_proxy))

    for detector in [*system_detectors, _detect_original_environment_proxy, _detect_current_environment_proxy]:
        try:
            detected = detector()
        except Exception as exc:
            logger.debug(
                "Network proxy detector failed: %s",
                exc,
                extra={"event": "network.proxy.detect.failed", "detector": detector.__name__},
            )
            continue
        if detected.detected:
            logger.info(
                "Network proxy detected",
                extra={"event": "network.proxy.detected", "source": detected.source},
            )
            return detected
    return NetworkProxyDetection(http_proxy_url="", https_proxy_url="", socks5_proxy_url="", source="")


def _set_proxy_env(names: tuple[str, ...], value: str) -> None:
    if os.name == "nt" and value:
        os.environ[names[0]] = value
        return

    if os.name == "nt" and not value:
        restore = next(((name, _ORIGINAL_PROXY_ENV.get(name)) for name in names if _ORIGINAL_PROXY_ENV.get(name)), None)
        for name in names:
            os.environ.pop(name, None)
        if restore is not None:
            os.environ[restore[0]] = restore[1] or ""
        return

    for name in names:
        if value:
            os.environ[name] = value
            continue
        original = _ORIGINAL_PROXY_ENV.get(name)
        if original is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = original


def _redact_proxy(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.netloc or "@" not in parsed.netloc:
        return value
    host = parsed.netloc.rsplit("@", 1)[-1]
    return parsed._replace(netloc=f"***@{host}").geturl()


class _FallbackNetworkProxyConfig:
    network_proxy_enabled = False
    http_proxy_url = ""
    https_proxy_url = ""
    socks5_proxy_url = ""


def _detect_original_environment_proxy() -> NetworkProxyDetection:
    return _detect_proxy_from_mapping(_ORIGINAL_PROXY_ENV, "environment")


def _detect_current_environment_proxy() -> NetworkProxyDetection:
    return _detect_proxy_from_mapping(os.environ, "process-environment")


def _detect_proxy_from_mapping(mapping: Any, source: str) -> NetworkProxyDetection:
    def first(names: tuple[str, ...]) -> str:
        for name in names:
            value = mapping.get(name) if hasattr(mapping, "get") else None
            if value:
                return str(value)
        return ""

    all_proxy = first(_SOCKS_PROXY_ENV_NAMES)
    all_proxy_as_http = _normalize_detected_http_proxy(all_proxy)
    all_proxy_as_socks = _normalize_detected_socks_proxy(all_proxy)
    return NetworkProxyDetection(
        http_proxy_url=_normalize_detected_http_proxy(first(_HTTP_PROXY_ENV_NAMES)) or all_proxy_as_http,
        https_proxy_url=_normalize_detected_http_proxy(first(_HTTPS_PROXY_ENV_NAMES)) or all_proxy_as_http,
        socks5_proxy_url=all_proxy_as_socks,
        source=source,
    )


def _detect_windows_proxy() -> NetworkProxyDetection:
    try:
        import winreg
    except Exception:
        return NetworkProxyDetection("", "", "", "windows")

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
    ) as key:
        enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
        if not enabled:
            return NetworkProxyDetection("", "", "", "windows")
        proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
    return _parse_windows_proxy_server(proxy_server)


def _parse_windows_proxy_server(value: str) -> NetworkProxyDetection:
    raw = str(value or "").strip()
    if not raw:
        return NetworkProxyDetection("", "", "", "windows")
    if "=" not in raw:
        http = _normalize_detected_http_proxy(raw)
        return NetworkProxyDetection(http, http, "", "windows")

    parts: dict[str, str] = {}
    for entry in raw.split(";"):
        key, separator, part_value = entry.partition("=")
        if separator:
            parts[key.strip().lower()] = part_value.strip()
    return NetworkProxyDetection(
        http_proxy_url=_normalize_detected_http_proxy(parts.get("http", "")),
        https_proxy_url=_normalize_detected_http_proxy(parts.get("https", "")),
        socks5_proxy_url=_normalize_detected_socks_proxy(parts.get("socks", "")),
        source="windows",
    )


def _detect_macos_proxy() -> NetworkProxyDetection:
    if not shutil.which("scutil"):
        return NetworkProxyDetection("", "", "", "macos")
    output = _run_text_command(["scutil", "--proxy"])
    values = _parse_scutil_proxy_output(output)
    return NetworkProxyDetection(
        http_proxy_url=_proxy_from_host_port(
            "http",
            values.get("HTTPProxy", ""),
            values.get("HTTPPort", ""),
            enabled=values.get("HTTPEnable") == "1",
        ),
        https_proxy_url=_proxy_from_host_port(
            "http",
            values.get("HTTPSProxy", ""),
            values.get("HTTPSPort", ""),
            enabled=values.get("HTTPSEnable") == "1",
        ),
        socks5_proxy_url=_proxy_from_host_port(
            "socks5",
            values.get("SOCKSProxy", ""),
            values.get("SOCKSPort", ""),
            enabled=values.get("SOCKSEnable") == "1",
        ),
        source="macos",
    )


def _parse_scutil_proxy_output(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _detect_gnome_proxy() -> NetworkProxyDetection:
    if not shutil.which("gsettings"):
        return NetworkProxyDetection("", "", "", "gnome")
    mode = _strip_command_value(_run_text_command(["gsettings", "get", "org.gnome.system.proxy", "mode"]))
    if mode != "manual":
        return NetworkProxyDetection("", "", "", "gnome")
    return NetworkProxyDetection(
        http_proxy_url=_proxy_from_host_port(
            "http",
            _strip_command_value(_run_text_command(["gsettings", "get", "org.gnome.system.proxy.http", "host"])),
            _strip_command_value(_run_text_command(["gsettings", "get", "org.gnome.system.proxy.http", "port"])),
        ),
        https_proxy_url=_proxy_from_host_port(
            "http",
            _strip_command_value(_run_text_command(["gsettings", "get", "org.gnome.system.proxy.https", "host"])),
            _strip_command_value(_run_text_command(["gsettings", "get", "org.gnome.system.proxy.https", "port"])),
        ),
        socks5_proxy_url=_proxy_from_host_port(
            "socks5",
            _strip_command_value(_run_text_command(["gsettings", "get", "org.gnome.system.proxy.socks", "host"])),
            _strip_command_value(_run_text_command(["gsettings", "get", "org.gnome.system.proxy.socks", "port"])),
        ),
        source="gnome",
    )


def _detect_kde_proxy() -> NetworkProxyDetection:
    config_path = Path.home() / ".config" / "kioslaverc"
    if not config_path.is_file():
        return NetworkProxyDetection("", "", "", "kde")
    try:
        import configparser

        parser = configparser.ConfigParser()
        parser.optionxform = str  # preserve KDE key casing
        parser.read(config_path, encoding="utf-8")
        section = parser["Proxy Settings"]
        if str(section.get("ProxyType", "")).strip() != "1":
            return NetworkProxyDetection("", "", "", "kde")
        return NetworkProxyDetection(
            http_proxy_url=_normalize_detected_http_proxy(_normalize_kde_proxy_value(section.get("httpProxy", ""))),
            https_proxy_url=_normalize_detected_http_proxy(_normalize_kde_proxy_value(section.get("httpsProxy", ""))),
            socks5_proxy_url=_normalize_detected_socks_proxy(_normalize_kde_proxy_value(section.get("socksProxy", ""))),
            source="kde",
        )
    except Exception:
        return NetworkProxyDetection("", "", "", "kde")


def _run_text_command(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=1.5,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or command[0]).strip())
    return completed.stdout


def _strip_command_value(value: str) -> str:
    raw = str(value or "").strip()
    if raw in {"''", '""'}:
        return ""
    if (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')):
        return raw[1:-1]
    return raw


def _normalize_kde_proxy_value(value: str) -> str:
    raw = str(value or "").strip()
    if "://" in raw:
        return raw
    parts = raw.split()
    if len(parts) == 2 and parts[1].isdigit():
        return f"{parts[0]}:{parts[1]}"
    return raw


def _proxy_from_host_port(scheme: str, host: str, port: str, *, enabled: bool = True) -> str:
    if not enabled:
        return ""
    clean_host = str(host or "").strip()
    clean_port = str(port or "").strip()
    if not clean_host:
        return ""
    host_part = clean_host
    if ":" in clean_host and not clean_host.startswith("[") and clean_host.count(":") > 1:
        host_part = f"[{clean_host}]"
    raw = f"{host_part}:{clean_port}" if clean_port else host_part
    if scheme.startswith("socks"):
        return _normalize_detected_socks_proxy(raw)
    return _normalize_detected_http_proxy(raw)


def _normalize_detected_http_proxy(value: str) -> str:
    return _normalize_detected_proxy_url(value, allowed_schemes={"http", "https"}, default_scheme="http")


def _normalize_detected_socks_proxy(value: str) -> str:
    return _normalize_detected_proxy_url(value, allowed_schemes={"socks5", "socks5h"}, default_scheme="socks5")


def _normalize_detected_proxy_url(value: str, *, allowed_schemes: set[str], default_scheme: str) -> str:
    raw = str(value or "").strip().strip("\"'")
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"{default_scheme}://{raw}"
    try:
        return normalize_proxy_url(raw, allowed_schemes=allowed_schemes, field_name="proxy")
    except ValueError:
        return ""
