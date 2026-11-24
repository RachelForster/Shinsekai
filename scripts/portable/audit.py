"""Sanitization and cross-platform integrity audit for Shinsekai portable bundles."""

from __future__ import annotations

from pathlib import Path
import re

import yaml

from ai.asr.sherpa_onnx_adapter import SHERPA_ZIPFORMER_ASSET
from ai.memory.config import EMBEDDING_MODEL_ASSET
from application.runtime.dependencies import (
    installed_versions_for_python,
    site_packages_dirs_for_python,
)
from config.models import ApiConfig, SystemConfig
from core.model_assets.service import ModelAssetSpec
from core.storage.layout import StorageLayout
from scripts.portable.models import (
    find_bundle_python,
    sprite_mouth_runtime_ready,
    toonout_runtime_ready,
)
from scripts.portable.targets import PlatformTarget

_SECRET_PATTERN = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{12,}|\bAIza[0-9A-Za-z_-]{20,}|\bhf_[A-Za-z0-9]{16,})"
)
_HARDCODED_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]+(?:Users|AI|conda|miniconda3|anaconda3)[\\/])",
    re.IGNORECASE,
)


def resolve_bundle_source_root(bundle_dir: Path) -> Path:
    """Return the app resources directory inside flat or macOS .app portable bundles."""
    app_resources = bundle_dir / "Shinsekai.app" / "Contents" / "Resources"
    if app_resources.is_dir():
        return app_resources
    return bundle_dir


def _verify_desktop_launcher(bundle_dir: Path, target: PlatformTarget | None) -> None:
    if target is not None:
        if target.uses_app_bundle and (bundle_dir / "Shinsekai.app").is_dir():
            launcher = bundle_dir / "Shinsekai.app" / "Contents" / "MacOS" / target.executable_name
            if not launcher.is_file():
                raise ValueError(f"Portable macOS bundle is missing executable: {launcher}")
            return
        launcher = bundle_dir / target.executable_name
        if not launcher.is_file():
            raise ValueError(f"Portable bundle is missing launcher executable: {launcher}")
        return

    candidates = (
        bundle_dir / "shinsekai.exe",
        bundle_dir / "shinsekai",
        bundle_dir / "Shinsekai.app" / "Contents" / "MacOS" / "shinsekai",
    )
    if not any(candidate.is_file() for candidate in candidates):
        raise ValueError("Portable bundle is missing desktop launcher executable")


def audit_portable_bundle(
    bundle_dir: Path,
    *,
    target: PlatformTarget | None = None,
    embedding_asset: ModelAssetSpec | None = None,
) -> None:
    """Verify the portable bundle has valid sanitized configs and zero personal/temp artifacts."""
    if not (bundle_dir / ".shinsekai-portable").is_file():
        raise ValueError("Portable bundle is missing .shinsekai-portable marker")

    _verify_desktop_launcher(bundle_dir, target)
    app_source_root = resolve_bundle_source_root(bundle_dir)
    if not (app_source_root / "frontend_bridge.py").is_file():
        raise ValueError(f"Portable bundle is missing frontend_bridge.py under {app_source_root}")
    if not (app_source_root / "frontend" / "dist" / "index.html").is_file():
        raise ValueError(f"Portable bundle is missing frontend/dist/index.html under {app_source_root}")

    layout = StorageLayout(bundle_dir)
    forbidden_paths = (
        layout.main_db_path,
        layout.config_file("sprite-mouth.json"),
        layout.model_dir("toonout") / "runtime.json",
        layout.model_dir("toonout") / "worker.log",
        layout.cache_dir / "huggingface" / "xet",
        layout.data_dir / "tts_bundles",
        layout.models_dir / "gpt-sovits",
    )
    for forbidden in forbidden_paths:
        if forbidden.exists():
            raise ValueError(f"Portable bundle contains forbidden path: {forbidden}")

    api_raw = yaml.safe_load(layout.config_file("api.yaml").read_text(encoding="utf-8"))
    system_raw = yaml.safe_load(layout.config_file("system_config.yaml").read_text(encoding="utf-8"))
    api_cfg = ApiConfig.model_validate(api_raw or {})
    SystemConfig.model_validate(system_raw or {})
    if api_cfg.llm_api_key:
        raise ValueError("Sanitized api.yaml must not contain llm_api_key entries")
    if api_cfg.hugging_face_access_token:
        raise ValueError("Sanitized api.yaml must not contain hugging_face_access_token")

    for config_file in layout.config_dir.rglob("*"):
        if not config_file.is_file():
            continue
        text = config_file.read_text(encoding="utf-8", errors="ignore")
        if _SECRET_PATTERN.search(text):
            raise ValueError(f"Detected secret-like token in {config_file}")
        if _HARDCODED_PATH_PATTERN.search(text):
            raise ValueError(f"Detected machine-specific path in {config_file}")

    toonout_dir = layout.model_dir("toonout")
    if toonout_dir.is_dir() and any(toonout_dir.iterdir()) and not toonout_runtime_ready(bundle_dir):
        raise ValueError("Portable bundle includes ToonOut assets without a runnable PyTorch environment")

    mouth_dir = layout.model_dir("sprite-mouth")
    if mouth_dir.is_dir() and any(mouth_dir.glob("*.safetensors")) and not sprite_mouth_runtime_ready(bundle_dir):
        raise ValueError("Portable bundle includes sprite-mouth weights without a runnable Python >=3.12 environment")

    gguf_dir = layout.model_dir("perception-gguf")
    if gguf_dir.is_dir() and any(gguf_dir.iterdir()):
        expected_llama = (
            (gguf_dir / "llama.cpp" / target.llama_executable,)
            if target is not None
            else (
                gguf_dir / "llama.cpp" / "llama-server.exe",
                gguf_dir / "llama.cpp" / "llama-server",
            )
        )
        if not any(candidate.is_file() for candidate in expected_llama):
            raise ValueError("Portable bundle includes perception-gguf without llama-server executable")

    resolved_embedding = embedding_asset or EMBEDDING_MODEL_ASSET
    bundle_py = find_bundle_python(bundle_dir)
    if bundle_py is not None and site_packages_dirs_for_python(bundle_py):
        versions = installed_versions_for_python(bundle_py)
        hub_dir = layout.cache_dir / "huggingface" / "hub"
        sherpa_repo = hub_dir / ("models--" + SHERPA_ZIPFORMER_ASSET.repo_id.replace("/", "--"))
        if sherpa_repo.is_dir() and "sherpa-onnx" not in versions:
            raise ValueError("Portable bundle includes sherpa-asr models but runtime is missing sherpa-onnx")
        embedding_repo = hub_dir / ("models--" + resolved_embedding.repo_id.replace("/", "--"))
        if embedding_repo.is_dir() and ("onnxruntime" not in versions or "huggingface-hub" not in versions):
            raise ValueError(
                "Portable bundle includes embedding model but runtime is missing onnxruntime or huggingface-hub"
            )
        if gguf_dir.is_dir() and "pillow" not in versions:
            raise ValueError("Portable bundle includes perception-gguf but runtime is missing Pillow")
