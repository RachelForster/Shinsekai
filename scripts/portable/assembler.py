"""Portable bundle assembly orchestrating app payload, templates, models, audit, and archive."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Mapping, Sequence

import yaml

from ai.asr.sherpa_onnx_adapter import SHERPA_SENSEVOICE_ASSET, SHERPA_ZIPFORMER_ASSET
from ai.memory.config import EMBEDDING_MODEL_ASSET
from application.model_assets.download_model import ModelAssetRequest, resolve_model_asset
from application.model_assets.registry import ASR_FASTER_WHISPER_ASSET_ID
from config.tts_provider_config import QWEN3_TTS_GGUF_DEFAULT_URL
from core.model_assets.service import ModelAssetSpec
from core.storage.layout import StorageLayout
from scripts.portable.archive import (
    cleanup_stale_bundle_artifacts,
    compress_bundle,
    compute_sha256,
    resolve_archive_format,
    write_bundle_metadata,
    write_sha256_file,
)
from scripts.portable.audit import audit_portable_bundle
from scripts.portable.gguf_runtime import (
    bundle_perception_gguf,
    bundle_qwen3_tts_gguf,
    copy_tree,
)
from scripts.portable.models import (
    bundle_huggingface_asset,
    bundle_sprite_mouth,
    bundle_toonout,
)
from scripts.portable.pi_bundle import bundle_pi_agent
from scripts.portable.targets import (
    DEFAULT_LLAMA_CPP_TAG,
    SUPPORTED_MODELS,
    PlatformTarget,
    infer_host_target,
    resolve_target,
)

APP_CODE_DIRS = (
    "ai",
    "application",
    "assets",
    "config",
    "core",
    "frontend_bridge_core",
    "i18n",
    "live",
    "plugin_system",
    "sdk",
    "tools",
)
APP_ROOT_FILES = (
    "VERSION",
    "main.py",
    "frontend_bridge.py",
    "requirements.txt",
    "requirements-runtime-core.txt",
    "requirements-runtime-local-ai.txt",
    "requirements-toonout.txt",
    "requirements-sprite-mouth.txt",
    "requirements-dev.txt",
)


@dataclass(frozen=True)
class BundleReport:
    """Result metadata returned after building and optionally archiving a portable bundle."""

    output_dir: Path
    archive_path: Path | None
    included_models: tuple[str, ...]
    warnings: tuple[str, ...]
    sha256_path: Path | None = None
    metadata_path: Path | None = None
    target: str = ""


def read_version(source_root: Path) -> str:
    """Read the semantic version string from `<source_root>/VERSION`."""
    version_file = source_root / "VERSION"
    if version_file.is_file():
        lines = version_file.read_text(encoding="utf-8").strip().splitlines()
        if lines and lines[0].strip():
            return lines[0].strip()
    return "0.0.0"


def _resolve_effective_target(
    target: str | PlatformTarget | None,
    release_dir: Path,
) -> tuple[PlatformTarget, bool]:
    if target is not None:
        return resolve_target(target), False
    try:
        host = resolve_target(infer_host_target())
    except ValueError:
        host = resolve_target("linux-x64")
    if (release_dir / host.executable_name).is_file() or (
        host.uses_app_bundle and (release_dir / "bundle" / "macos" / "Shinsekai.app").is_dir()
    ):
        return host, True
    if (release_dir / "shinsekai.exe").is_file():
        return resolve_target("windows-x64"), True
    return host, True


def _ensure_unix_executables(runtime_dir: Path) -> None:
    if os.name == "nt":
        return
    bin_dir = runtime_dir / "bin"
    if not bin_dir.is_dir():
        return
    for entry in bin_dir.iterdir():
        if entry.name.startswith("python") and entry.is_file() and not entry.is_symlink():
            entry.chmod(entry.stat().st_mode | 0o111)


def _resolve_runtime_source(
    source_root: Path,
    release_dir: Path,
    runtime_dir: Path | None,
) -> Path:
    if runtime_dir is not None:
        resolved = runtime_dir
    else:
        source_runtime = source_root / "runtime"
        resolved = source_runtime if source_runtime.is_dir() else (release_dir / "runtime")
    if not resolved.is_dir():
        raise FileNotFoundError(f"Missing bundled Python runtime: {resolved}")
    return resolved


def _resolve_frontend_dist(
    source_root: Path,
    release_dir: Path,
    frontend_dist_dir: Path | None,
) -> Path:
    if frontend_dist_dir is not None:
        resolved = frontend_dist_dir
    else:
        source_frontend = source_root / "frontend" / "dist"
        resolved = source_frontend if source_frontend.is_dir() else (release_dir / "frontend" / "dist")
    if not resolved.is_dir():
        raise FileNotFoundError(f"Missing built frontend assets: {resolved}")
    return resolved


def _copy_app_sources(
    *,
    source_root: Path,
    release_dir: Path,
    dest_root: Path,
    dereference: bool,
) -> None:
    runtime_manifest = release_dir / "runtime_manifest.json"
    if not runtime_manifest.is_file():
        runtime_manifest = source_root / "frontend" / "src-tauri" / "runtime_manifest.json"
    if runtime_manifest.is_file():
        shutil.copy2(runtime_manifest, dest_root / "runtime_manifest.json")

    for rel in APP_ROOT_FILES:
        src = source_root / rel
        if src.is_file():
            shutil.copy2(src, dest_root / rel)

    for rel in APP_CODE_DIRS:
        src = source_root / rel
        if src.is_dir():
            copy_tree(src, dest_root / rel, dereference=dereference)


def _copy_base_desktop_app(
    *,
    source_root: Path,
    release_dir: Path,
    output_dir: Path,
    target: PlatformTarget,
    runtime_dir: Path | None = None,
    frontend_dist_dir: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    app_bundle_src = release_dir / "bundle" / "macos" / "Shinsekai.app"

    if target.uses_app_bundle and app_bundle_src.is_dir():
        app_bundle_dst = output_dir / "Shinsekai.app"
        copy_tree(app_bundle_src, app_bundle_dst, dereference=False)
        macos_exe = app_bundle_dst / "Contents" / "MacOS" / target.executable_name
        if not macos_exe.is_file() and not macos_exe.is_symlink():
            raise FileNotFoundError(f"macOS .app bundle is missing executable: {macos_exe}")
        if os.name != "nt" and not macos_exe.is_symlink():
            macos_exe.chmod(macos_exe.stat().st_mode | 0o111)

        resources_dir = app_bundle_dst / "Contents" / "Resources"
        resources_dir.mkdir(parents=True, exist_ok=True)
        if runtime_dir is not None or not (resources_dir / "runtime").is_dir():
            resolved_runtime = _resolve_runtime_source(source_root, release_dir, runtime_dir)
            if (resources_dir / "runtime").exists():
                shutil.rmtree(resources_dir / "runtime")
            copy_tree(resolved_runtime, resources_dir / "runtime", dereference=False)
        _ensure_unix_executables(resources_dir / "runtime")

        if frontend_dist_dir is not None or not (resources_dir / "frontend" / "dist" / "index.html").is_file():
            resolved_frontend = _resolve_frontend_dist(source_root, release_dir, frontend_dist_dir)
            if (resources_dir / "frontend" / "dist").exists():
                shutil.rmtree(resources_dir / "frontend" / "dist")
            copy_tree(resolved_frontend, resources_dir / "frontend" / "dist", dereference=False)

        if not (resources_dir / "frontend_bridge.py").is_file():
            _copy_app_sources(
                source_root=source_root,
                release_dir=release_dir,
                dest_root=resources_dir,
                dereference=False,
            )
        return

    exe_path = release_dir / target.executable_name
    if not exe_path.is_file():
        raise FileNotFoundError(
            f"Missing built Tauri executable: {exe_path}. Run `pnpm tauri build --no-bundle` first."
        )

    dereference = target.os_family == "windows"
    resolved_runtime = _resolve_runtime_source(source_root, release_dir, runtime_dir)
    resolved_frontend = _resolve_frontend_dist(source_root, release_dir, frontend_dist_dir)

    dst_exe = output_dir / target.executable_name
    shutil.copy2(exe_path, dst_exe)
    if os.name != "nt":
        dst_exe.chmod(dst_exe.stat().st_mode | 0o111)

    copy_tree(resolved_runtime, output_dir / "runtime", dereference=dereference)
    _ensure_unix_executables(output_dir / "runtime")
    copy_tree(resolved_frontend, output_dir / "frontend" / "dist", dereference=dereference)
    _copy_app_sources(
        source_root=source_root,
        release_dir=release_dir,
        dest_root=output_dir,
        dereference=dereference,
    )


def _apply_portable_templates(*, source_root: Path, output_dir: Path) -> None:
    template_root = source_root / "scripts" / "portable_templates"
    if not template_root.is_dir():
        raise FileNotFoundError(f"Missing portable template directory: {template_root}")

    config_templates = template_root / "data" / "config"
    dst_config = StorageLayout(output_dir).config_dir
    copy_tree(config_templates, dst_config, dereference=True)

    readme_src = template_root / "使用说明.txt"
    if readme_src.is_file():
        shutil.copy2(readme_src, output_dir / "使用说明.txt")

    (output_dir / ".shinsekai-portable").write_text("portable=1\n", encoding="utf-8")

    layout = StorageLayout(output_dir)
    for rel in ("logs", "memory", "chat_history", "uploads", "plugins"):
        (layout.data_dir / rel).mkdir(parents=True, exist_ok=True)


def _asr_small_spec() -> ModelAssetSpec:
    return resolve_model_asset(ModelAssetRequest(asset_id=ASR_FASTER_WHISPER_ASSET_ID, variant="small"))


def _configure_bundled_qwen3_tts_defaults(output_dir: Path) -> None:
    api_path = StorageLayout(output_dir).config_file("api.yaml")
    raw = yaml.safe_load(api_path.read_text(encoding="utf-8")) or {}
    raw["tts_provider"] = "qwen3-tts-gguf"
    raw["gpt_sovits_url"] = QWEN3_TTS_GGUF_DEFAULT_URL
    raw["gpt_sovits_api_path"] = ""
    api_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def build_portable_bundle(
    *,
    source_root: Path,
    release_dir: Path,
    data_source_root: Path,
    output_dir: Path,
    target: str | PlatformTarget | None = None,
    runtime_dir: Path | None = None,
    frontend_dist_dir: Path | None = None,
    models: Sequence[str] | None = None,
    download_missing: bool = False,
    strict_models: bool = False,
    archive: bool = False,
    archive_format: str = "auto",
    write_sha256: bool = False,
    write_metadata: bool = False,
    llama_cpp_tag: str = DEFAULT_LLAMA_CPP_TAG,
    overwrite: bool = False,
    embedding_asset: ModelAssetSpec | None = None,
    toonout_artifacts: Mapping[str, tuple[str, str]] | None = None,
    mouth_model_files: Mapping[str, Mapping[str, object]] | None = None,
) -> BundleReport:
    """Assemble, validate, and optionally archive a cross-platform portable bundle."""
    resolved_target, compat_mode = _resolve_effective_target(target, release_dir)
    raw_models = resolved_target.default_models if models is None else models
    selected = tuple(dict.fromkeys(str(item).strip() for item in raw_models if str(item).strip()))
    unknown = set(selected) - SUPPORTED_MODELS
    if unknown:
        raise ValueError(f"Unsupported model bundle key(s): {', '.join(sorted(unknown))}")

    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {output_dir} (pass --overwrite to replace)")
        shutil.rmtree(output_dir)
    if overwrite:
        cleanup_stale_bundle_artifacts(output_dir)

    _copy_base_desktop_app(
        source_root=source_root,
        release_dir=release_dir,
        output_dir=output_dir,
        target=resolved_target,
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist_dir,
    )
    _apply_portable_templates(source_root=source_root, output_dir=output_dir)

    active_embedding = embedding_asset or EMBEDDING_MODEL_ASSET
    warnings: list[str] = []
    included: list[str] = []
    if "embedding" in selected and bundle_huggingface_asset(
        active_embedding,
        label="记忆向量模型",
        data_source_root=data_source_root,
        output_dir=output_dir,
        download_missing=download_missing,
        warnings=warnings,
    ):
        included.append("embedding")
    if "sherpa-asr" in selected:
        zipformer_ok = bundle_huggingface_asset(
            SHERPA_ZIPFORMER_ASSET,
            label="Sherpa 流式 Zipformer 模型",
            data_source_root=data_source_root,
            output_dir=output_dir,
            download_missing=download_missing,
            warnings=warnings,
        )
        sensevoice_ok = bundle_huggingface_asset(
            SHERPA_SENSEVOICE_ASSET,
            label="Sherpa SenseVoiceSmall 模型",
            data_source_root=data_source_root,
            output_dir=output_dir,
            download_missing=download_missing,
            warnings=warnings,
        )
        if zipformer_ok and sensevoice_ok:
            included.append("sherpa-asr")
    if "asr-small" in selected and bundle_huggingface_asset(
        _asr_small_spec(),
        label="ASR faster-whisper-small 模型",
        data_source_root=data_source_root,
        output_dir=output_dir,
        download_missing=download_missing,
        warnings=warnings,
    ):
        included.append("asr-small")
    if "perception-gguf" in selected and bundle_perception_gguf(
        target=resolved_target,
        data_source_root=data_source_root,
        output_dir=output_dir,
        download_missing=download_missing,
        llama_cpp_tag=llama_cpp_tag,
        allow_host_llama_fallback=compat_mode,
        warnings=warnings,
    ):
        included.append("perception-gguf")
    if "qwen3-tts-gguf" in selected and bundle_qwen3_tts_gguf(
        target=resolved_target,
        data_source_root=data_source_root,
        output_dir=output_dir,
        download_missing=download_missing,
        llama_cpp_tag=llama_cpp_tag,
        allow_host_llama_fallback=compat_mode,
        warnings=warnings,
    ):
        included.append("qwen3-tts-gguf")
    if "pi-agent" in selected and bundle_pi_agent(
        target=resolved_target,
        data_source_root=data_source_root,
        output_dir=output_dir,
        download_missing=download_missing,
        warnings=warnings,
    ):
        included.append("pi-agent")
    if "toonout" in selected and bundle_toonout(
        data_source_root=data_source_root,
        output_dir=output_dir,
        warnings=warnings,
        artifacts=toonout_artifacts,
    ):
        included.append("toonout")
    if "sprite-mouth" in selected and bundle_sprite_mouth(
        data_source_root=data_source_root,
        output_dir=output_dir,
        warnings=warnings,
        model_files=mouth_model_files,
    ):
        included.append("sprite-mouth")

    if strict_models:
        missing = [item for item in selected if item not in included]
        if missing:
            detail = f" (warnings: {' | '.join(warnings)})" if warnings else ""
            raise RuntimeError(f"Failed to include required portable model(s): {', '.join(missing)}{detail}")

    if "qwen3-tts-gguf" in included:
        _configure_bundled_qwen3_tts_defaults(output_dir)

    audit_portable_bundle(
        output_dir,
        target=None if compat_mode else resolved_target,
        embedding_asset=active_embedding,
    )

    archive_path: Path | None = None
    sha256_path: Path | None = None
    metadata_path: Path | None = None
    if archive:
        resolved_fmt = resolve_archive_format(archive_format, source_root=source_root, target=resolved_target)
        archive_path = compress_bundle(
            source_root,
            output_dir,
            target=resolved_target,
            archive_format=resolved_fmt,
        )
        digest: str | None = None
        if write_sha256 or write_metadata:
            digest = compute_sha256(archive_path)
        if write_sha256:
            sha256_path, digest = write_sha256_file(archive_path, digest=digest)
        else:
            archive_path.with_name(f"{archive_path.name}.sha256").unlink(missing_ok=True)
        if write_metadata and digest is not None:
            metadata_path = write_bundle_metadata(
                archive_path,
                version=read_version(source_root),
                target=resolved_target,
                sha256=digest,
                included_models=included,
                archive_format=resolved_fmt,
                llama_cpp_tag=llama_cpp_tag,
            )
        else:
            archive_path.with_name(f"{archive_path.name}.meta.json").unlink(missing_ok=True)

    return BundleReport(
        output_dir=output_dir,
        archive_path=archive_path,
        included_models=tuple(included),
        warnings=tuple(warnings),
        sha256_path=sha256_path,
        metadata_path=metadata_path,
        target=resolved_target.name,
    )
