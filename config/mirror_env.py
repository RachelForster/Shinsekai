"""Mirror source resolution and environment variable application."""

from __future__ import annotations

import locale
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_HUGGINGFACE_MIRROR_URL = "https://hf-mirror.com"
DEFAULT_GITHUB_MIRROR_URL = "https://gh-proxy.com/"
DEFAULT_PYPI_MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple/"
DEFAULT_HUGGINGFACE_CACHE_DIR = "./data/cache/huggingface"
OFFICIAL_PYPI_INDEX_URL = "https://pypi.org/simple/"

REGION_AUTO = "auto"
REGION_CHINA = "china"
REGION_GLOBAL = "global"

_NETWORK_REGION_OVERRIDE_ENV = "SHINSEKAI_NETWORK_REGION"
_SKIP_PROBE_ENV = "SHINSEKAI_SKIP_NETWORK_REGION_PROBE"
_DETECT_CACHE_TTL_SEC = 600.0
_DETECT_CACHE: tuple[float, bool] | None = None

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

    local_hint = _has_china_local_hint()
    if local_hint:
        _DETECT_CACHE = (now, True)
        logger.info(
            "Mirror region detected from local environment hints",
            extra={"event": "mirror.region.detected", "source": "local_hint", "region": REGION_CHINA},
        )
        return True

    network_hint = None if os.environ.get(_SKIP_PROBE_ENV) else _probe_china_network(timeout_sec=timeout_sec)
    result = local_hint if network_hint is None else network_hint
    _DETECT_CACHE = (now, result)
    logger.info(
        "Mirror region detected from network probe",
        extra={
            "event": "mirror.region.detected",
            "source": "network_probe" if network_hint is not None else "fallback",
            "region": REGION_CHINA if result else REGION_GLOBAL,
            "network_hint": network_hint,
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
    huggingface_cache_dir = str(getattr(config, "huggingface_cache_dir", "") or "").strip()
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


def config_with_resolved_mirrors(config: Any) -> Any:
    values = resolved_mirror_values(config)
    updates = {
        "mirror_region": values.region,
        "huggingface_mirror_url": values.huggingface,
        "huggingface_cache_dir": values.huggingface_cache_dir,
        "github_mirror_url": values.github,
        "pypi_mirror_url": values.pypi,
    }
    copier = getattr(config, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    for key, value in updates.items():
        setattr(config, key, value)
    return config


def apply_mirror_environment(config: Any) -> MirrorValues:
    values = resolved_mirror_values(config)
    _set_or_restore_env("HF_ENDPOINT", values.huggingface)
    _set_or_restore_env("HUGGINGFACE_HUB_ENDPOINT", values.huggingface)
    _set_or_restore_env("SHINSEKAI_HUGGINGFACE_MIRROR_URL", values.huggingface)
    hf_home = _resolved_cache_path(values.huggingface_cache_dir)
    hf_hub_cache = (Path(hf_home) / "hub").as_posix()
    transformers_cache = (Path(hf_home) / "transformers").as_posix()
    _ensure_cache_dirs(hf_home, hf_hub_cache, transformers_cache)
    _set_or_restore_env("HF_HOME", hf_home)
    _set_or_restore_env("HF_HUB_CACHE", hf_hub_cache)
    _set_or_restore_env("HUGGINGFACE_HUB_CACHE", hf_hub_cache)
    _set_or_restore_env("TRANSFORMERS_CACHE", transformers_cache)
    _set_or_restore_env("SHINSEKAI_HUGGINGFACE_CACHE_DIR", hf_home)
    _set_or_restore_env("GITHUB_MIRROR_URL", values.github)
    _set_or_restore_env("SHINSEKAI_GITHUB_MIRROR_URL", values.github)
    _set_or_restore_env("SHINSEKAI_PIP_INDEX_URL", values.pypi)
    logger.info(
        "Mirror environment applied",
        extra={
            "event": "mirror.env.applied",
            "region": values.region,
            "huggingface_mirror": _redact_url(values.huggingface),
            "huggingface_cache_dir": hf_home,
            "github_mirror": _redact_url(values.github),
            "pypi_index": _redact_url(values.pypi),
            "sets_standard_pip_env": False,
        },
    )
    return values


def apply_mirror_environment_from_system_config(path: str | Path | None = None) -> MirrorValues:
    """Apply mirror env early without constructing the full ConfigManager."""
    try:
        import yaml
        from config.schema import SystemConfig

        config_path = Path(path or "data/config/system_config.yaml")
        raw = {}
        if config_path.is_file():
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw = loaded if isinstance(loaded, dict) else {}
        return apply_mirror_environment(SystemConfig.model_validate(raw))
    except Exception as exc:
        logger.warning(
            "Falling back to default mirror configuration after config read failed: %s",
            exc,
            extra={"event": "mirror.env.fallback"},
        )
        return apply_mirror_environment(_FallbackMirrorConfig())


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


def _resolved_cache_path(raw: str) -> str:
    path = Path(raw or DEFAULT_HUGGINGFACE_CACHE_DIR).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False).as_posix()


def _ensure_cache_dirs(*paths: str) -> None:
    for raw in paths:
        try:
            Path(raw).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not create HuggingFace cache directory %s: %s",
                raw,
                exc,
                extra={"event": "mirror.cache.mkdir.failed", "path": raw},
            )
            pass


def _redact_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    return f"{scheme}{sep}***@{rest.rsplit('@', 1)[1]}"
