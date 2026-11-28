"""Pi Agent binary runtime downloading and portable bundling."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat

from core.agent.pi_runtime import PI_RELEASE, PiRuntimeManager, file_digest
from core.downloads import download_archive
from core.storage.layout import StorageLayout
from scripts.portable.gguf_runtime import copy_tree
from scripts.portable.targets import PlatformTarget


def _github_headers() -> dict[str, str]:
    headers = {"User-Agent": "shinsekai-portable-builder"}
    gh_token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"
    return headers


def _cleanup_pi_staging(dst_pi_root: Path) -> None:
    shutil.rmtree(dst_pi_root / "downloads", ignore_errors=True)
    lock_file = dst_pi_root / "install.lock"
    if lock_file.is_file():
        lock_file.unlink(missing_ok=True)


def bundle_pi_agent(
    *,
    target: PlatformTarget,
    data_source_root: Path,
    output_dir: Path,
    download_missing: bool = False,
    warnings: list[str],
) -> bool:
    """Copy or download and verify the pinned official Pi Agent runtime into the bundle."""
    platform_key = target.pi_platform_key
    src_pi_root = StorageLayout(data_source_root).data_dir / "agent" / "runtimes" / "pi"
    dst_pi_root = StorageLayout(output_dir).data_dir / "agent" / "runtimes" / "pi"

    try:
        src_mgr = PiRuntimeManager(src_pi_root, platform_key=platform_key)
        src_runtime = src_mgr.inspect()
        dst_mgr = PiRuntimeManager(dst_pi_root, platform_key=platform_key)

        if src_runtime is not None:
            copy_tree(src_mgr.installed, dst_mgr.installed, dereference=True)
            if target.os_family != "windows" and os.name != "nt":
                rel_exe = src_runtime.executable.resolve().relative_to(src_mgr.installed.resolve())
                dst_exe = dst_mgr.installed / rel_exe
                if dst_exe.is_file():
                    dst_exe.chmod(dst_exe.stat().st_mode | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)
            if dst_mgr.inspect() is None:
                raise ValueError("Copied Pi runtime failed integrity verification.")
            return True

        cached_archive = src_pi_root / "downloads" / src_mgr.name
        if cached_archive.is_file() and file_digest(cached_archive) == src_mgr.sha256:
            dst_archive = dst_pi_root / "downloads" / dst_mgr.name
            dst_archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_archive, dst_archive)
            dst_mgr.ensure()
            _cleanup_pi_staging(dst_pi_root)
            if dst_mgr.inspect() is None:
                raise ValueError("Extracted cached Pi runtime failed integrity verification.")
            return True

        if not download_missing:
            warnings.append(
                f"未找到本地缓存的 Pi Agent 运行时（{platform_key}）；"
                "可追加 --download-missing 自动下载并打入便携包。"
            )
            return False

        dst_archive = dst_pi_root / "downloads" / dst_mgr.name
        download_archive(
            f"{PI_RELEASE}/{dst_mgr.name}",
            dst_archive,
            _github_headers(),
            expected_sha256=dst_mgr.sha256,
            timeout=(20, 300),
        )
        dst_mgr.ensure()
        _cleanup_pi_staging(dst_pi_root)
        if dst_mgr.inspect() is None:
            raise ValueError("Downloaded Pi runtime failed integrity verification.")
        return True
    except Exception as exc:
        shutil.rmtree(dst_pi_root, ignore_errors=True)
        warnings.append(f"准备 Pi Agent 运行时失败，已跳过：{exc}")
        return False
