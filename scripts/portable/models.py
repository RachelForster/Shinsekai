"""Hugging Face and optional PyTorch/mouth model bundling and runtime probes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Mapping

from application.characters.sprite import mouth_resources
from application.runtime.dependencies import (
    installed_versions_for_python,
    site_packages_dirs_for_python,
)
from core.media.toonout_assets import ARTIFACTS as DEFAULT_TOONOUT_ARTIFACTS, verify_assets
from core.model_assets.service import ModelAssetSpec, find_cached_huggingface_snapshot
from core.storage.layout import StorageLayout
from scripts.portable.gguf_runtime import copy_tree


def python_in_runtime_dir(runtime_dir: Path) -> Path | None:
    """Locate the Python executable inside a runtime prefix."""
    for rel in (
        "python.exe",
        "Scripts/python.exe",
        "bin/python3.11",
        "bin/python3.10",
        "bin/python3",
        "bin/python",
    ):
        candidate = runtime_dir / rel
        if candidate.is_file():
            return candidate
    return None


def find_bundle_python(bundle_dir: Path) -> Path | None:
    """Locate the bundled Python interpreter in flat or macOS .app portable layouts."""
    candidates = (
        bundle_dir / "runtime",
        bundle_dir / "Shinsekai.app" / "Contents" / "Resources" / "runtime",
    )
    for runtime_dir in candidates:
        found = python_in_runtime_dir(runtime_dir)
        if found is not None:
            return found
    return None


def materialize_hf_repo_snapshot(
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
    copy_tree(snapshot_dir, dst_snapshot, dereference=True)

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


def bundle_huggingface_asset(
    spec: ModelAssetSpec,
    *,
    label: str,
    data_source_root: Path,
    output_dir: Path,
    download_missing: bool,
    warnings: list[str],
) -> bool:
    """Copy or download a Hugging Face model asset into the bundle's cache directory."""
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
            apply_mirror_environment_from_system_config(
                data_source_root / "data" / "config" / "system_config.yaml"
            )
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

    repo_folder = "models--" + spec.repo_id.replace("/", "--")
    if snapshot.is_relative_to(target_hub):
        staged_tmp = target_hub / f".staging-{repo_folder}"
        if staged_tmp.exists():
            shutil.rmtree(staged_tmp)
        copy_tree(snapshot, staged_tmp, dereference=True)
        shutil.rmtree(snapshot)
        shutil.move(str(staged_tmp), str(snapshot))
        for removable in (target_hub / repo_folder / "blobs", target_hub / ".locks"):
            if removable.is_dir():
                shutil.rmtree(removable, ignore_errors=True)
    else:
        materialize_hf_repo_snapshot(
            snapshot_dir=snapshot,
            repo_id=spec.repo_id,
            target_hub_dir=target_hub,
            revision_ref=spec.revision or "main",
        )
    return True


def toonout_runtime_ready(bundle_dir: Path) -> bool:
    """Return True when the portable bundle has PyTorch + ToonOut dependencies."""
    layout = StorageLayout(bundle_dir)
    py = python_in_runtime_dir(layout.runtime_subdir("toonout")) or find_bundle_python(bundle_dir)
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


def sprite_mouth_runtime_ready(bundle_dir: Path) -> bool:
    """Return True when the portable bundle has Python >=3.12 + mouth tracking dependencies."""
    layout = StorageLayout(bundle_dir)
    packages_dir = layout.runtime_subdir("sprite-mouth") / "packages"
    candidates: list[Path] = []
    for sub in (
        layout.runtime_subdir("sprite-mouth") / "python",
        bundle_dir / "runtime",
        bundle_dir / "Shinsekai.app" / "Contents" / "Resources" / "runtime",
    ):
        found = python_in_runtime_dir(sub)
        if found is not None:
            candidates.append(found)
    for candidate in candidates:
        probe = mouth_resources._probe(
            str(candidate),
            str(packages_dir),
            candidate.stat().st_mtime_ns,
        )
        version = probe.get("version", [])
        if tuple(version[:2]) >= (3, 12) and not probe.get("missing"):
            return True
    return False


def bundle_toonout(
    *,
    data_source_root: Path,
    output_dir: Path,
    warnings: list[str],
    artifacts: Mapping[str, tuple[str, str]] | None = None,
) -> bool:
    """Copy ToonOut weights and dedicated runtime if present and runnable."""
    resolved_artifacts = artifacts if artifacts is not None else DEFAULT_TOONOUT_ARTIFACTS
    candidates = (
        StorageLayout(data_source_root).model_dir("toonout"),
        data_source_root / "cache" / "models" / "toonout",
    )
    src_dir = next(
        (
            candidate
            for candidate in candidates
            if all((candidate / name).is_file() for name in resolved_artifacts)
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
        copy_tree(src_runtime, dst_runtime, dereference=True)
        copied_runtime = True

    dst_dir = StorageLayout(output_dir).model_dir("toonout")
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in resolved_artifacts:
        shutil.copy2(src_dir / name, dst_dir / name)
    deps_dir = src_dir / "deps"
    if deps_dir.is_dir():
        copy_tree(deps_dir, dst_dir / "deps", dereference=True)
    verify_assets(dst_dir)

    if not toonout_runtime_ready(output_dir):
        shutil.rmtree(dst_dir, ignore_errors=True)
        if copied_runtime:
            shutil.rmtree(dst_runtime, ignore_errors=True)
        warnings.append(
            "随包运行环境不含 ToonOut 所需的 PyTorch 依赖（未提供可运行的 data/runtime/toonout），已跳过。"
        )
        return False
    return True


def bundle_sprite_mouth(
    *,
    data_source_root: Path,
    output_dir: Path,
    warnings: list[str],
    model_files: Mapping[str, Mapping[str, object]] | None = None,
) -> bool:
    """Copy sprite-mouth weights and dedicated Python >=3.12 runtime if runnable."""
    resolved_model_files = model_files if model_files is not None else mouth_resources.MODEL_FILES
    src_models = StorageLayout(data_source_root).model_dir("sprite-mouth")
    if not all(
        mouth_resources.verify_weight(src_models / f"{key}.safetensors", spec)
        for key, spec in resolved_model_files.items()
    ):
        warnings.append("未找到校验通过的 sprite-mouth 模型权重，已跳过。")
        return False

    dst_models = StorageLayout(output_dir).model_dir("sprite-mouth")
    dst_models.mkdir(parents=True, exist_ok=True)
    for key in resolved_model_files:
        shutil.copy2(src_models / f"{key}.safetensors", dst_models / f"{key}.safetensors")

    src_runtime = StorageLayout(data_source_root).runtime_subdir("sprite-mouth")
    dst_runtime = StorageLayout(output_dir).runtime_subdir("sprite-mouth")
    if src_runtime.is_dir():
        copy_tree(src_runtime, dst_runtime, dereference=True)

    if not sprite_mouth_runtime_ready(output_dir):
        shutil.rmtree(dst_models, ignore_errors=True)
        shutil.rmtree(dst_runtime, ignore_errors=True)
        warnings.append(
            "随包运行环境不含 Python >=3.12 及口型检测依赖（未提供可运行的 data/runtime/sprite-mouth/python），已跳过。"
        )
        return False
    return True
