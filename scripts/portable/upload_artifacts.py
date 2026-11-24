"""Publish portable bundle archives to Hugging Face and ModelScope sequentially."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.portable.archive import compute_sha256
from scripts.portable.hub_providers import (
    ProviderUploadFn,
    UploadTargetConfig,
    VALID_REPO_TYPES,
    build_remote_url,
    make_default_upload_fn,
)

ARCHIVE_SUFFIXES = (".tar.gz", ".zip", ".7z")


@dataclass(frozen=True)
class UploadedArtifactRecord:
    """Record describing one uploaded portable archive and its sidecar metadata."""

    platform: str
    archive_name: str
    size_bytes: int
    sha256: str
    included_models: tuple[str, ...] = ()
    urls: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishReport:
    """Summary returned after publishing portable artifacts across configured targets."""

    release_prefix: str
    version: str
    uploaded_providers: tuple[str, ...]
    skipped_providers: dict[str, str]
    artifacts: tuple[UploadedArtifactRecord, ...]
    manifest_urls: dict[str, str]
    checksum_urls: dict[str, str]


DownloadPlatformFn = Callable[[str, str, str, Path], None]


def _download_github_platform_artifact(
    run_id: str,
    repo: str,
    platform: str,
    dest_dir: Path,
) -> None:
    artifact_name = f"shinsekai-portable-{platform}"
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(run_id),
            "-R",
            repo,
            "-n",
            artifact_name,
            "-D",
            str(dest_dir),
        ],
        check=True,
    )


def _is_archive_file(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and any(name.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _collect_archives_from_dir(directory: Path, fallback_platform: str = "") -> list[Path]:
    archives = sorted(
        (candidate for candidate in directory.rglob("*") if _is_archive_file(candidate)),
        key=lambda item: item.name,
    )
    if not archives:
        label = fallback_platform or str(directory)
        raise FileNotFoundError(f"No portable archive (.tar.gz/.zip/.7z) found for {label}")
    return archives


def _read_sidecar_metadata(archive_path: Path, fallback_platform: str = "") -> dict[str, Any]:
    meta_path = archive_path.with_name(f"{archive_path.name}.meta.json")
    if meta_path.is_file():
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    return {"platform": fallback_platform}


def _read_or_compute_sha256(archive_path: Path, meta: dict[str, Any]) -> tuple[str, Path | None]:
    sha_path = archive_path.with_name(f"{archive_path.name}.sha256")
    if sha_path.is_file():
        first_token = sha_path.read_text(encoding="utf-8").strip().split()
        if first_token and len(first_token[0]) == 64:
            return first_token[0].lower(), sha_path
    digest = str(meta.get("sha256") or "").strip().lower()
    if len(digest) != 64:
        digest = compute_sha256(archive_path)
    return digest, None


def _emit_step_summary(report: PublishReport, summary_path: Path | None) -> None:
    if summary_path is None:
        return
    lines = [
        f"## Portable Artifacts Publish (`{report.release_prefix}`)",
        "",
        "| Provider | Status | Details |",
        "| --- | --- | --- |",
    ]
    for provider in ("huggingface", "modelscope"):
        if provider in report.uploaded_providers:
            details = f"Manifest: `{report.manifest_urls.get(provider, '')}`"
            lines.append(f"| `{provider}` | Uploaded | {details} |")
        else:
            reason = report.skipped_providers.get(provider, "Skipped")
            lines.append(f"| `{provider}` | Skipped | {reason} |")

    if report.artifacts:
        lines.extend(
            [
                "",
                "| Platform | Archive | Size (MB) | SHA-256 | Hugging Face | ModelScope |",
                "| --- | --- | ---: | --- | --- | --- |",
            ]
        )
        for item in report.artifacts:
            size_mb = f"{item.size_bytes / (1024 * 1024):.1f}"
            hf_link = f"[download]({item.urls['huggingface']})" if "huggingface" in item.urls else "-"
            ms_link = f"[download]({item.urls['modelscope']})" if "modelscope" in item.urls else "-"
            lines.append(
                f"| `{item.platform}` | `{item.archive_name}` | {size_mb} | `{item.sha256[:12]}...` | {hf_link} | {ms_link} |"
            )

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def publish_portable_artifacts(
    *,
    targets: Sequence[UploadTargetConfig],
    release_prefix: str,
    version: str,
    artifacts_dir: Path | None = None,
    github_run_id: str = "",
    github_repo: str = "",
    platforms: Sequence[str] = (),
    require_configured: bool = False,
    summary_path: Path | None = None,
    upload_fn: ProviderUploadFn | None = None,
    download_fn: DownloadPlatformFn | None = None,
) -> PublishReport:
    """Upload built portable archives sequentially to configured Hugging Face / ModelScope targets."""
    active_targets = [cfg for cfg in targets if cfg.configured]
    skipped: dict[str, str] = {}
    for cfg in targets:
        if not cfg.configured:
            reason = cfg.missing_reason()
            skipped[cfg.provider] = reason
            print(f"::warning::{cfg.provider}: {reason}")

    clean_prefix = str(release_prefix or "").strip().strip("/")
    if not clean_prefix:
        clean_prefix = f"v{version}"

    if not active_targets:
        if require_configured:
            raise RuntimeError(
                "No upload provider is configured. Set HF_TOKEN/HF_PORTABLE_REPO_ID or "
                "MODELSCOPE_TOKEN/MODELSCOPE_PORTABLE_REPO_ID."
            )
        report = PublishReport(
            release_prefix=clean_prefix,
            version=version,
            uploaded_providers=(),
            skipped_providers=skipped,
            artifacts=(),
            manifest_urls={},
            checksum_urls={},
        )
        _emit_step_summary(report, summary_path)
        return report

    uploader = upload_fn or make_default_upload_fn()
    downloader = download_fn or _download_github_platform_artifact
    records: list[UploadedArtifactRecord] = []

    def _process_directory(stage_dir: Path, fallback_platform: str) -> None:
        for archive_path in _collect_archives_from_dir(stage_dir, fallback_platform):
            meta = _read_sidecar_metadata(archive_path, fallback_platform)
            digest, sha_path = _read_or_compute_sha256(archive_path, meta)
            platform_name = str(meta.get("platform") or fallback_platform or "unknown")
            included_models = tuple(str(m) for m in (meta.get("included_models") or ()))
            size_bytes = archive_path.stat().st_size
            remote_archive = f"{clean_prefix}/{archive_path.name}"
            urls: dict[str, str] = {}

            with tempfile.TemporaryDirectory(prefix="shinsekai-sha-") as sha_tmp:
                local_sha = sha_path
                if local_sha is None:
                    local_sha = Path(sha_tmp) / f"{archive_path.name}.sha256"
                    local_sha.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
                remote_sha = f"{clean_prefix}/{archive_path.name}.sha256"
                for cfg in active_targets:
                    commit_msg = f"Upload {archive_path.name} ({clean_prefix})"
                    urls[cfg.provider] = uploader(cfg, archive_path, remote_archive, commit_msg)
                    uploader(cfg, local_sha, remote_sha, f"Upload checksum for {archive_path.name}")

            records.append(
                UploadedArtifactRecord(
                    platform=platform_name,
                    archive_name=archive_path.name,
                    size_bytes=size_bytes,
                    sha256=digest,
                    included_models=included_models,
                    urls=urls,
                )
            )

    if artifacts_dir is not None:
        _process_directory(artifacts_dir, "")
    elif github_run_id and github_repo and platforms:
        for platform_name in platforms:
            with tempfile.TemporaryDirectory(prefix=f"shinsekai-dl-{platform_name}-") as dl_tmp:
                dl_dir = Path(dl_tmp)
                downloader(github_run_id, github_repo, platform_name, dl_dir)
                _process_directory(dl_dir, platform_name)
    else:
        raise ValueError(
            "Provide either --artifacts-dir or (--github-run-id, --github-repo, --platforms)."
        )

    manifest_urls: dict[str, str] = {}
    checksum_urls: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="shinsekai-manifest-") as meta_tmp:
        meta_dir = Path(meta_tmp)
        sums_path = meta_dir / "SHA256SUMS.txt"
        sums_lines = [f"{item.sha256}  {item.archive_name}" for item in records]
        sums_path.write_text("\n".join(sums_lines) + ("\n" if sums_lines else ""), encoding="utf-8")

        manifest_path = meta_dir / "portable-manifest.json"
        manifest_payload = {
            "version": version,
            "release_prefix": clean_prefix,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": [
                {
                    "platform": item.platform,
                    "archive_name": item.archive_name,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "included_models": list(item.included_models),
                    "urls": item.urls,
                }
                for item in records
            ],
        }
        manifest_path.write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")

        for cfg in active_targets:
            checksum_urls[cfg.provider] = uploader(
                cfg,
                sums_path,
                f"{clean_prefix}/SHA256SUMS.txt",
                f"Update SHA256SUMS.txt ({clean_prefix})",
            )
            manifest_urls[cfg.provider] = uploader(
                cfg,
                manifest_path,
                f"{clean_prefix}/portable-manifest.json",
                f"Update portable-manifest.json ({clean_prefix})",
            )

    report = PublishReport(
        release_prefix=clean_prefix,
        version=version,
        uploaded_providers=tuple(cfg.provider for cfg in active_targets),
        skipped_providers=skipped,
        artifacts=tuple(records),
        manifest_urls=manifest_urls,
        checksum_urls=checksum_urls,
    )
    _emit_step_summary(report, summary_path)
    return report


def _parse_bool_flag(raw: str | None, *, default: bool = True) -> bool:
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-prefix", required=True, help="Remote directory prefix (e.g. v2.7.0).")
    parser.add_argument("--version", default="", help="Application version string.")
    parser.add_argument("--artifacts-dir", type=Path, default=None, help="Local directory of built archives.")
    parser.add_argument("--github-run-id", default="", help="GitHub Actions workflow run id.")
    parser.add_argument("--github-repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="GitHub owner/repo.")
    parser.add_argument("--platforms", default="", help="Comma-separated platform list for gh run download.")
    parser.add_argument(
        "--require-configured",
        action="store_true",
        help="Fail instead of skipping when no provider secrets/variables are configured.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    targets = (
        UploadTargetConfig(
            provider="huggingface",
            enabled=_parse_bool_flag(os.environ.get("UPLOAD_HUGGINGFACE"), default=True),
            token=os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or "",
            repo_id=os.environ.get("HF_PORTABLE_REPO_ID", ""),
            repo_type=os.environ.get("HF_PORTABLE_REPO_TYPE", "model"),
        ),
        UploadTargetConfig(
            provider="modelscope",
            enabled=_parse_bool_flag(os.environ.get("UPLOAD_MODELSCOPE"), default=True),
            token=os.environ.get("MODELSCOPE_TOKEN", ""),
            repo_id=os.environ.get("MODELSCOPE_PORTABLE_REPO_ID", ""),
            repo_type=os.environ.get("MODELSCOPE_PORTABLE_REPO_TYPE", "model"),
        ),
    )
    platforms = tuple(item.strip() for item in str(args.platforms).split(",") if item.strip())
    summary_env = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    summary_path = Path(summary_env) if summary_env else None

    report = publish_portable_artifacts(
        targets=targets,
        release_prefix=args.release_prefix,
        version=args.version or args.release_prefix.lstrip("v"),
        artifacts_dir=args.artifacts_dir.resolve() if args.artifacts_dir else None,
        github_run_id=str(args.github_run_id).strip(),
        github_repo=str(args.github_repo).strip(),
        platforms=platforms,
        require_configured=args.require_configured,
        summary_path=summary_path,
    )
    print(f"Publish finished for {report.release_prefix}: uploaded={list(report.uploaded_providers)}")
    for provider, reason in report.skipped_providers.items():
        print(f"Skipped {provider}: {reason}")
    return 0


__all__ = [
    "DownloadPlatformFn",
    "ProviderUploadFn",
    "PublishReport",
    "UploadTargetConfig",
    "UploadedArtifactRecord",
    "VALID_REPO_TYPES",
    "build_remote_url",
    "main",
    "publish_portable_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
