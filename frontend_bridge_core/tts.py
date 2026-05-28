from __future__ import annotations

import sys
from typing import Any

from .state import BridgeState
from .tasks import _update_task


def _download_tts_bundle(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.tts.tts_bundle_worker import (
        _archive_filename,
        _extract_7za,
        _list_targets,
        _load_py7zr,
        _resolve_extracted_root,
        _rmtree,
        _seven_zip_exe,
    )
    from ui.settings_ui.tts.tts_env_probe import bundle_choice_for_kind, get_default_project_root

    kind = str(payload.get("kind") or "genie").strip()
    choice = bundle_choice_for_kind(kind)
    root = get_default_project_root().resolve()
    base = root / "data" / "tts_bundles"
    dl_dir = base / "downloads"
    out_dir = base / "installed" / choice.bundle_dir_key
    dl_dir.mkdir(parents=True, exist_ok=True)
    archive = dl_dir / _archive_filename(choice.download_url)
    _rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) EasyAI-Desktop/1.0"
        )
    }
    _update_task(state, task_id, message="正在下载 TTS 整合包。", phase="download", progress=0.02)
    try:
        import requests

        with requests.get(choice.download_url, stream=True, timeout=(15, 600), headers=headers) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            with archive.open("wb") as file:
                for chunk in response.iter_content(512 * 1024):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress = min(0.7, 0.7 * downloaded / total)
                        message = f"正在下载 {downloaded}/{total} bytes。"
                    else:
                        progress = min(0.35, downloaded / (50 * 1024 * 1024))
                        message = f"已下载 {downloaded} bytes。"
                    _update_task(state, task_id, message=message, phase="download", progress=round(progress, 4))
    except Exception as exc:
        raise RuntimeError(f"download: {exc}") from exc

    _update_task(state, task_id, message="正在解压 TTS 整合包。", phase="extract", progress=0.7)
    seven_zip = _seven_zip_exe()
    if getattr(sys, "frozen", False):
        if seven_zip is None:
            raise RuntimeError(f"7za not found; archive saved at {archive.resolve()}")
        error = _extract_7za(seven_zip, archive, out_dir)
        if error is not None:
            raise RuntimeError(f"extract: {error}; archive saved at {archive.resolve()}")
    else:
        py7zr = _load_py7zr()
        if py7zr is not None:
            try:
                with py7zr.SevenZipFile(archive, "r") as zfile:
                    targets = _list_targets(zfile)
                    total_targets = len(targets)
                    if total_targets == 0 or total_targets > 1000:
                        zfile.extractall(path=out_dir)
                    else:
                        for index, name in enumerate(targets, start=1):
                            zfile.extract(path=out_dir, targets=[name])
                            progress = 0.7 + 0.3 * index / total_targets
                            _update_task(
                                state,
                                task_id,
                                message=f"正在解压 {index}/{total_targets}。",
                                phase="extract",
                                progress=round(progress, 4),
                            )
            except Exception as exc:
                raise RuntimeError(f"extract: {exc}; archive saved at {archive.resolve()}") from exc
        elif seven_zip is not None:
            error = _extract_7za(seven_zip, archive, out_dir)
            if error is not None:
                raise RuntimeError(f"extract: {error}; archive saved at {archive.resolve()}")
        else:
            raise RuntimeError(f"py7zr is not installed; archive saved at {archive.resolve()}")

    bundle_root = _resolve_extracted_root(out_dir)
    result = {
        "path": str(bundle_root.resolve()),
        "provider": "genie-tts" if choice.kind == "genie" else "gpt-sovits",
    }
    _update_task(state, task_id, message="TTS 整合包已就绪。", phase="completed", progress=1, result=result)
    return result
