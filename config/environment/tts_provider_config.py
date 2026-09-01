from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

LEGACY_DEFAULT_TTS_SERVER_URL = "http://127.0.0.1:9880"
HTTPS_DEFAULT_TTS_SERVER_URL = "https://127.0.0.1:9880"
DEFAULT_TTS_SERVER_URL = LEGACY_DEFAULT_TTS_SERVER_URL
TTS_PROVIDER_DEFAULT_URLS = {
    "genie-tts": DEFAULT_TTS_SERVER_URL,
    "gpt-sovits": DEFAULT_TTS_SERVER_URL,
    "index-tts": LEGACY_DEFAULT_TTS_SERVER_URL,
}
BUILTIN_TTS_SERVER_URLS = {LEGACY_DEFAULT_TTS_SERVER_URL, HTTPS_DEFAULT_TTS_SERVER_URL, DEFAULT_TTS_SERVER_URL}
INSTALLED_TTS_BUNDLES_PATH = Path("data/tts_bundles/installed")
REMOTE_TTS_PROVIDERS = {"kaggle-gpt-sovits"}
LOCAL_SERVER_TTS_PROVIDERS = {"gpt-sovits", "genie-tts", "index-tts"}
SERVER_CONFIG_TTS_PROVIDERS = LOCAL_SERVER_TTS_PROVIDERS | REMOTE_TTS_PROVIDERS
TTS_PROVIDER_BUNDLE_KEYS: dict[str, tuple[str, ...]] = {
    "genie-tts": ("genie_tts_server",),
    "gpt-sovits": ("gpt_sovits_v2pro", "gpt_sovits_nvidia50"),
}


def normalize_tts_provider(value: str | None) -> str:
    raw = str(value or "").strip()
    low = raw.lower()
    if low in {"none", "off", "disable", "disabled", "不使用"}:
        return "none"
    legacy = {
        "genie tts": "genie-tts",
        "gpt sovits": "gpt-sovits",
        "gpt-sovits": "gpt-sovits",
        "kaggle": "kaggle-gpt-sovits",
        "kaggle gpt sovits": "kaggle-gpt-sovits",
        "kaggle gpt-sovits": "kaggle-gpt-sovits",
        "kaggle-gpt-sovits": "kaggle-gpt-sovits",
    }
    if low in legacy:
        return legacy[low]
    if not low:
        return "none"
    return low


def is_http_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def uses_shared_tts_server_config(provider: str | None) -> bool:
    return normalize_tts_provider(provider) in SERVER_CONFIG_TTS_PROVIDERS


def requires_tts_work_path(provider: str | None) -> bool:
    return normalize_tts_provider(provider) in LOCAL_SERVER_TTS_PROVIDERS


def default_tts_server_url(provider: str | None) -> str:
    return TTS_PROVIDER_DEFAULT_URLS.get(normalize_tts_provider(provider), "")


def tts_server_url_or_default(provider: str | None, current_url: str | None = "") -> str:
    clean_url = str(current_url or "").strip()
    default_url = default_tts_server_url(provider)
    if default_url and (not clean_url or clean_url in BUILTIN_TTS_SERVER_URLS):
        return default_url
    return clean_url


def _resolve_extracted_bundle_root(path: Path) -> Path:
    sub = [entry for entry in path.iterdir() if not entry.name.startswith(".")]
    if len(sub) == 1 and sub[0].is_dir():
        return sub[0]
    return path


def _is_valid_bundle_root(provider: str, path: Path) -> bool:
    if provider == "gpt-sovits":
        return (path / "api_v2.py").is_file()
    if provider == "genie-tts":
        return (path / "start.py").is_file() and (path / "runtime").is_dir()
    return False


def _installed_tts_bundle_root_for_key(
    provider: str,
    key: str,
    project_root: str | Path | None = None,
) -> Path | None:
    base = INSTALLED_TTS_BUNDLES_PATH
    bundle_dir = (Path(project_root) / base if project_root else base) / key
    try:
        if not bundle_dir.is_dir():
            return None
        root = _resolve_extracted_bundle_root(bundle_dir)
        if _is_valid_bundle_root(provider, root):
            return root.resolve()
    except OSError:
        return None
    return None


def installed_tts_bundle_paths(project_root: str | Path | None = None) -> dict[str, str]:
    paths: dict[str, str] = {}
    for provider, keys in TTS_PROVIDER_BUNDLE_KEYS.items():
        roots = [
            root
            for key in keys
            if (root := _installed_tts_bundle_root_for_key(provider, key, project_root)) is not None
        ]
        if roots:
            newest = max(roots, key=lambda root: root.stat().st_mtime)
            paths[provider] = newest.as_posix()
    return paths


def installed_tts_bundles_path(
    provider: str | None = None,
    project_root: str | Path | None = None,
) -> str:
    provider_key = normalize_tts_provider(provider)
    if not provider_key or provider_key == "none":
        return ""
    return installed_tts_bundle_paths(project_root).get(provider_key, "")


def default_tts_work_path(
    provider: str | None,
    current_path: str | None = "",
    project_root: str | Path | None = None,
) -> str:
    provider_key = normalize_tts_provider(provider)
    if provider_key == "kaggle-gpt-sovits":
        return ""
    clean_path = str(current_path or "").strip()
    if clean_path or not requires_tts_work_path(provider_key):
        return clean_path
    return installed_tts_bundles_path(provider_key, project_root)
