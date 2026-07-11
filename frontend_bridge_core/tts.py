from __future__ import annotations

from typing import Any

from .state import BridgeState
from .tasks import TaskCancelled, _is_task_cancel_requested, _update_task


def _tts_bundle_recommendation() -> dict[str, Any]:
    from ui.settings_ui.tts.tts_env_probe import (
        format_platform,
        get_gpu_list,
        recommend_tts_bundle,
    )

    gpus = get_gpu_list()
    choice = recommend_tts_bundle(gpus)
    return {
        "gpus": gpus,
        "kind": choice.kind,
        "platform": format_platform(),
    }


def _download_tts_bundle(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .config import _state_project_root
    from ui.settings_ui.tts.tts_bundle_worker import (
        _DownloadInterrupted,
        _ExtractionInterrupted,
        _archive_filename,
        _archive_verification_error,
        _download_archive,
        _extract_archive,
        _resolve_extracted_root,
        _rmtree,
    )
    from ui.settings_ui.tts.tts_bundle_manifest import bundle_manifest_for_key
    from ui.settings_ui.tts.tts_env_probe import bundle_choice_for_kind

    kind = str(payload.get("kind") or "genie").strip()
    choice = bundle_choice_for_kind(kind)
    root = _state_project_root(state)
    base = root / "data" / "tts_bundles"
    dl_dir = base / "downloads"
    out_dir = base / "installed" / choice.bundle_dir_key
    dl_dir.mkdir(parents=True, exist_ok=True)
    manifest = bundle_manifest_for_key(choice.bundle_dir_key)
    local_name = manifest.filename if manifest is not None else _archive_filename(choice.download_url)
    archive = dl_dir / local_name
    downloaded_this_run = False
    started_extract = False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) EasyAI-Desktop/1.0"
        )
    }

    def cancel_requested() -> bool:
        return _is_task_cancel_requested(state, task_id)

    def cleanup_cancelled_download() -> None:
        part = archive.with_name(f"{archive.name}.part")
        if part.exists():
            part.unlink()
        if downloaded_this_run and archive.exists():
            archive.unlink()
        if started_extract:
            _rmtree(out_dir)

    archive_ready = False
    if manifest is not None and archive.exists():
        _update_task(state, task_id, message="正在校验已下载的 TTS 整合包。", phase="verify", progress=0.01)
        try:
            archive_ready = _archive_verification_error(archive, manifest, is_interrupted=cancel_requested) is None
        except _DownloadInterrupted as exc:
            cleanup_cancelled_download()
            raise TaskCancelled() from exc

    if cancel_requested():
        cleanup_cancelled_download()
        raise TaskCancelled()

    if not archive_ready:
        _update_task(state, task_id, message="正在下载 TTS 整合包。", phase="download", progress=0.02)

        def on_download_progress(progress: int) -> None:
            _update_task(
                state,
                task_id,
                message=f"正在下载 TTS 整合包（{progress}%）。",
                phase="download",
                progress=round(progress / 100, 4),
            )

        try:
            _download_archive(
                choice.download_url,
                archive,
                headers,
                expected_size=manifest.size if manifest is not None else None,
                expected_sha256=manifest.sha256 if manifest is not None else None,
                is_interrupted=cancel_requested,
                on_progress=on_download_progress,
                timeout=(15, 5),
            )
            downloaded_this_run = True
        except _DownloadInterrupted as exc:
            cleanup_cancelled_download()
            raise TaskCancelled() from exc
        except Exception as exc:
            cleanup_cancelled_download()
            raise RuntimeError(f"download: {exc}") from exc

    if cancel_requested():
        cleanup_cancelled_download()
        raise TaskCancelled()

    _update_task(state, task_id, message="正在解压 TTS 整合包。", phase="extract", progress=0.7)
    _rmtree(out_dir)
    started_extract = True
    out_dir.mkdir(parents=True, exist_ok=True)

    def on_extract_progress(progress: int) -> None:
        _update_task(
            state,
            task_id,
            message=f"正在解压 TTS 整合包（{progress}%）。",
            phase="extract",
            progress=round(progress / 100, 4),
        )

    try:
        error = _extract_archive(
            archive,
            out_dir,
            is_interrupted=cancel_requested,
            on_progress=on_extract_progress,
        )
    except _ExtractionInterrupted as exc:
        cleanup_cancelled_download()
        raise TaskCancelled() from exc
    if cancel_requested():
        cleanup_cancelled_download()
        raise TaskCancelled()
    if error is not None:
        _rmtree(out_dir)
        raise RuntimeError(f"extract: {error}; archive saved at {archive.resolve()}")

    bundle_root = _resolve_extracted_root(out_dir)
    result = {
        "path": str(bundle_root.resolve()),
        "provider": "genie-tts" if choice.kind == "genie" else "gpt-sovits",
    }
    _update_task(state, task_id, message="TTS 整合包已就绪。", phase="completed", progress=1, result=result)
    return result
