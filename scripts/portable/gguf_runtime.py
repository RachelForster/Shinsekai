"""GGUF weights and platform llama.cpp binary download and bundling."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import zipfile

from application.perception.server_launcher import _gguf_candidate_dirs
from core.downloads import download_archive
from core.storage.layout import StorageLayout
from scripts.portable.targets import (
    DEFAULT_LLAMA_CPP_TAG,
    PERCEPTION_GGUF_FILES,
    PERCEPTION_GGUF_REPO_ID,
    QWEN3_TTS_GGUF_FILES,
    QWEN3_TTS_GGUF_REPO_ID,
    PlatformTarget,
)

_QWEN3_QUANT_RANK = ("q8_0", "q4_k_m", "bf16", "f16")

IGNORED_DIR_NAMES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".git"})
IGNORED_FILE_SUFFIXES = (".pyc", ".pyo", ".pdb", ".d", ".rlib")


def ignore_copy_entries(_directory: str, entries: list[str]) -> set[str]:
    """Filter out Python cache and compiler artifact entries during copytree."""
    return {
        name
        for name in entries
        if name in IGNORED_DIR_NAMES or name.endswith(IGNORED_FILE_SUFFIXES)
    }


def copy_tree(src: Path, dst: Path, *, dereference: bool = True) -> None:
    """Recursively copy a directory while stripping caches and build intermediates."""
    if not src.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {src}")
    shutil.copytree(
        src,
        dst,
        symlinks=not dereference,
        ignore=ignore_copy_entries,
        dirs_exist_ok=True,
    )


def _validate_archive_member_path(extract_root: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise ValueError(f"Unsafe absolute archive member path: {member_name}")
    rel = Path(normalized)
    if ".." in rel.parts:
        raise ValueError(f"Unsafe path traversal in archive member: {member_name}")
    root_resolved = extract_root.resolve()
    target_resolved = (root_resolved / rel).resolve()
    if target_resolved != root_resolved and not target_resolved.is_relative_to(root_resolved):
        raise ValueError(f"Archive member escapes extraction directory: {member_name}")
    return target_resolved


def safe_extract_zip(archive_path: Path, extract_dir: Path) -> None:
    """Safely extract a zip archive after validating paths and symlink targets."""
    root_resolved = extract_dir.resolve()
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            target = _validate_archive_member_path(extract_dir, info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                link_target = zf.read(info.filename).decode("utf-8", errors="strict")
                if os.path.isabs(link_target):
                    raise ValueError(f"Unsafe absolute symlink target in zip: {link_target}")
                resolved_link = (target.parent / link_target).resolve()
                if not resolved_link.is_relative_to(root_resolved):
                    raise ValueError(f"Symlink escapes extraction directory: {info.filename} -> {link_target}")
        zf.extractall(extract_dir)
        if os.name != "nt":
            for info in zf.infolist():
                if info.is_dir():
                    continue
                target = extract_dir / info.filename
                unix_mode = (info.external_attr >> 16) & 0o777
                if unix_mode and target.is_file() and not target.is_symlink():
                    target.chmod(unix_mode)


def safe_extract_tar_gz(archive_path: Path, extract_dir: Path) -> None:
    """Safely extract a .tar.gz archive after validating member paths and links."""
    root_resolved = extract_dir.resolve()
    with tarfile.open(archive_path, "r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            target = _validate_archive_member_path(extract_dir, member.name)
            if member.issym():
                if os.path.isabs(member.linkname):
                    raise ValueError(f"Unsafe absolute symlink in tar: {member.name} -> {member.linkname}")
                resolved_link = (target.parent / member.linkname).resolve()
                if not resolved_link.is_relative_to(root_resolved):
                    raise ValueError(
                        f"Symlink escapes extraction directory: {member.name} -> {member.linkname}"
                    )
            elif member.islnk():
                _validate_archive_member_path(extract_dir, member.linkname)
            elif member.isdev() or member.ischr() or member.isblk() or member.isfifo():
                raise ValueError(f"Unsupported special file in archive: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tf.extractall(extract_dir, members=members, filter="data")
        else:
            tf.extractall(extract_dir, members=members)


def _download_gguf_weights(
    dst_dir: Path,
    *,
    repo_id: str = PERCEPTION_GGUF_REPO_ID,
    files: tuple[str, ...] = PERCEPTION_GGUF_FILES,
) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    hf_token = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or "").strip() or None
    endpoint = (
        os.environ.get("HF_ENDPOINT", "").strip()
        or os.environ.get("HUGGINGFACE_HUB_ENDPOINT", "").strip()
        or "https://huggingface.co"
    ).rstrip("/")

    for filename in files:
        dest_file = dst_dir / filename
        if dest_file.is_file() and dest_file.stat().st_size > 0:
            continue
        try:
            from huggingface_hub import hf_hub_download

            downloaded = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(dst_dir),
                token=hf_token,
            )
            resolved = Path(downloaded)
            if resolved.is_symlink():
                materialized = resolved.resolve()
                resolved.unlink()
                shutil.copy2(materialized, resolved)
        except Exception:
            url = f"{endpoint}/{repo_id}/resolve/main/{filename}"
            headers = {"User-Agent": "shinsekai-portable-builder"}
            if hf_token:
                headers["Authorization"] = f"Bearer {hf_token}"
            download_archive(url, dest_file, headers, timeout=(20, 900))

    hf_cache_dir = dst_dir / ".cache"
    if hf_cache_dir.is_dir():
        shutil.rmtree(hf_cache_dir, ignore_errors=True)


def _download_llama_cpp_runtime(
    *,
    target: PlatformTarget,
    dst_dir: Path,
    llama_cpp_tag: str,
) -> None:
    headers = {"User-Agent": "shinsekai-portable-builder"}
    gh_token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    with tempfile.TemporaryDirectory(prefix="shinsekai-llamacpp-") as tmp_str:
        tmp_dir = Path(tmp_str)
        archive_path: Path | None = None
        last_error: Exception | None = None
        for template in target.llama_asset_candidates:
            asset_name = template.format(tag=llama_cpp_tag)
            url = f"https://github.com/ggml-org/llama.cpp/releases/download/{llama_cpp_tag}/{asset_name}"
            candidate_path = tmp_dir / asset_name
            try:
                download_archive(url, candidate_path, headers, timeout=(20, 600))
                archive_path = candidate_path
                break
            except Exception as exc:
                last_error = exc
                candidate_path.unlink(missing_ok=True)
        if archive_path is None:
            raise RuntimeError(
                f"Failed to download llama.cpp runtime ({llama_cpp_tag}) for {target.name}: {last_error}"
            )

        extract_dir = tmp_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        if archive_path.name.endswith(".zip"):
            safe_extract_zip(archive_path, extract_dir)
        elif archive_path.name.endswith(".tar.gz"):
            safe_extract_tar_gz(archive_path, extract_dir)
        else:
            raise ValueError(f"Unsupported llama.cpp archive format: {archive_path.name}")

        matches = sorted(extract_dir.rglob(target.llama_executable))
        server_exe = next((match for match in matches if match.is_file() or match.is_symlink()), None)
        if server_exe is None:
            raise FileNotFoundError(
                f"llama.cpp archive {archive_path.name} does not contain {target.llama_executable}"
            )

        llama_dst = dst_dir / "llama.cpp"
        copy_tree(server_exe.parent, llama_dst, dereference=(target.os_family == "windows"))
        dst_exe = llama_dst / target.llama_executable
        if target.os_family != "windows" and dst_exe.is_file() and not dst_exe.is_symlink():
            dst_exe.chmod(dst_exe.stat().st_mode | 0o111)


def _accepted_llama_executables(target: PlatformTarget, *, allow_host_fallback: bool) -> list[str]:
    llama_names = [target.llama_executable]
    if allow_host_fallback:
        host_llama = "llama-server.exe" if os.name == "nt" else "llama-server"
        if host_llama not in llama_names:
            llama_names.append(host_llama)
    return llama_names


def _rank_gguf_file(path: Path) -> tuple[int, str]:
    lowered = path.name.lower()
    for idx, token in enumerate(_QWEN3_QUANT_RANK):
        if token in lowered:
            return (idx, lowered)
    return (len(_QWEN3_QUANT_RANK), lowered)


def _find_local_qwen3_tts_pair(data_source_root: Path) -> tuple[Path, Path, Path | None] | None:
    layout = StorageLayout(data_source_root)
    for candidate in (layout.model_dir("qwen3-tts-gguf"), layout.cache_dir / "qwen3-tts-gguf"):
        if not candidate.is_dir():
            continue
        llama_dir = (candidate / "llama.cpp") if (candidate / "llama.cpp").is_dir() else None
        exact = [candidate / name for name in QWEN3_TTS_GGUF_FILES]
        if all(path.is_file() and path.stat().st_size > 0 for path in exact):
            return exact[0], exact[1], llama_dir
        non_mmproj: list[Path] = []
        mmprojs: list[Path] = []
        for entry in candidate.glob("*.gguf"):
            if not entry.is_file() or entry.stat().st_size <= 0:
                continue
            if "mmproj" in entry.name.lower():
                mmprojs.append(entry)
            else:
                non_mmproj.append(entry)
        if non_mmproj and mmprojs:
            return min(non_mmproj, key=_rank_gguf_file), min(mmprojs, key=_rank_gguf_file), llama_dir
    return None


def bundle_perception_gguf(
    *,
    target: PlatformTarget,
    data_source_root: Path,
    output_dir: Path,
    download_missing: bool = False,
    llama_cpp_tag: str = DEFAULT_LLAMA_CPP_TAG,
    allow_host_llama_fallback: bool = False,
    warnings: list[str],
) -> bool:
    """Copy or download Qwen3-VL-2B GGUF weights and platform llama-server runtime."""
    llama_names = _accepted_llama_executables(target, allow_host_fallback=allow_host_llama_fallback)

    src_dir: Path | None = None
    matched_llama_name = target.llama_executable
    for candidate in _gguf_candidate_dirs(data_source_root):
        if not all((candidate / name).is_file() for name in PERCEPTION_GGUF_FILES):
            continue
        found_llama = next(
            (name for name in llama_names if (candidate / "llama.cpp" / name).is_file()),
            None,
        )
        if found_llama is not None:
            src_dir = candidate
            matched_llama_name = found_llama
            break

    dst_dir = StorageLayout(output_dir).model_dir("perception-gguf")
    if src_dir is not None:
        copy_tree(src_dir, dst_dir, dereference=(target.os_family == "windows"))
        return True

    if not download_missing:
        warnings.append("未找到完整的 perception-gguf 模型与 llama.cpp，已跳过。")
        return False

    required = (
        Path("llama.cpp") / matched_llama_name,
        *(Path(name) for name in PERCEPTION_GGUF_FILES),
    )
    try:
        _download_gguf_weights(dst_dir)
        _download_llama_cpp_runtime(
            target=target,
            dst_dir=dst_dir,
            llama_cpp_tag=llama_cpp_tag,
        )
        if not all((dst_dir / rel).is_file() for rel in required):
            raise FileNotFoundError("Downloaded perception-gguf bundle is missing required files.")
        return True
    except Exception as exc:
        shutil.rmtree(dst_dir, ignore_errors=True)
        warnings.append(f"下载 perception-gguf 模型或 llama.cpp 失败，已跳过：{exc}")
        return False


def bundle_qwen3_tts_gguf(
    *,
    target: PlatformTarget,
    data_source_root: Path,
    output_dir: Path,
    download_missing: bool = False,
    llama_cpp_tag: str = DEFAULT_LLAMA_CPP_TAG,
    allow_host_llama_fallback: bool = False,
    warnings: list[str],
) -> bool:
    """Copy or download Qwen3-TTS 0.6B GGUF weights and reuse or bundle llama-server."""
    dst_dir = StorageLayout(output_dir).model_dir("qwen3-tts-gguf")
    local_pair = _find_local_qwen3_tts_pair(data_source_root)
    if local_pair is None and not download_missing:
        warnings.append("未找到完整的 qwen3-tts-gguf 模型权重，已跳过；可追加 --download-missing 自动下载并打入便携包。")
        return False

    try:
        local_llama_dir: Path | None = None
        if local_pair is not None:
            src_backbone, src_mmproj, local_llama_dir = local_pair
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_backbone, dst_dir / src_backbone.name)
            shutil.copy2(src_mmproj, dst_dir / src_mmproj.name)
            expected_weights = (src_backbone.name, src_mmproj.name)
        else:
            _download_gguf_weights(
                dst_dir,
                repo_id=QWEN3_TTS_GGUF_REPO_ID,
                files=QWEN3_TTS_GGUF_FILES,
            )
            expected_weights = QWEN3_TTS_GGUF_FILES

        if not all((dst_dir / name).is_file() and (dst_dir / name).stat().st_size > 0 for name in expected_weights):
            raise FileNotFoundError("qwen3-tts-gguf bundle is missing required GGUF weights.")

        llama_names = _accepted_llama_executables(target, allow_host_fallback=allow_host_llama_fallback)
        shared_llama_dir = StorageLayout(output_dir).model_dir("perception-gguf") / "llama.cpp"
        if any((shared_llama_dir / name).is_file() for name in llama_names):
            return True

        candidate_llama_dirs: list[Path] = []
        if local_llama_dir is not None:
            candidate_llama_dirs.append(local_llama_dir)
        for cand in _gguf_candidate_dirs(data_source_root):
            candidate_llama_dirs.append(cand / "llama.cpp")

        matched_llama_dir = next(
            (
                cand
                for cand in candidate_llama_dirs
                if cand.is_dir() and any((cand / name).is_file() for name in llama_names)
            ),
            None,
        )
        if matched_llama_dir is not None:
            copy_tree(matched_llama_dir, dst_dir / "llama.cpp", dereference=(target.os_family == "windows"))
        elif download_missing:
            _download_llama_cpp_runtime(
                target=target,
                dst_dir=dst_dir,
                llama_cpp_tag=llama_cpp_tag,
            )
        else:
            raise FileNotFoundError("No usable llama-server runtime found for qwen3-tts-gguf.")

        if not any((dst_dir / "llama.cpp" / name).is_file() for name in llama_names):
            raise FileNotFoundError("Bundled qwen3-tts-gguf runtime is missing llama-server executable.")
        return True
    except Exception as exc:
        shutil.rmtree(dst_dir, ignore_errors=True)
        warnings.append(f"准备 qwen3-tts-gguf 模型或 llama.cpp 失败，已跳过：{exc}")
        return False
