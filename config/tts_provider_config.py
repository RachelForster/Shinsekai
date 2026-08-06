from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sdk.file_transactions import (
    file_snapshot_is_stable,
    inspect_portable_directory_tree_with_metadata,
)
from sdk.path_contract import (
    managed_project_directory,
    managed_project_storage,
    path_is_within,
    project_root as configured_project_root,
    resolve_project_path,
)

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


@dataclass(frozen=True)
class _InstalledBundleSnapshot:
    path: Path
    identity: os.stat_result


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


def _inspect_installed_bundle(
    provider: str,
    path: Path,
) -> _InstalledBundleSnapshot | None:
    root_identity, directories, files = (
        inspect_portable_directory_tree_with_metadata(path)
    )
    directory_identities = dict(directories)
    file_identities = dict(files)
    visible_top_level = [
        entry
        for entry in (*directory_identities, *file_identities)
        if len(entry.parts) == 1 and not entry.name.startswith(".")
    ]
    relative_root = Path()
    bundle_identity = root_identity
    if (
        len(visible_top_level) == 1
        and visible_top_level[0] in directory_identities
    ):
        relative_root = visible_top_level[0]
        bundle_identity = directory_identities[relative_root]

    required_file: Path | None = None
    required_directory: Path | None = None
    if provider == "gpt-sovits":
        required_file = relative_root / "api_v2.py"
    elif provider == "genie-tts":
        required_file = relative_root / "start.py"
        required_directory = relative_root / "runtime"
    if (
        required_file is None
        or required_file not in file_identities
        or (
            required_directory is not None
            and required_directory not in directory_identities
        )
    ):
        return None

    bundle_root = path / relative_root
    current_identity = bundle_root.lstat()
    if not file_snapshot_is_stable(bundle_identity, current_identity):
        raise PermissionError(
            f"installed TTS bundle identity changed: {bundle_root}"
        )
    return _InstalledBundleSnapshot(
        path=bundle_root,
        identity=bundle_identity,
    )


def _installed_tts_bundle_root_for_key(
    provider: str,
    key: str,
    project_root: str | Path | None = None,
) -> _InstalledBundleSnapshot | None:
    root = (
        resolve_project_path(".", root=project_root)
        if project_root is not None
        else configured_project_root()
    )
    try:
        base = managed_project_storage(INSTALLED_TTS_BUNDLES_PATH, root=root)
    except OSError:
        return None
    try:
        bundle_dir = managed_project_directory(
            INSTALLED_TTS_BUNDLES_PATH,
            key,
            root=root,
        )
        bundle_snapshot = _inspect_installed_bundle(provider, bundle_dir)
        if bundle_snapshot is None:
            return None
        bundle_root = bundle_snapshot.path
        if not path_is_within(bundle_dir, base):
            return None
        if not path_is_within(bundle_root, bundle_dir):
            return None
        current_identity = bundle_root.lstat()
        if not file_snapshot_is_stable(
            bundle_snapshot.identity,
            current_identity,
        ):
            raise PermissionError(
                f"installed TTS bundle identity changed: {bundle_root}"
            )
        return bundle_snapshot
    except (OSError, PermissionError, ValueError):
        return None
    return None


def installed_tts_bundle_paths(project_root: str | Path | None = None) -> dict[str, str]:
    paths: dict[str, str] = {}
    for provider, keys in TTS_PROVIDER_BUNDLE_KEYS.items():
        snapshots = [
            snapshot
            for key in keys
            if (
                snapshot := _installed_tts_bundle_root_for_key(
                    provider,
                    key,
                    project_root,
                )
            )
            is not None
        ]
        if snapshots:
            newest = max(
                snapshots,
                key=lambda snapshot: snapshot.identity.st_mtime_ns,
            )
            try:
                current_identity = newest.path.lstat()
            except FileNotFoundError:
                continue
            if file_snapshot_is_stable(
                newest.identity,
                current_identity,
            ):
                paths[provider] = newest.path.as_posix()
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
    raw_path = str(current_path or "")
    if raw_path and (
        raw_path != raw_path.strip()
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in raw_path
        )
    ):
        raise ValueError("TTS work path contains non-portable characters")
    if raw_path or not requires_tts_work_path(provider_key):
        return raw_path
    return installed_tts_bundles_path(provider_key, project_root)
