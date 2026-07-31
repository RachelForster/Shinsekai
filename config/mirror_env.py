"""Mirror source resolution and environment variable application."""

from __future__ import annotations

import json
import locale
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdk.file_transactions import read_text_without_links
from sdk.path_contract import (
    project_root,
    require_directory_without_links,
    resolve_project_output_path,
    resolve_project_path,
    resolve_project_read_path,
)

logger = logging.getLogger(__name__)

DEFAULT_HUGGINGFACE_MIRROR_URL = "https://hf-mirror.com"
DEFAULT_GITHUB_MIRROR_URL = "https://gh-proxy.com/"
DEFAULT_PYPI_MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple/"
DEFAULT_HUGGINGFACE_CACHE_DIR = "data/cache/huggingface"
OFFICIAL_HUGGINGFACE_URL = "https://huggingface.co"
OFFICIAL_GITHUB_URL = "https://github.com"
OFFICIAL_PYPI_INDEX_URL = "https://pypi.org/simple/"

REGION_AUTO = "auto"
REGION_CHINA = "china"
REGION_GLOBAL = "global"

_NETWORK_REGION_OVERRIDE_ENV = "SHINSEKAI_NETWORK_REGION"
_SKIP_PROBE_ENV = "SHINSEKAI_SKIP_NETWORK_REGION_PROBE"
_IP_REGION_URLS_ENV = "SHINSEKAI_IP_REGION_URLS"
_DETECT_CACHE_TTL_SEC = 600.0
_DETECT_CACHE: tuple[float, bool] | None = None
_DEFAULT_IP_REGION_URLS = (
    "https://ipapi.co/country/",
    "https://api.country.is/",
)

_MANAGED_ENV_NAMES = (
    "HF_ENDPOINT",
    "HF_HOME",
    "HF_HUB_CACHE",
    "HUGGINGFACE_HUB_ENDPOINT",
    "HUGGINGFACE_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "SHINSEKAI_HUGGINGFACE_MIRROR_URL",
    "SHINSEKAI_HUGGINGFACE_CACHE_DIR",
    "GITHUB_MIRROR_URL",
    "SHINSEKAI_GITHUB_MIRROR_URL",
    "SHINSEKAI_PIP_INDEX_URL",
    "SHINSEKAI_MIRROR_REGION",
)
_ORIGINAL_ENV = {name: os.environ.get(name) for name in _MANAGED_ENV_NAMES}


@dataclass(frozen=True)
class MirrorValues:
    huggingface: str
    huggingface_cache_dir: str
    github: str
    pypi: str
    region: str


def detect_china_network(*, timeout_sec: float = 1.2) -> bool:
    """Best-effort China network detection with explicit env override support."""
    override = os.environ.get(_NETWORK_REGION_OVERRIDE_ENV, "").strip().lower()
    if override in {"cn", "china", "mainland", "mainland_china", "zh_cn"}:
        logger.info(
            "Mirror region forced to China by environment override",
            extra={"event": "mirror.region.detected", "source": "env", "region": REGION_CHINA},
        )
        return True
    if override in {"global", "intl", "international", "overseas", "us"}:
        logger.info(
            "Mirror region forced to global by environment override",
            extra={"event": "mirror.region.detected", "source": "env", "region": REGION_GLOBAL},
        )
        return False

    global _DETECT_CACHE
    now = time.monotonic()
    if _DETECT_CACHE is not None and now - _DETECT_CACHE[0] < _DETECT_CACHE_TTL_SEC:
        logger.debug(
            "Using cached mirror region detection result",
            extra={
                "event": "mirror.region.detected",
                "source": "cache",
                "region": REGION_CHINA if _DETECT_CACHE[1] else REGION_GLOBAL,
            },
        )
        return _DETECT_CACHE[1]

    skip_network_probe = bool(os.environ.get(_SKIP_PROBE_ENV))
    ip_hint = None if skip_network_probe else _detect_china_by_ip(timeout_sec=timeout_sec)
    if ip_hint is not None:
        _DETECT_CACHE = (now, ip_hint)
        logger.info(
            "Mirror region detected from public IP geolocation",
            extra={
                "event": "mirror.region.detected",
                "source": "ip_geo",
                "region": REGION_CHINA if ip_hint else REGION_GLOBAL,
            },
        )
        return ip_hint

    network_hint = None if skip_network_probe else _probe_china_network(timeout_sec=timeout_sec)
    if network_hint is not None:
        _DETECT_CACHE = (now, network_hint)
        logger.info(
            "Mirror region detected from network probe",
            extra={
                "event": "mirror.region.detected",
                "source": "network_probe",
                "region": REGION_CHINA if network_hint else REGION_GLOBAL,
            },
        )
        return network_hint

    result = _has_china_local_hint()
    _DETECT_CACHE = (now, result)
    logger.info(
        "Mirror region detected from local environment fallback",
        extra={
            "event": "mirror.region.detected",
            "source": "local_hint" if result else "fallback",
            "region": REGION_CHINA if result else REGION_GLOBAL,
        },
    )
    return result


def resolved_mirror_values(config: Any) -> MirrorValues:
    auto_enabled = bool(getattr(config, "mirror_auto_detect_china", True))
    use_china_defaults = auto_enabled and detect_china_network()
    region = REGION_CHINA if use_china_defaults else REGION_GLOBAL
    if not auto_enabled:
        region = REGION_GLOBAL

    huggingface = str(getattr(config, "huggingface_mirror_url", "") or "").strip()
    huggingface_cache_dir = str(getattr(config, "huggingface_cache_dir", "") or "")
    github = str(getattr(config, "github_mirror_url", "") or "").strip()
    pypi = str(getattr(config, "pypi_mirror_url", "") or "").strip()
    if use_china_defaults:
        huggingface = huggingface or DEFAULT_HUGGINGFACE_MIRROR_URL
        github = github or DEFAULT_GITHUB_MIRROR_URL
        pypi = pypi or DEFAULT_PYPI_MIRROR_URL
    huggingface_cache_dir = huggingface_cache_dir or DEFAULT_HUGGINGFACE_CACHE_DIR
    return MirrorValues(
        huggingface=huggingface,
        huggingface_cache_dir=huggingface_cache_dir,
        github=github,
        pypi=pypi,
        region=region,
    )


def system_config_payload_with_resolved_mirrors(config: Any) -> dict[str, Any]:
    dumper = getattr(config, "model_dump", None)
    if callable(dumper):
        payload = dumper(mode="json")
    elif isinstance(config, dict):
        payload = dict(config)
    else:
        payload = dict(getattr(config, "__dict__", {}))
    values = resolved_mirror_values(config)
    payload.update(
        {
            "mirror_region": values.region,
        }
    )
    return payload


def apply_mirror_environment(
    config: Any,
    *,
    root: str | Path | None = None,
) -> MirrorValues:
    values = resolved_mirror_values(config)
    detection_mode = "auto" if bool(getattr(config, "mirror_auto_detect_china", True)) else "manual"
    huggingface_source = _redact_url(values.huggingface or OFFICIAL_HUGGINGFACE_URL)
    github_source = _redact_url(values.github or OFFICIAL_GITHUB_URL)
    pypi_source = _redact_url(values.pypi or OFFICIAL_PYPI_INDEX_URL)
    _set_or_restore_env("HF_ENDPOINT", values.huggingface)
    _set_or_restore_env("HUGGINGFACE_HUB_ENDPOINT", values.huggingface)
    _set_or_restore_env("SHINSEKAI_HUGGINGFACE_MIRROR_URL", values.huggingface)
    cache_project_root = (
        project_root()
        if root is None
        else resolve_project_path(".", root=root)
    )
    hf_home_path = resolve_project_output_path(
        values.huggingface_cache_dir or DEFAULT_HUGGINGFACE_CACHE_DIR,
        root=cache_project_root,
    )
    hf_hub_cache_path = resolve_project_output_path(
        hf_home_path / "hub",
        root=cache_project_root,
    )
    transformers_cache_path = resolve_project_output_path(
        hf_home_path / "transformers",
        root=cache_project_root,
    )
    _ensure_cache_dirs(
        hf_home_path,
        hf_hub_cache_path,
        transformers_cache_path,
    )
    hf_home = hf_home_path.as_posix()
    hf_hub_cache = hf_hub_cache_path.as_posix()
    transformers_cache = transformers_cache_path.as_posix()
    _set_or_restore_env("HF_HOME", hf_home)
    _set_or_restore_env("HF_HUB_CACHE", hf_hub_cache)
    _set_or_restore_env("HUGGINGFACE_HUB_CACHE", hf_hub_cache)
    _set_or_restore_env("TRANSFORMERS_CACHE", transformers_cache)
    _set_or_restore_env("SHINSEKAI_HUGGINGFACE_CACHE_DIR", hf_home)
    _set_or_restore_env("GITHUB_MIRROR_URL", values.github)
    _set_or_restore_env("SHINSEKAI_GITHUB_MIRROR_URL", values.github)
    _set_or_restore_env("SHINSEKAI_PIP_INDEX_URL", values.pypi)
    _set_or_restore_env("SHINSEKAI_MIRROR_REGION", values.region)
    logger.info(
        "Mirror environment applied "
        "(region=%s, mode=%s, huggingface=%s, github=%s, pypi=%s)",
        values.region,
        detection_mode,
        huggingface_source,
        github_source,
        pypi_source,
        extra={
            "event": "mirror.env.applied",
            "region": values.region,
            "detection_mode": detection_mode,
            "huggingface_source": huggingface_source,
            "github_source": github_source,
            "pypi_source": pypi_source,
            "huggingface_mirror": _redact_url(values.huggingface),
            "huggingface_cache_dir": hf_home,
            "github_mirror": _redact_url(values.github),
            "pypi_index": _redact_url(values.pypi),
            "sets_standard_pip_env": False,
        },
    )
    return values


def apply_mirror_environment_from_system_config(
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
) -> MirrorValues:
    """Apply mirror env early without constructing the full ConfigManager."""
    config_project_root = (
        project_root()
        if root is None
        else resolve_project_path(".", root=root)
    )
    config_path = resolve_project_read_path(
        "data/config/system_config.yaml" if path is None else path,
        root=config_project_root,
    )
    try:
        import yaml
        from config.schema import SystemConfig

        raw = {}
        if config_path.is_file():
            loaded = yaml.safe_load(read_text_without_links(config_path))
            raw = loaded if isinstance(loaded, dict) else {}
        return apply_mirror_environment(
            SystemConfig.model_validate(raw),
            root=config_project_root,
        )
    except Exception as exc:
        logger.warning(
            "Falling back to default mirror configuration after config read failed: %s",
            exc,
            extra={"event": "mirror.env.fallback"},
        )
        return apply_mirror_environment(
            _FallbackMirrorConfig(),
            root=config_project_root,
        )


def mirror_github_url(url: str) -> str:
    mirror = os.environ.get("SHINSEKAI_GITHUB_MIRROR_URL", "").strip() or os.environ.get("GITHUB_MIRROR_URL", "").strip()
    if not mirror or "github.com/" not in url:
        return url
    if "{url}" in mirror:
        return mirror.replace("{url}", url)
    if "{path}" in mirror:
        return mirror.replace("{path}", url.split("github.com/", 1)[1])
    return f"{mirror.rstrip('/')}/{url}"


def _has_china_local_hint() -> bool:
    env_blob = " ".join(
        os.environ.get(name, "")
        for name in ("TZ", "LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE")
    ).lower()
    if any(marker in env_blob for marker in ("asia/shanghai", "zh_cn", "zh-hans")):
        return True
    try:
        loc = " ".join(part for part in locale.getlocale() if part).lower()
    except Exception:
        loc = ""
    return "zh_cn" in loc or "chinese" in loc


def _probe_china_network(*, timeout_sec: float) -> bool | None:
    baidu_ok = _probe_url("https://www.baidu.com", timeout_sec=timeout_sec)
    google_ok = _probe_url("https://www.google.com/generate_204", timeout_sec=timeout_sec)
    if baidu_ok is True and google_ok is False:
        return True
    if google_ok is True and baidu_ok is False:
        return False
    return None


def _detect_china_by_ip(*, timeout_sec: float) -> bool | None:
    for url in _ip_region_urls():
        country = _fetch_ip_country(url, timeout_sec=timeout_sec)
        if country:
            return country == "CN"
    return None


def _ip_region_urls() -> tuple[str, ...]:
    raw = os.environ.get(_IP_REGION_URLS_ENV, "")
    urls = tuple(part.strip() for part in raw.replace("\n", ",").split(",") if part.strip())
    return urls or _DEFAULT_IP_REGION_URLS


def _fetch_ip_country(url: str, *, timeout_sec: float) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Shinsekai/1.0 mirror-detect"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace").strip()
    except (OSError, urllib.error.URLError, UnicodeDecodeError):
        return None

    if not body:
        return None
    if body.startswith("{"):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            for key in ("country", "country_code", "countryCode"):
                value = data.get(key)
                country = _normalize_country_code(value)
                if country:
                    return country
        return None
    first = body.splitlines()[0].strip().strip('"')
    return _normalize_country_code(first)


def _normalize_country_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    country = value.strip().upper()
    if len(country) == 2 and country.isalpha():
        return country
    return None


def _probe_url(url: str, *, timeout_sec: float) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "Shinsekai/1.0 mirror-detect"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return 200 <= int(getattr(resp, "status", 200)) < 400
    except (OSError, urllib.error.URLError):
        return False


def _set_or_restore_env(name: str, value: str) -> None:
    if value:
        os.environ[name] = value
        return
    original = _ORIGINAL_ENV.get(name)
    if original is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = original


class _FallbackMirrorConfig:
    mirror_auto_detect_china = True
    huggingface_mirror_url = ""
    huggingface_cache_dir = ""
    github_mirror_url = ""
    pypi_mirror_url = ""


def _ensure_cache_dirs(*paths: Path) -> None:
    for path in paths:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not create HuggingFace cache directory %s: %s",
                path,
                exc,
                extra={"event": "mirror.cache.mkdir.failed", "path": str(path)},
            )
            continue
        # Do not downgrade an ownership/link violation to a warning. A path can
        # be replaced between output resolution and mkdir; exporting that alias
        # would let model downloads escape the selected project root.
        require_directory_without_links(
            path,
            field="HuggingFace cache directory",
        )


def _redact_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    return f"{scheme}{sep}***@{rest.rsplit('@', 1)[1]}"
