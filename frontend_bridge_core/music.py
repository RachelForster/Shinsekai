from __future__ import annotations

from pathlib import Path
from typing import Any

from .state import BridgeState, _jsonify
from .tasks import _append_task_log, _update_task


def _music_cover_source(payload: dict[str, Any]) -> str:
    source = str(payload.get("source") or "youtube").strip().lower()
    aliases = {
        "youtube": "youtube",
        "yt": "youtube",
        "bilibili": "bilibili",
        "b站": "bilibili",
        "url": "url",
    }
    if source not in aliases:
        raise ValueError(f"Unsupported music cover source: {source}")
    return aliases[source]


def _music_cover_search(state: BridgeState, payload: dict[str, Any]) -> dict[str, str]:
    from live.music_cover_pipeline import search_preview

    source = _music_cover_source(payload)
    query = str(payload.get("query") or "").strip()
    log = search_preview(state.config_manager.config.system_config, source, query)
    return {"log": str(log or "")}


def _run_music_cover(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, str]:
    from live.music_cover_pipeline import format_pipeline_log, run_pipeline

    source = _music_cover_source(payload)
    query = str(payload.get("query") or "").strip()
    pick_index = int(payload.get("pickIndex") or payload.get("pick_index") or 0)
    pick_index = max(0, min(7, pick_index))
    skip_rvc = bool(payload.get("skipRvc") or payload.get("skip_rvc"))
    _update_task(
        state,
        task_id,
        message="正在执行音乐翻唱流水线。",
        phase="pipeline",
        progress=0.2,
    )
    result = run_pipeline(
        state.config_manager.config.system_config,
        source=source,
        query=query,
        pick_index=pick_index,
        skip_rvc=skip_rvc,
    )
    log = str(format_pipeline_log(result) or "")
    final_mix = getattr(result, "final_mix", None)
    audio_path = str(final_mix) if final_mix is not None and Path(final_mix).exists() else ""
    if log:
        _append_task_log(state, task_id, log)
    return {"audioPath": audio_path, "log": log}


def _save_music_cover_config(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    current = state.config_manager.config.system_config

    def _float_value(key: str, default: float) -> float:
        raw = payload.get(key)
        if raw is None or raw == "":
            return float(default)
        return float(raw)

    def _int_value(key: str, default: int) -> int:
        raw = payload.get(key)
        if raw is None or raw == "":
            return int(default)
        return int(raw)

    message = state.config_manager.save_music_cover_config(
        str(payload.get("music_cover_work_dir") or ""),
        str(payload.get("music_cover_yt_dlp_exe") or ""),
        str(payload.get("music_cover_ffmpeg_exe") or ""),
        str(payload.get("music_cover_uvr_cmd_template") or ""),
        str(payload.get("music_cover_rvc_cmd_template") or ""),
        str(payload.get("music_cover_rvc_model_path") or ""),
        str(payload.get("music_cover_rvc_index_path") or ""),
        str(payload.get("music_cover_rvc_device") or ""),
        str(payload.get("music_cover_rvc_model_version") or ""),
        str(payload.get("music_cover_rvc_f0_method") or ""),
        _float_value("music_cover_rvc_pitch", getattr(current, "music_cover_rvc_pitch", 0.0)),
        _float_value("music_cover_rvc_index_rate", getattr(current, "music_cover_rvc_index_rate", 0.0)),
        _int_value("music_cover_rvc_filter_radius", getattr(current, "music_cover_rvc_filter_radius", 0)),
        _int_value("music_cover_rvc_resample_sr", getattr(current, "music_cover_rvc_resample_sr", 0)),
        _float_value("music_cover_rvc_rms_mix_rate", getattr(current, "music_cover_rvc_rms_mix_rate", 0.0)),
        _float_value("music_cover_rvc_protect", getattr(current, "music_cover_rvc_protect", 0.0)),
    )
    state.config_manager.reload()
    return {"message": message, "systemConfig": _jsonify(state.config_manager.config.system_config)}
