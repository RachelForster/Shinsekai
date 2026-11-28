"""Resolve and validate GitHub Actions build matrix and release prefix for portable artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CATALOG: dict[str, dict[str, str]] = {
    "windows-x64": {
        "platform": "windows-x64",
        "os": "windows-latest",
        "tauri_bundles": "none",
        "default_models": "embedding,sherpa-asr,perception-gguf,qwen3-tts-gguf,pi-agent",
    },
    "windows-arm64": {
        "platform": "windows-arm64",
        "os": "windows-11-arm",
        "tauri_bundles": "none",
        "default_models": "embedding,perception-gguf,qwen3-tts-gguf,pi-agent",
    },
    "macos-arm64": {
        "platform": "macos-arm64",
        "os": "macos-15",
        "tauri_bundles": "app",
        "default_models": "embedding,sherpa-asr,perception-gguf,qwen3-tts-gguf,pi-agent",
    },
    "linux-x64": {
        "platform": "linux-x64",
        "os": "ubuntu-latest",
        "tauri_bundles": "none",
        "default_models": "embedding,sherpa-asr,perception-gguf,qwen3-tts-gguf,pi-agent",
    },
    "linux-arm64": {
        "platform": "linux-arm64",
        "os": "ubuntu-24.04-arm",
        "tauri_bundles": "none",
        "default_models": "embedding,sherpa-asr,perception-gguf,qwen3-tts-gguf,pi-agent",
    },
}

RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(-rc\.\d+)?$")
SEMVER_PREFIX_RE = re.compile(r"^(v\d+\.\d+\.\d+)(?:[-+].*)?$")
SAFE_TAG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _read_and_verify_version(source_root: Path) -> str:
    raw_version = (source_root / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
    clean_version = raw_version.removeprefix("v").removesuffix("-dev")
    pkg_version = json.loads((source_root / "frontend" / "package.json").read_text(encoding="utf-8"))["version"]
    if clean_version != pkg_version:
        raise ValueError(f"VERSION ({clean_version}) must match frontend/package.json ({pkg_version}).")
    return clean_version


def _validate_release_tag(ref_name: str, clean_version: str) -> str:
    if not RELEASE_TAG_RE.match(ref_name):
        raise ValueError(f"Invalid release tag '{ref_name}'; expected vX.Y.Z or vX.Y.Z-rc.N.")
    base_tag = re.sub(r"-rc\.\d+$", "", ref_name)
    expected_tag = f"v{clean_version}"
    if base_tag != expected_tag:
        raise ValueError(
            f"Release tag ({ref_name}) must match VERSION ({clean_version}); expected base tag {expected_tag}."
        )
    return ref_name


def _validate_custom_version_tag(version_tag: str, clean_version: str) -> str:
    if ".." in version_tag or not SAFE_TAG_RE.match(version_tag):
        raise ValueError(
            f"Unsafe version_tag '{version_tag}'; only alphanumeric, '.', '_', and '-' without '..' are allowed."
        )
    semver_match = SEMVER_PREFIX_RE.match(version_tag)
    if semver_match is not None:
        base_tag = semver_match.group(1)
        expected_tag = f"v{clean_version}"
        if base_tag != expected_tag:
            raise ValueError(
                f"Semver version_tag ({version_tag}) must match VERSION ({clean_version}); "
                f"expected prefix {expected_tag}."
            )
    return version_tag


def resolve_portable_plan(
    *,
    source_root: Path = REPO_ROOT,
    event_name: str,
    ref_name: str = "",
    github_ref: str = "",
    input_platforms: str = "all",
    input_models: str = "default",
    input_archive_format: str = "auto",
    input_version_tag: str = "",
    input_upload_huggingface: str = "true",
    input_upload_modelscope: str = "true",
) -> dict[str, str]:
    """Resolve validated CI matrix and release outputs for workflow_dispatch or tag push."""
    clean_version = _read_and_verify_version(source_root)
    is_dispatch = event_name == "workflow_dispatch"

    raw_platforms = (input_platforms or "all").strip() if is_dispatch else "all"
    if not raw_platforms or raw_platforms.lower() == "all":
        selected_names = list(CATALOG.keys())
    else:
        selected_names = []
        for part in raw_platforms.split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name not in CATALOG:
                raise ValueError(f"Unsupported platform '{name}'. Supported: {', '.join(CATALOG.keys())}")
            if name not in selected_names:
                selected_names.append(name)
    if not selected_names:
        raise ValueError("At least one platform must be selected.")

    models_mode = (input_models or "default").strip() if is_dispatch else "default"
    archive_format = (input_archive_format or "auto").strip() if is_dispatch else "auto"
    if archive_format not in {"auto", "zip", "tar.gz", "7z"}:
        raise ValueError(f"Unsupported archive format: {archive_format}")

    if is_dispatch:
        upload_hf = "true" if str(input_upload_huggingface or "true").lower() == "true" else "false"
        upload_ms = "true" if str(input_upload_modelscope or "true").lower() == "true" else "false"
        custom_tag = (input_version_tag or "").strip()
    else:
        upload_hf = "true"
        upload_ms = "true"
        custom_tag = ""

    if github_ref.startswith("refs/tags/"):
        tag_prefix = _validate_release_tag(ref_name, clean_version)
        release_prefix = _validate_custom_version_tag(custom_tag, clean_version) if custom_tag else tag_prefix
    elif custom_tag:
        release_prefix = _validate_custom_version_tag(custom_tag, clean_version)
    else:
        release_prefix = f"v{clean_version}"

    matrix = {"include": [CATALOG[name] for name in selected_names]}
    return {
        "version": clean_version,
        "release_prefix": release_prefix,
        "matrix": json.dumps(matrix, separators=(",", ":")),
        "platforms_csv": ",".join(selected_names),
        "models_mode": models_mode,
        "archive_format": archive_format,
        "upload_huggingface": upload_hf,
        "upload_modelscope": upload_ms,
    }


def main() -> int:
    outputs = resolve_portable_plan(
        source_root=REPO_ROOT,
        event_name=os.environ["EVENT_NAME"],
        ref_name=os.environ.get("REF_NAME", ""),
        github_ref=os.environ.get("GITHUB_REF", ""),
        input_platforms=os.environ.get("INPUT_PLATFORMS", "all"),
        input_models=os.environ.get("INPUT_MODELS", "default"),
        input_archive_format=os.environ.get("INPUT_ARCHIVE_FORMAT", "auto"),
        input_version_tag=os.environ.get("INPUT_VERSION_TAG", ""),
        input_upload_huggingface=os.environ.get("INPUT_UPLOAD_HF", "true"),
        input_upload_modelscope=os.environ.get("INPUT_UPLOAD_MS", "true"),
    )
    github_output = os.environ.get("GITHUB_OUTPUT", "").strip()
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            for key, value in outputs.items():
                fh.write(f"{key}={value}\n")
    else:
        print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
