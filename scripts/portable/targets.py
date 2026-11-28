"""Target platform definitions and defaults for Shinsekai portable bundles."""

from __future__ import annotations

from dataclasses import dataclass
import platform
import sys

DEFAULT_MODELS = ("embedding", "sherpa-asr", "perception-gguf", "qwen3-tts-gguf", "pi-agent")
SUPPORTED_MODELS = frozenset((*DEFAULT_MODELS, "asr-small", "toonout", "sprite-mouth"))

DEFAULT_LLAMA_CPP_TAG = "b12669"
PERCEPTION_GGUF_REPO_ID = "Qwen/Qwen3-VL-2B-Instruct-GGUF"
PERCEPTION_GGUF_FILES = (
    "Qwen3VL-2B-Instruct-Q4_K_M.gguf",
    "mmproj-Qwen3VL-2B-Instruct-F16.gguf",
)
QWEN3_TTS_GGUF_REPO_ID = "mradermacher/Qwen3-TTS-12Hz-0.6B-Base-GGUF"
QWEN3_TTS_GGUF_FILES = (
    "Qwen3-TTS-12Hz-0.6B-Base.Q8_0.gguf",
    "Qwen3-TTS-12Hz-0.6B-Base.mmproj-f16.gguf",
)


@dataclass(frozen=True)
class PlatformTarget:
    """Metadata describing how to assemble and package a portable bundle for one target."""

    name: str
    os_family: str
    arch: str
    pi_platform_key: str
    executable_name: str
    llama_executable: str
    llama_asset_candidates: tuple[str, ...]
    default_archive_format: str
    default_models: tuple[str, ...]
    uses_app_bundle: bool = False


PLATFORM_TARGETS: dict[str, PlatformTarget] = {
    "windows-x64": PlatformTarget(
        name="windows-x64",
        os_family="windows",
        arch="x64",
        pi_platform_key="windows-x64",
        executable_name="shinsekai.exe",
        llama_executable="llama-server.exe",
        llama_asset_candidates=(
            "llama-{tag}-bin-win-vulkan-x64.zip",
            "llama-{tag}-bin-win-cpu-x64.zip",
        ),
        default_archive_format="zip",
        default_models=DEFAULT_MODELS,
        uses_app_bundle=False,
    ),
    "windows-arm64": PlatformTarget(
        name="windows-arm64",
        os_family="windows",
        arch="arm64",
        pi_platform_key="windows-arm64",
        executable_name="shinsekai.exe",
        llama_executable="llama-server.exe",
        llama_asset_candidates=(
            "llama-{tag}-bin-win-vulkan-arm64.zip",
            "llama-{tag}-bin-win-cpu-arm64.zip",
        ),
        default_archive_format="zip",
        # requirements-runtime-core.txt skips sherpa-onnx on Windows ARM64.
        default_models=("embedding", "perception-gguf", "qwen3-tts-gguf", "pi-agent"),
        uses_app_bundle=False,
    ),
    "macos-arm64": PlatformTarget(
        name="macos-arm64",
        os_family="macos",
        arch="arm64",
        pi_platform_key="darwin-arm64",
        executable_name="shinsekai",
        llama_executable="llama-server",
        llama_asset_candidates=("llama-{tag}-bin-macos-arm64.tar.gz",),
        default_archive_format="tar.gz",
        default_models=DEFAULT_MODELS,
        uses_app_bundle=True,
    ),
    "linux-x64": PlatformTarget(
        name="linux-x64",
        os_family="linux",
        arch="x64",
        pi_platform_key="linux-x64",
        executable_name="shinsekai",
        llama_executable="llama-server",
        llama_asset_candidates=("llama-{tag}-bin-ubuntu-x64.tar.gz",),
        default_archive_format="tar.gz",
        default_models=DEFAULT_MODELS,
        uses_app_bundle=False,
    ),
    "linux-arm64": PlatformTarget(
        name="linux-arm64",
        os_family="linux",
        arch="arm64",
        pi_platform_key="linux-arm64",
        executable_name="shinsekai",
        llama_executable="llama-server",
        llama_asset_candidates=("llama-{tag}-bin-ubuntu-arm64.tar.gz",),
        default_archive_format="tar.gz",
        default_models=DEFAULT_MODELS,
        uses_app_bundle=False,
    ),
}

SUPPORTED_TARGETS: tuple[str, ...] = tuple(PLATFORM_TARGETS.keys())

TARGET_ALIASES: dict[str, str] = {
    "win-x64": "windows-x64",
    "win-arm64": "windows-arm64",
    "darwin-arm64": "macos-arm64",
}


def infer_host_target() -> str:
    """Infer the canonical target identifier for the current Python host."""
    if sys.platform.startswith("win"):
        os_family = "windows"
    elif sys.platform == "darwin":
        os_family = "macos"
    elif sys.platform.startswith("linux"):
        os_family = "linux"
    else:
        raise ValueError(f"Unsupported host OS for portable bundle: {sys.platform}")

    machine = platform.machine().strip().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        raise ValueError(f"Unsupported host architecture for portable bundle: {machine}")

    target_name = f"{os_family}-{arch}"
    if target_name not in PLATFORM_TARGETS:
        raise ValueError(f"Unsupported portable bundle target: {target_name}")
    return target_name


def resolve_target(target: str | PlatformTarget | None = None) -> PlatformTarget:
    """Resolve a target name, alias, or PlatformTarget instance into a PlatformTarget."""
    if isinstance(target, PlatformTarget):
        return target
    raw = str(target or "").strip().lower()
    if not raw:
        raw = infer_host_target()
    canonical = TARGET_ALIASES.get(raw, raw)
    resolved = PLATFORM_TARGETS.get(canonical)
    if resolved is None:
        supported = ", ".join(SUPPORTED_TARGETS)
        raise ValueError(f"Unsupported portable target '{target}'. Supported targets: {supported}")
    return resolved


def default_models_for_target(target: str | PlatformTarget | None = None) -> tuple[str, ...]:
    """Return the default model pack tuple for the given target."""
    return resolve_target(target).default_models


def default_bundle_dirname(version: str, target: PlatformTarget) -> str:
    """Build the canonical directory and archive stem name for a portable bundle."""
    clean_version = str(version or "0.0.0").strip() or "0.0.0"
    return f"Shinsekai-Portable-v{clean_version}-{target.name}"
