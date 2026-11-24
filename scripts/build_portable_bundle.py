"""Build a clean, sanitized, zero-setup cross-platform portable bundle for Shinsekai."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Apply mirror env BEFORE importing huggingface_hub (which reads HF_ENDPOINT at import time).
from config.mirror_env import apply_mirror_environment_from_system_config as _init_mirror_env

_init_mirror_env(REPO_ROOT / "data" / "config" / "system_config.yaml")

from ai.memory.config import EMBEDDING_MODEL_ASSET
from application.characters.sprite.mouth_resources import MODEL_FILES as MOUTH_MODEL_FILES
from core.media.toonout_assets import ARTIFACTS as TOONOUT_ARTIFACTS
from core.model_assets.service import ModelAssetSpec
from scripts.portable.archive import SUPPORTED_ARCHIVE_FORMATS
from scripts.portable.assembler import (
    BundleReport,
    build_portable_bundle as _assemble_portable_bundle,
    read_version,
)
from scripts.portable.audit import audit_portable_bundle as _audit_portable_bundle
from scripts.portable.targets import (
    DEFAULT_LLAMA_CPP_TAG,
    DEFAULT_MODELS,
    SUPPORTED_MODELS,
    SUPPORTED_TARGETS,
    PlatformTarget,
    default_bundle_dirname,
    infer_host_target,
    resolve_target,
)


def audit_portable_bundle(
    bundle_dir: Path,
    *,
    target: str | PlatformTarget | None = None,
) -> None:
    """Verify the portable bundle has valid sanitized configs and zero personal/temp artifacts."""
    resolved_target = resolve_target(target) if target is not None else None
    _audit_portable_bundle(
        bundle_dir,
        target=resolved_target,
        embedding_asset=EMBEDDING_MODEL_ASSET,
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
    """Assemble and validate a portable bundle, forwarding module-level asset overrides."""
    return _assemble_portable_bundle(
        source_root=source_root,
        release_dir=release_dir,
        data_source_root=data_source_root,
        output_dir=output_dir,
        target=target,
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist_dir,
        models=models,
        download_missing=download_missing,
        strict_models=strict_models,
        archive=archive,
        archive_format=archive_format,
        write_sha256=write_sha256,
        write_metadata=write_metadata,
        llama_cpp_tag=llama_cpp_tag,
        overwrite=overwrite,
        embedding_asset=embedding_asset or EMBEDDING_MODEL_ASSET,
        toonout_artifacts=toonout_artifacts if toonout_artifacts is not None else TOONOUT_ARTIFACTS,
        mouth_model_files=mouth_model_files if mouth_model_files is not None else MOUTH_MODEL_FILES,
    )


def _resolve_cli_models(raw_models: str, target: PlatformTarget) -> tuple[str, ...]:
    cleaned = str(raw_models or "").strip()
    if cleaned.lower() == "default":
        return target.default_models
    if not cleaned or cleaned.lower() == "none":
        return ()
    return tuple(item.strip() for item in cleaned.split(",") if item.strip())


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    version = read_version(REPO_ROOT)
    default_target = infer_host_target()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=default_target,
        help=f"Target portable platform ({', '.join(SUPPORTED_TARGETS)}; default: {default_target}).",
    )
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
        help="Built Tauri release directory containing the desktop executable or bundle/.",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=None,
        help="Optional Python runtime directory override (defaults to source runtime/ if present).",
    )
    parser.add_argument(
        "--frontend-dist-dir",
        type=Path,
        default=None,
        help="Optional built frontend dist directory override (defaults to source frontend/dist).",
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
        default=None,
        help=f"Destination folder (default: dist/{default_bundle_dirname(version, resolve_target(default_target))}).",
    )
    parser.add_argument(
        "--models",
        default="default",
        help=(
            "Comma-separated model packs to include, 'default' for target defaults, or 'none' "
            f"(supported: {', '.join(sorted(SUPPORTED_MODELS))})."
        ),
    )
    parser.add_argument(
        "--download-missing",
        action="store_true",
        help="Download missing model assets and llama.cpp binaries into the bundle if not cached locally.",
    )
    parser.add_argument(
        "--strict-models",
        action="store_true",
        help="Fail with a non-zero exit status if any requested model pack could not be bundled.",
    )
    parser.add_argument(
        "--llama-cpp-tag",
        default=os.environ.get("SHINSEKAI_LLAMA_CPP_TAG") or DEFAULT_LLAMA_CPP_TAG,
        help=f"ggml-org/llama.cpp release tag used when downloading GGUF runtime (default: {DEFAULT_LLAMA_CPP_TAG}).",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Compress the portable folder into an archive.",
    )
    parser.add_argument(
        "--archive-format",
        choices=SUPPORTED_ARCHIVE_FORMATS,
        default="auto",
        help="Archive format when --archive is passed (default: auto -> zip/7z on Windows, tar.gz on Unix).",
    )
    parser.add_argument(
        "--write-sha256",
        action="store_true",
        help="Write a `<archive>.sha256` checksum file alongside the compressed archive.",
    )
    parser.add_argument(
        "--write-metadata",
        action="store_true",
        help="Write a `<archive>.meta.json` descriptor alongside the compressed archive.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite --output-dir if it already exists.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    source_root = args.source_root.resolve()
    target = resolve_target(args.target)
    version = read_version(source_root)
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else (REPO_ROOT / "dist" / default_bundle_dirname(version, target)).resolve()
    )
    models = _resolve_cli_models(args.models, target)
    report = build_portable_bundle(
        source_root=source_root,
        release_dir=args.release_dir.resolve(),
        data_source_root=args.data_source_root.resolve(),
        output_dir=output_dir,
        target=target,
        runtime_dir=args.runtime_dir.resolve() if args.runtime_dir else None,
        frontend_dist_dir=args.frontend_dist_dir.resolve() if args.frontend_dist_dir else None,
        models=models,
        download_missing=args.download_missing,
        strict_models=args.strict_models,
        archive=args.archive,
        archive_format=args.archive_format,
        write_sha256=args.write_sha256,
        write_metadata=args.write_metadata,
        llama_cpp_tag=str(args.llama_cpp_tag or DEFAULT_LLAMA_CPP_TAG).strip(),
        overwrite=args.overwrite,
    )
    print(f"Portable bundle ready ({report.target}): {report.output_dir}")
    print(f"Included models: {', '.join(report.included_models) or '(none)'}")
    if report.archive_path is not None:
        print(f"Archive created: {report.archive_path}")
    if report.sha256_path is not None:
        print(f"SHA-256 written: {report.sha256_path}")
    if report.metadata_path is not None:
        print(f"Metadata written: {report.metadata_path}")
    for warning in report.warnings:
        print(f"[WARN] {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
