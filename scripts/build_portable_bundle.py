"""Build a clean, sanitized, zero-setup Windows portable bundle for Shinsekai."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Apply mirror env BEFORE importing huggingface_hub (which reads HF_ENDPOINT at import time).
from config.mirror_env import apply_mirror_environment_from_system_config as _init_mirror_env

_init_mirror_env(REPO_ROOT / "data" / "config" / "system_config.yaml")

import yaml

from ai.asr.sherpa_onnx_adapter import SHERPA_SENSEVOICE_ASSET, SHERPA_ZIPFORMER_ASSET
from ai.memory.config import EMBEDDING_MODEL_ASSET
from application.characters.sprite import mouth_resources
from application.characters.sprite.mouth_resources import MODEL_FILES as MOUTH_MODEL_FILES, verify_weight
from application.model_assets.download_model import ModelAssetRequest, resolve_model_asset
from application.model_assets.registry import ASR_FASTER_WHISPER_ASSET_ID
from application.perception.server_launcher import _gguf_candidate_dirs
from application.runtime.dependencies import (
    installed_versions_for_python,
    site_packages_dirs_for_python,
)
from config.models import ApiConfig, SystemConfig
from core.media.toonout_assets import ARTIFACTS as TOONOUT_ARTIFACTS, verify_assets
from core.model_assets.service import ModelAssetSpec, find_cached_huggingface_snapshot
from core.storage.layout import StorageLayout

DEFAULT_MODELS = ("embedding", "sherpa-asr", "perception-gguf")
SUPPORTED_MODELS = frozenset((*DEFAULT_MODELS, "asr-small", "toonout", "sprite-mouth"))

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
IGNORED_DIR_NAMES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".git"})
IGNORED_FILE_SUFFIXES = (".pyc", ".pyo", ".pdb", ".d", ".rlib")

_SECRET_PATTERN = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{12,}|\bAIza[0-9A-Za-z_-]{20,}|\bhf_[A-Za-z0-9]{16,})"
)
_HARDCODED_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]+(?:Users|AI|conda|miniconda3|anaconda3)[\\/])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BundleReport:
    output_dir: Path
    archive_path: Path | None
    included_models: tuple[str, ...]
    warnings: tuple[str, ...]


def _ignore_copy_entries(_directory: str, entries: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in entries:
        if name in IGNORED_DIR_NAMES or name.endswith(IGNORED_FILE_SUFFIXES):
            ignored.add(name)
    return ignored


def _copy_tree(src: Path, dst: Path, *, dereference: bool = True) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {src}")
    shutil.copytree(
        src,
        dst,
        symlinks=not dereference,
        ignore=_ignore_copy_entries,
        dirs_exist_ok=True,
    )


def _read_version(source_root: Path) -> str:
    version_file = source_root / "VERSION"
    if version_file.is_file():
        text = version_file.read_text(encoding="utf-8").strip().splitlines()
        if text and text[0].strip():
            return text[0].strip()
    return "0.0.0"


def _copy_base_desktop_app(
    *,
    source_root: Path,
    release_dir: Path,
    output_dir: Path,
    runtime_dir: Path | None = None,
    frontend_dist_dir: Path | None = None,
) -> None:
    exe_path = release_dir / "shinsekai.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(
            f"Missing built Tauri executable: {exe_path}. Run `pnpm tauri build --no-bundle` first."
        )

    resolved_runtime = runtime_dir
    if resolved_runtime is None:
        source_runtime = source_root / "runtime"
        resolved_runtime = source_runtime if source_runtime.is_dir() else (release_dir / "runtime")
    if not resolved_runtime.is_dir():
        raise FileNotFoundError(f"Missing bundled Python runtime: {resolved_runtime}")

    resolved_frontend = frontend_dist_dir
    if resolved_frontend is None:
        source_frontend = source_root / "frontend" / "dist"
        resolved_frontend = source_frontend if source_frontend.is_dir() else (release_dir / "frontend" / "dist")
    if not resolved_frontend.is_dir():
        raise FileNotFoundError(f"Missing built frontend assets: {resolved_frontend}")

    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe_path, output_dir / "shinsekai.exe")
    _copy_tree(resolved_runtime, output_dir / "runtime", dereference=True)

    runtime_manifest = release_dir / "runtime_manifest.json"
    if runtime_manifest.is_file():
        shutil.copy2(runtime_manifest, output_dir / "runtime_manifest.json")

    _copy_tree(resolved_frontend, output_dir / "frontend" / "dist", dereference=True)

    for rel in APP_ROOT_FILES:
        src = source_root / rel
        if src.is_file():
            shutil.copy2(src, output_dir / rel)

    for rel in APP_CODE_DIRS:
        src = source_root / rel
        if src.is_dir():
            _copy_tree(src, output_dir / rel, dereference=True)


def _materialize_hf_repo_snapshot(
    *,
    snapshot_dir: Path,
    repo_id: str,
    target_hub_dir: Path,
    revision_ref: str = "main",
) -> Path:
    """Copy a complete HF snapshot into target_hub_dir with regular files (no symlinks/blobs/xet)."""
    repo_folder = "models--" + repo_id.replace("/", "--")
    dst_repo = target_hub_dir / repo_folder
    revision = snapshot_dir.name
    dst_snapshot = dst_repo / "snapshots" / revision
    _copy_tree(snapshot_dir, dst_snapshot, dereference=True)

    refs_dir = dst_repo / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / revision_ref).write_text(revision, encoding="utf-8")

    manifest_src = snapshot_dir.parent.parent / ".shinsekai_manifests" / f"{revision}.json"
    if manifest_src.is_file():
        manifest_dst = dst_repo / ".shinsekai_manifests" / f"{revision}.json"
        manifest_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_src, manifest_dst)
    return dst_snapshot


def _find_hf_snapshot(spec: ModelAssetSpec, data_source_root: Path) -> Path | None:
    candidates = [
        StorageLayout(data_source_root).cache_dir / "huggingface" / "hub",
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    old_env = {k: os.environ.get(k) for k in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME")}
    try:
        for hub_dir in candidates:
            if not hub_dir.is_dir():
                continue
            os.environ["HF_HUB_CACHE"] = str(hub_dir)
            os.environ["HUGGINGFACE_HUB_CACHE"] = str(hub_dir)
            os.environ.pop("HF_HOME", None)
            snapshot = find_cached_huggingface_snapshot(spec)
            if snapshot is not None:
                return snapshot
    finally:
        for key, val in old_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
    return None


def _bundle_huggingface_asset(
    spec: ModelAssetSpec,
    *,
    label: str,
    data_source_root: Path,
    output_dir: Path,
    download_missing: bool,
    warnings: list[str],
) -> bool:
    target_hf_home = (StorageLayout(output_dir).cache_dir / "huggingface").resolve()
    target_hub = (target_hf_home / "hub").resolve()
    target_hub.mkdir(parents=True, exist_ok=True)

    snapshot = _find_hf_snapshot(spec, data_source_root)
    if snapshot is None and download_missing:
        from config.mirror_env import apply_mirror_environment_from_system_config
        from core.model_assets.service import download_model_asset

        old_env = {
            k: os.environ.get(k)
            for k in ("HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE")
        }
        try:
            apply_mirror_environment_from_system_config(data_source_root / "data" / "config" / "system_config.yaml")
            os.environ["HF_HOME"] = str(target_hf_home)
            os.environ["HF_HUB_CACHE"] = str(target_hub)
            os.environ["HUGGINGFACE_HUB_CACHE"] = str(target_hub)
            os.environ["TRANSFORMERS_CACHE"] = str(target_hf_home / "transformers")
            try:
                download_model_asset(spec, update_task=lambda **_: None)
            except Exception:
                from ai.asr.sherpa_onnx_adapter import _download_snapshot_via_direct_http

                _download_snapshot_via_direct_http(spec)
            snapshot = find_cached_huggingface_snapshot(spec)
        finally:
            for key, val in old_env.items():
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val
        # Clean up any temporary xet/transformers caches left by download
        for temp_name in ("xet", "transformers"):
            temp_dir = target_hf_home / temp_name
            if temp_dir.is_dir():
                shutil.rmtree(temp_dir, ignore_errors=True)

    if snapshot is None:
        warnings.append(
            f"未找到本地缓存的{label}（{spec.repo_id}）；"
            "可追加 --download-missing 自动下载并打入便携包。"
        )
        return False

    # If downloaded directly into output_dir, ensure snapshot files are materialized and blobs/locks removed
    repo_folder = "models--" + spec.repo_id.replace("/", "--")
    if snapshot.is_relative_to(target_hub):
        staged_tmp = target_hub / f".staging-{repo_folder}"
        if staged_tmp.exists():
            shutil.rmtree(staged_tmp)
        _copy_tree(snapshot, staged_tmp, dereference=True)
        shutil.rmtree(snapshot)
        shutil.move(str(staged_tmp), str(snapshot))
        for removable in (target_hub / repo_folder / "blobs", target_hub / ".locks"):
            if removable.is_dir():
                shutil.rmtree(removable, ignore_errors=True)
    else:
        _materialize_hf_repo_snapshot(
            snapshot_dir=snapshot,
            repo_id=spec.repo_id,
            target_hub_dir=target_hub,
            revision_ref=spec.revision or "main",
        )
    return True


def _asr_small_spec() -> ModelAssetSpec:
    return resolve_model_asset(ModelAssetRequest(asset_id=ASR_FASTER_WHISPER_ASSET_ID, variant="small"))


def _bundle_perception_gguf(
    *,
    data_source_root: Path,
    output_dir: Path,
    warnings: list[str],
) -> bool:
    executable = "llama-server.exe" if os.name == "nt" else "llama-server"
    required = (
        Path("llama.cpp") / executable,
        Path("Qwen3VL-2B-Instruct-Q4_K_M.gguf"),
        Path("mmproj-Qwen3VL-2B-Instruct-F16.gguf"),
    )
    src_dir: Path | None = None
    for candidate in _gguf_candidate_dirs(data_source_root):
        if all((candidate / rel).is_file() for rel in required):
            src_dir = candidate
            break
    if src_dir is None:
        warnings.append("未找到完整的 perception-gguf 模型与 llama.cpp，已跳过。")
        return False

    dst_dir = StorageLayout(output_dir).model_dir("perception-gguf")
    _copy_tree(src_dir, dst_dir, dereference=True)
    return True


def _python_in_runtime_dir(runtime_dir: Path) -> Path | None:
    for rel in ("python.exe", "Scripts/python.exe", "bin/python3", "bin/python"):
        candidate = runtime_dir / rel
        if candidate.is_file():
            return candidate
    return None


def _toonout_runtime_ready(bundle_dir: Path) -> bool:
    layout = StorageLayout(bundle_dir)
    py = _python_in_runtime_dir(layout.runtime_subdir("toonout")) or _python_in_runtime_dir(
        bundle_dir / "runtime"
    )
    if py is None or not site_packages_dirs_for_python(py):
        return False
    versions = installed_versions_for_python(py)
    if not all(pkg in versions for pkg in ("torch", "torchvision", "transformers", "pillow")):
        return False
    deps_dir = layout.model_dir("toonout") / "deps"
    for extra in ("timm", "kornia", "einops"):
        if extra in versions:
            continue
        if (deps_dir / extra).is_dir() or (deps_dir / f"{extra}.py").is_file():
            continue
        return False
    return True


def _sprite_mouth_runtime_ready(bundle_dir: Path) -> bool:
    layout = StorageLayout(bundle_dir)
    packages_dir = layout.runtime_subdir("sprite-mouth") / "packages"
    candidates = (
        layout.runtime_subdir("sprite-mouth") / "python" / "python.exe",
        layout.runtime_subdir("sprite-mouth") / "python" / "bin" / "python3",
        bundle_dir / "runtime" / "python.exe",
        bundle_dir / "runtime" / "bin" / "python3",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        probe = mouth_resources._probe(
            str(candidate),
            str(packages_dir),
            candidate.stat().st_mtime_ns,
        )
        version = probe.get("version", [])
        if tuple(version[:2]) >= (3, 12) and not probe.get("missing"):
            return True
    return False


def _bundle_toonout(
    *,
    data_source_root: Path,
    output_dir: Path,
    warnings: list[str],
) -> bool:
    candidates = (
        StorageLayout(data_source_root).model_dir("toonout"),
        data_source_root / "cache" / "models" / "toonout",
    )
    src_dir = next(
        (
            candidate
            for candidate in candidates
            if all((candidate / name).is_file() for name in TOONOUT_ARTIFACTS)
        ),
        None,
    )
    if src_dir is None:
        warnings.append("未找到完整的 ToonOut 模型文件，已跳过。")
        return False

    src_runtime = StorageLayout(data_source_root).runtime_subdir("toonout")
    dst_runtime = StorageLayout(output_dir).runtime_subdir("toonout")
    copied_runtime = False
    if src_runtime.is_dir():
        _copy_tree(src_runtime, dst_runtime, dereference=True)
        copied_runtime = True

    dst_dir = StorageLayout(output_dir).model_dir("toonout")
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in TOONOUT_ARTIFACTS:
        shutil.copy2(src_dir / name, dst_dir / name)
    deps_dir = src_dir / "deps"
    if deps_dir.is_dir():
        _copy_tree(deps_dir, dst_dir / "deps", dereference=True)
    verify_assets(dst_dir)

    if not _toonout_runtime_ready(output_dir):
        shutil.rmtree(dst_dir, ignore_errors=True)
        if copied_runtime:
            shutil.rmtree(dst_runtime, ignore_errors=True)
        warnings.append(
            "随包运行环境不含 ToonOut 所需的 PyTorch 依赖（未提供可运行的 data/runtime/toonout），已跳过。"
        )
        return False
    return True


def _bundle_sprite_mouth(
    *,
    data_source_root: Path,
    output_dir: Path,
    warnings: list[str],
) -> bool:
    src_models = StorageLayout(data_source_root).model_dir("sprite-mouth")
    if not all(verify_weight(src_models / f"{key}.safetensors", spec) for key, spec in MOUTH_MODEL_FILES.items()):
        warnings.append("未找到校验通过的 sprite-mouth 模型权重，已跳过。")
        return False

    dst_models = StorageLayout(output_dir).model_dir("sprite-mouth")
    dst_models.mkdir(parents=True, exist_ok=True)
    for key in MOUTH_MODEL_FILES:
        shutil.copy2(src_models / f"{key}.safetensors", dst_models / f"{key}.safetensors")

    src_runtime = StorageLayout(data_source_root).runtime_subdir("sprite-mouth")
    dst_runtime = StorageLayout(output_dir).runtime_subdir("sprite-mouth")
    if src_runtime.is_dir():
        _copy_tree(src_runtime, dst_runtime, dereference=True)

    if not _sprite_mouth_runtime_ready(output_dir):
        shutil.rmtree(dst_models, ignore_errors=True)
        shutil.rmtree(dst_runtime, ignore_errors=True)
        warnings.append(
            "随包运行环境不含 Python >=3.12 及口型检测依赖（未提供可运行的 data/runtime/sprite-mouth/python），已跳过。"
        )
        return False
    return True


def _apply_portable_templates(*, source_root: Path, output_dir: Path) -> None:
    template_root = source_root / "scripts" / "portable_templates"
    if not template_root.is_dir():
        raise FileNotFoundError(f"Missing portable template directory: {template_root}")

    config_templates = template_root / "data" / "config"
    dst_config = StorageLayout(output_dir).config_dir
    _copy_tree(config_templates, dst_config, dereference=True)

    readme_src = template_root / "使用说明.txt"
    if readme_src.is_file():
        shutil.copy2(readme_src, output_dir / "使用说明.txt")

    (output_dir / ".shinsekai-portable").write_text("portable=1\n", encoding="utf-8")

    layout = StorageLayout(output_dir)
    for rel in ("logs", "memory", "chat_history", "uploads", "plugins"):
        (layout.data_dir / rel).mkdir(parents=True, exist_ok=True)


def audit_portable_bundle(bundle_dir: Path) -> None:
    """Verify the portable bundle has valid sanitized configs and zero personal/temp artifacts."""
    if not (bundle_dir / ".shinsekai-portable").is_file():
        raise ValueError("Portable bundle is missing .shinsekai-portable marker")
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
    if toonout_dir.is_dir() and any(toonout_dir.iterdir()) and not _toonout_runtime_ready(bundle_dir):
        raise ValueError("Portable bundle includes ToonOut assets without a runnable PyTorch environment")

    mouth_dir = layout.model_dir("sprite-mouth")
    if mouth_dir.is_dir() and any(mouth_dir.glob("*.safetensors")) and not _sprite_mouth_runtime_ready(bundle_dir):
        raise ValueError("Portable bundle includes sprite-mouth weights without a runnable Python >=3.12 environment")

    bundle_py = _python_in_runtime_dir(bundle_dir / "runtime")
    if bundle_py is not None and site_packages_dirs_for_python(bundle_py):
        versions = installed_versions_for_python(bundle_py)
        hub_dir = layout.cache_dir / "huggingface" / "hub"
        sherpa_repo = hub_dir / ("models--" + SHERPA_ZIPFORMER_ASSET.repo_id.replace("/", "--"))
        if sherpa_repo.is_dir() and "sherpa-onnx" not in versions:
            raise ValueError("Portable bundle includes sherpa-asr models but runtime is missing sherpa-onnx")
        embedding_repo = hub_dir / ("models--" + EMBEDDING_MODEL_ASSET.repo_id.replace("/", "--"))
        if embedding_repo.is_dir() and ("onnxruntime" not in versions or "huggingface-hub" not in versions):
            raise ValueError(
                "Portable bundle includes embedding model but runtime is missing onnxruntime or huggingface-hub"
            )
        if layout.model_dir("perception-gguf").is_dir() and "pillow" not in versions:
            raise ValueError("Portable bundle includes perception-gguf but runtime is missing Pillow")


def _compress_bundle(source_root: Path, output_dir: Path) -> Path:
    seven_zip = source_root / "build_exe" / "7za.exe"
    if seven_zip.is_file():
        archive_path = output_dir.parent / f"{output_dir.name}.7z"
        if archive_path.exists():
            archive_path.unlink()
        subprocess.run(
            [str(seven_zip), "a", "-t7z", "-mx=5", str(archive_path), output_dir.name],
            cwd=output_dir.parent,
            check=True,
        )
        return archive_path

    archive_base = str(output_dir)
    created = shutil.make_archive(archive_base, "zip", root_dir=output_dir.parent, base_dir=output_dir.name)
    return Path(created)


def build_portable_bundle(
    *,
    source_root: Path,
    release_dir: Path,
    data_source_root: Path,
    output_dir: Path,
    runtime_dir: Path | None = None,
    frontend_dist_dir: Path | None = None,
    models: Sequence[str] = DEFAULT_MODELS,
    download_missing: bool = False,
    archive: bool = False,
    overwrite: bool = False,
) -> BundleReport:
    selected = tuple(dict.fromkeys(str(item).strip() for item in models if str(item).strip()))
    unknown = set(selected) - SUPPORTED_MODELS
    if unknown:
        raise ValueError(f"Unsupported model bundle key(s): {', '.join(sorted(unknown))}")

    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {output_dir} (pass --overwrite to replace)")
        shutil.rmtree(output_dir)

    _copy_base_desktop_app(
        source_root=source_root,
        release_dir=release_dir,
        output_dir=output_dir,
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist_dir,
    )
    _apply_portable_templates(source_root=source_root, output_dir=output_dir)

    warnings: list[str] = []
    included: list[str] = []
    if "embedding" in selected and _bundle_huggingface_asset(
        EMBEDDING_MODEL_ASSET,
        label="记忆向量模型",
        data_source_root=data_source_root,
        output_dir=output_dir,
        download_missing=download_missing,
        warnings=warnings,
    ):
        included.append("embedding")
    if "sherpa-asr" in selected:
        zipformer_ok = _bundle_huggingface_asset(
            SHERPA_ZIPFORMER_ASSET,
            label="Sherpa 流式 Zipformer 模型",
            data_source_root=data_source_root,
            output_dir=output_dir,
            download_missing=download_missing,
            warnings=warnings,
        )
        sensevoice_ok = _bundle_huggingface_asset(
            SHERPA_SENSEVOICE_ASSET,
            label="Sherpa SenseVoiceSmall 模型",
            data_source_root=data_source_root,
            output_dir=output_dir,
            download_missing=download_missing,
            warnings=warnings,
        )
        if zipformer_ok and sensevoice_ok:
            included.append("sherpa-asr")
    if "asr-small" in selected and _bundle_huggingface_asset(
        _asr_small_spec(),
        label="ASR faster-whisper-small 模型",
        data_source_root=data_source_root,
        output_dir=output_dir,
        download_missing=download_missing,
        warnings=warnings,
    ):
        included.append("asr-small")
    if "perception-gguf" in selected and _bundle_perception_gguf(
        data_source_root=data_source_root,
        output_dir=output_dir,
        warnings=warnings,
    ):
        included.append("perception-gguf")
    if "toonout" in selected and _bundle_toonout(
        data_source_root=data_source_root,
        output_dir=output_dir,
        warnings=warnings,
    ):
        included.append("toonout")
    if "sprite-mouth" in selected and _bundle_sprite_mouth(
        data_source_root=data_source_root,
        output_dir=output_dir,
        warnings=warnings,
    ):
        included.append("sprite-mouth")

    audit_portable_bundle(output_dir)
    archive_path = _compress_bundle(source_root, output_dir) if archive else None
    return BundleReport(
        output_dir=output_dir,
        archive_path=archive_path,
        included_models=tuple(included),
        warnings=tuple(warnings),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    version = _read_version(REPO_ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=REPO_ROOT,
        help="Shinsekai source repository root.",
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=REPO_ROOT / "frontend" / "src-tauri" / "target" / "release",
        help="Built Tauri release directory containing shinsekai.exe.",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=None,
        help="Optional Python runtime directory override (defaults to source runtime/ if present).",
    )
    parser.add_argument(
        "--data-source-root",
        type=Path,
        default=REPO_ROOT,
        help="Project root containing downloaded models and caches.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist" / f"Shinsekai-Portable-v{version}-win-x64",
        help="Destination folder for the assembled portable package.",
    )
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help=(
            "Comma-separated model packs to include "
            "(default: embedding,sherpa-asr,perception-gguf; optional: asr-small,toonout,sprite-mouth)."
        ),
    )
    parser.add_argument(
        "--download-missing",
        action="store_true",
        help="Download missing HF embedding model snapshot into the bundle if not cached locally.",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Compress the portable folder into a .7z (via build_exe/7za.exe) or .zip archive.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite --output-dir if it already exists.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    models = [item.strip() for item in str(args.models).split(",") if item.strip()]
    report = build_portable_bundle(
        source_root=args.source_root.resolve(),
        release_dir=args.release_dir.resolve(),
        data_source_root=args.data_source_root.resolve(),
        output_dir=args.output_dir.resolve(),
        runtime_dir=args.runtime_dir.resolve() if args.runtime_dir else None,
        models=models,
        download_missing=args.download_missing,
        archive=args.archive,
        overwrite=args.overwrite,
    )
    print(f"Portable bundle ready: {report.output_dir}")
    print(f"Included models: {', '.join(report.included_models) or '(none)'}")
    if report.archive_path is not None:
        print(f"Archive created: {report.archive_path}")
    for warning in report.warnings:
        print(f"[WARN] {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
