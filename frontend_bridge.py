"""Lightweight HTTP bridge for the React frontend.

The React layer talks to this process through ``shared/platform``. The bridge
keeps YAML, filesystem, plugin, and chat-launch behavior in Python where the
current project already owns it.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from email.parser import BytesParser
from email.policy import default as default_email_policy
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

MARK_SCENARIO = "<<<EASYAI_USER_SCENARIO>>>"
MARK_SYSTEM = "<<<EASYAI_SYSTEM_TEMPLATE>>>"
TEMP_SPLIT_META = "_temp_split.json"
TRANSPARENT_BACKGROUND_NAME = "透明场景"
_main_chat_process: subprocess.Popen[bytes] | None = None
_MODEL_REQUEST_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 Shinsekai/1.0"
)
_IMAGE_ONLY_MODEL_MARKERS = (
    "dall-e",
    "dalle",
    "flux",
    "gpt-image",
    "imagen",
    "midjourney",
    "qwen-image",
    "sdxl",
    "stable-diffusion",
)
_TTS_LABEL_PREFS: tuple[tuple[str, str], ...] = (
    ("genie-tts", "Genie TTS"),
    ("gpt-sovits", "GPT SoVITS"),
    ("index-tts", "IndexTTS"),
    ("cosyvoice", "CosyVoice"),
)
_PREFERRED_T2I_KEYS_LOWER: tuple[str, ...] = ("comfyui", "stable diffusion")


@dataclass
class BridgeState:
    config_manager: Any
    character_manager: Any
    background_manager: Any
    template_generator: Any
    task_lock: threading.Lock = field(default_factory=threading.Lock)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    template_dir_path: str = "./data/character_templates"
    history_dir: str = "./data/chat_history"
    frontend_dist_dir: str = ""
    chat_session: dict[str, Any] = field(default_factory=dict)


def _jsonify(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    return value


def _adapter_schema(adapter_class: Any | None) -> dict[str, Any]:
    if adapter_class is None:
        return {}
    getter = getattr(adapter_class, "get_config_schema", None)
    if not callable(getter):
        return {}
    try:
        schema = getter()
    except Exception:
        return {}
    return _jsonify(schema) if isinstance(schema, dict) else {}


def _adapter_option(value: str, label: str, adapter_class: Any | None = None) -> dict[str, Any]:
    return {
        "label": str(label or value),
        "schema": _adapter_schema(adapter_class),
        "value": str(value),
    }


def _adapter_catalog() -> dict[str, list[dict[str, Any]]]:
    """Expose the same registered adapter choices the PyQt settings tab uses."""
    try:
        from asr.asr_manager import ASRAdapterFactory
        from llm.constants import LLM_BASE_URLS
        from llm.llm_manager import LLMAdapterFactory
        from t2i.t2i_manager import T2IAdapterFactory
        from tts.tts_manager import TTSAdapterFactory
    except Exception:
        return {"asr": [], "llm": [], "t2i": [], "tts": []}

    llm_adapters = dict(LLMAdapterFactory._adapters)
    llm: list[dict[str, Any]] = []
    for key in LLM_BASE_URLS.keys():
        if key in llm_adapters:
            llm.append(_adapter_option(key, key, llm_adapters[key]))
    for key in sorted(llm_adapters.keys(), key=str.lower):
        if key not in {item["value"] for item in llm}:
            llm.append(_adapter_option(key, key, llm_adapters[key]))

    tts_adapters = dict(TTSAdapterFactory._adapters)
    tts: list[dict[str, Any]] = [_adapter_option("none", "不使用", None)]
    by_lower = {key.lower(): key for key in tts_adapters}
    seen: set[str] = set()
    for slug, label in _TTS_LABEL_PREFS:
        canonical = by_lower.get(slug)
        if canonical:
            tts.append(_adapter_option(canonical, label, tts_adapters[canonical]))
            seen.add(canonical)
    for key in sorted(tts_adapters.keys(), key=str.lower):
        if key not in seen:
            tts.append(_adapter_option(key, key.replace("-", " ").title(), tts_adapters[key]))

    t2i_adapters = dict(T2IAdapterFactory._adapters)
    t2i_by_lower = {key.lower(): key for key in t2i_adapters}
    t2i: list[dict[str, Any]] = []
    fixed_t2i_labels = {"comfyui": "ComfyUI", "stable diffusion": "Stable Diffusion"}
    for preferred in _PREFERRED_T2I_KEYS_LOWER:
        canonical = t2i_by_lower.get(preferred)
        if canonical:
            t2i.append(
                _adapter_option(
                    canonical,
                    fixed_t2i_labels.get(canonical.lower(), canonical.replace("-", " ").title()),
                    t2i_adapters[canonical],
                )
            )
    for key in sorted(t2i_adapters.keys(), key=str.lower):
        if key not in {item["value"] for item in t2i}:
            t2i.append(
                _adapter_option(
                    key,
                    fixed_t2i_labels.get(key.lower(), key.replace("-", " ").title()),
                    t2i_adapters[key],
                )
            )

    asr_adapters = dict(ASRAdapterFactory._adapters)
    asr_labels = {"faster_whisper": "faster-whisper", "realtime_stt": "RealtimeSTT", "vosk": "Vosk"}
    asr: list[dict[str, Any]] = []
    if "vosk" in asr_adapters:
        asr.append(_adapter_option("vosk", asr_labels["vosk"], asr_adapters["vosk"]))
    for key in sorted(k for k in asr_adapters.keys() if k != "vosk"):
        asr.append(_adapter_option(key, asr_labels.get(key, key), asr_adapters[key]))

    return {"asr": asr, "llm": llm, "t2i": t2i, "tts": tts}


def _app_config_response(state: BridgeState) -> dict[str, Any]:
    payload = _jsonify(state.config_manager.config)
    if not isinstance(payload, dict):
        return {}
    api_config = payload.get("api_config")
    if isinstance(api_config, dict):
        provider = str(api_config.get("llm_provider") or "Deepseek").strip() or "Deepseek"
        if not str(api_config.get("llm_base_url") or "").strip():
            try:
                from llm.constants import LLM_BASE_URLS

                api_config["llm_base_url"] = str(LLM_BASE_URLS.get(provider) or "")
            except Exception:
                pass
        llm_model = api_config.get("llm_model")
        if not isinstance(llm_model, dict):
            llm_model = {}
            api_config["llm_model"] = llm_model
    payload["adapter_catalog"] = _adapter_catalog()
    return payload


def _contains_quotes(value: str) -> bool:
    return '"' in value or "'" in value


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _provider_map_value(mapping: dict[str, str], provider: str) -> str:
    return str((mapping or {}).get(provider, "") or "").strip()


def _normalize_tts_provider(value: str) -> str:
    raw = str(value or "").strip()
    low = raw.lower()
    if low in {"none", "off", "disable", "disabled", "不使用"}:
        return "none"
    legacy = {
        "genie tts": "genie-tts",
        "gpt sovits": "gpt-sovits",
        "gpt-sovits": "gpt-sovits",
    }
    return legacy.get(low, low or "gpt-sovits")


def _normalize_t2i_provider(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "comfyui"
    try:
        from t2i.t2i_manager import T2IAdapterFactory

        low = raw.lower()
        for key in T2IAdapterFactory._adapters:
            if key.lower() == low:
                return key
    except Exception:
        pass
    return raw


def _validate_api_config_for_save(config: Any) -> None:
    provider = str(config.llm_provider or "").strip()
    base_url = str(config.llm_base_url or "").strip()
    api_key = _provider_map_value(config.llm_api_key, provider)
    model = _provider_map_value(config.llm_model, provider)
    if not provider or not base_url or not api_key or not model:
        raise ValueError("服务商、基础地址、API Key 和模型 ID 都需要填写。")
    if _contains_quotes(base_url):
        raise ValueError("LLM API 基础网址不能包含引号。")

    tts_provider = _normalize_tts_provider(config.tts_provider)
    if tts_provider not in {"gpt-sovits", "genie-tts"}:
        return

    tts_url = str(config.gpt_sovits_url or "").strip()
    tts_path = str(config.gpt_sovits_api_path or "").strip()
    if not tts_url or not tts_path:
        raise ValueError("当前 TTS 引擎需要填写 URL 和服务启动路径。")
    if _contains_quotes(tts_url) or _contains_quotes(tts_path):
        raise ValueError("TTS URL 和服务启动路径不能包含引号。")
    if not _is_http_url(tts_url):
        raise ValueError("TTS URL 必须是有效的 http(s) URL。")
    if not Path(tts_path).expanduser().is_dir():
        raise ValueError("TTS 服务启动路径必须是已存在的目录。")


def _save_api_config(state: BridgeState, payload: dict[str, Any]) -> Any:
    config = ApiConfig.model_validate(payload).model_copy(deep=True)
    config.tts_provider = _normalize_tts_provider(config.tts_provider)
    config.t2i_provider = _normalize_t2i_provider(config.t2i_provider)
    _validate_api_config_for_save(config)
    state.config_manager.config.api_config = config
    state.config_manager.save_api_config()
    return config


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get_task(state: BridgeState, task_id: str) -> dict[str, Any]:
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        return dict(task)


def _create_task(state: BridgeState, *, kind: str, title: str, message: str = "") -> dict[str, Any]:
    task_id = uuid.uuid4().hex
    now = _now_ms()
    task = {
        "createdAt": now,
        "error": "",
        "id": task_id,
        "kind": kind,
        "logs": [],
        "message": message,
        "phase": "queued",
        "progress": 0,
        "result": None,
        "status": "queued",
        "title": title,
        "updatedAt": now,
    }
    with state.task_lock:
        state.tasks[task_id] = task
    return dict(task)


def _update_task(state: BridgeState, task_id: str, **changes: Any) -> dict[str, Any]:
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        task.update(changes)
        task["updatedAt"] = _now_ms()
        return dict(task)


def _append_task_log(state: BridgeState, task_id: str, line: str, *, limit: int = 120) -> None:
    text = str(line).strip()
    if not text:
        return
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            return
        logs = list(task.get("logs") or [])
        logs.append(text)
        task["logs"] = logs[-limit:]
        task["updatedAt"] = _now_ms()


def _run_background_task(state: BridgeState, task_id: str, worker: Any) -> None:
    try:
        _update_task(state, task_id, phase="running", status="running")
        result = worker()
        _update_task(
            state,
            task_id,
            message="任务完成。",
            phase="completed",
            progress=1,
            result=result,
            status="succeeded",
        )
    except Exception as exc:
        _update_task(
            state,
            task_id,
            error=str(exc),
            message=str(exc) or exc.__class__.__name__,
            phase="failed",
            status="failed",
        )


def _is_running_task(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "") in {"queued", "running"}


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


def _template_dir(state: BridgeState) -> Path:
    path = Path(state.template_dir_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _template_id(path: Path) -> str:
    return path.name


def _compose_stored_template(scenario: str, system: str) -> str:
    a = (scenario or "").replace("\r\n", "\n").rstrip()
    b = (system or "").replace("\r\n", "\n").rstrip()
    return f"{MARK_SCENARIO}\n{a}\n{MARK_SYSTEM}\n{b}\n"


def _parse_stored_template(raw: str) -> tuple[str, str]:
    text = (raw or "").replace("\r\n", "\n")
    if MARK_SCENARIO in text and MARK_SYSTEM in text:
        try:
            i = text.index(MARK_SCENARIO) + len(MARK_SCENARIO)
            j = text.index(MARK_SYSTEM, i)
            return text[i:j].strip("\n"), text[j + len(MARK_SYSTEM) :].strip("\n")
        except ValueError:
            pass
    text = text.strip()
    return (text, "") if text else ("", "")


def _compose_for_llm(scenario: str, system: str) -> str:
    a = (scenario or "").strip()
    b = (system or "").strip()
    if a and b:
        return f"{a}\n\n{b}"
    return a or b


def _history_id_from_scenario(user_scenario: str, system_template: str) -> str:
    stable = (user_scenario or "").strip() or (system_template or "").strip()
    return hashlib.md5(stable.encode("utf-8")).hexdigest()


def _latest_history_json(history_dir: str) -> Path | None:
    path = Path(history_dir)
    if not path.is_dir():
        return None
    files = [item for item in path.glob("*.json") if item.is_file()]
    if not files:
        return None
    return max(files, key=lambda item: item.stat().st_mtime)


def _read_split_meta(template_dir: Path) -> tuple[str, str] | None:
    meta_path = template_dir / TEMP_SPLIT_META
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    scenario = data.get("scenario", "")
    system = data.get("system", "")
    if not isinstance(scenario, str):
        scenario = ""
    if not isinstance(system, str):
        system = ""
    if scenario.strip() or system.strip():
        return scenario, system
    return None


def _resume_template_parts(state: BridgeState) -> tuple[str, str, str] | None:
    template_dir = _template_dir(state)
    temp_path = template_dir / "_temp.txt"
    if temp_path.is_file() and temp_path.stat().st_size > 0:
        split_meta = _read_split_meta(template_dir)
        if split_meta is not None:
            if _has_untranslated_template_keys(split_meta[0], split_meta[1]):
                from ui.settings_ui.services.template_tab_session import load_template_session

                repaired = _repair_template_session_if_needed(state, load_template_session(state.template_dir_path))
                if repaired:
                    return (
                        str(repaired.get("scenario_text") or ""),
                        str(repaired.get("system_template_text") or ""),
                        "_temp.txt",
                    )
            return split_meta[0], split_meta[1], "_temp.txt"
        try:
            scenario, system = _parse_stored_template(temp_path.read_text(encoding="utf-8"))
        except OSError:
            scenario, system = "", ""
        if scenario.strip() or system.strip():
            return scenario, system, "_temp.txt"

    candidates = [item for item in template_dir.glob("*.txt") if item.is_file() and item.name != "_temp.txt"]
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        scenario, system = _parse_stored_template(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if scenario.strip() or system.strip():
        return scenario, system, path.name
    return None


def _release_root() -> Path:
    if os.environ.get("EASYAI_PROJECT_ROOT"):
        return Path(os.environ["EASYAI_PROJECT_ROOT"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent


def _frontend_dist_root(state: BridgeState) -> Path | None:
    raw = str(state.frontend_dist_dir or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _schedule_browser_open(url: str) -> None:
    def _open() -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"Could not open browser automatically: {exc}")

    timer = threading.Timer(0.35, _open)
    timer.daemon = True
    timer.start()


def _launch_chat(
    state: BridgeState,
    *,
    history_file: str,
    init_sprite_path: str,
    room_id: str,
    selected_bg: str,
    system_template: str,
    use_cg: bool,
    user_scenario: str,
) -> str:
    global _main_chat_process

    template = _compose_for_llm(user_scenario, system_template)
    template_dir = _template_dir(state)
    (template_dir / "_temp.txt").write_text(template, encoding="utf-8")
    (template_dir / TEMP_SPLIT_META).write_text(
        json.dumps({"scenario": user_scenario, "system": system_template}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sc = state.config_manager.config.system_config.model_copy(deep=True)
    sc.live_room_id = room_id
    state.config_manager.config.system_config = sc
    state.config_manager.save_system_config()

    if _main_chat_process is not None and _main_chat_process.poll() is None:
        return f"进程已经在运行中！PID: {_main_chat_process.pid}"

    template_hash = _history_id_from_scenario(user_scenario, system_template)
    history_path = Path(history_file) if history_file else Path(state.history_dir) / f"{template_hash}.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    root = _release_root()
    tts_slug = str(state.config_manager.config.api_config.tts_provider or "gpt-sovits").strip() or "gpt-sovits"
    args = [
        "--template=_temp",
        f"--init_sprite_path={init_sprite_path or ''}",
        f"--history={history_path.resolve()}",
        f"--bg={selected_bg}",
        f"--t2i={'ComfyUI' if use_cg else ''}",
        f"--room_id={room_id}",
        f"--tts={tts_slug}",
    ]

    if getattr(sys, "frozen", False):
        candidates = [root / "main" / "main.exe", root / "main.exe"]
        exe = next((item for item in candidates if item.is_file()), None)
        if exe is None:
            checked = " 与 ".join(str(item) for item in candidates)
            return f"启动失败: 未找到 main.exe（已检查 {checked}）。"
        _main_chat_process = subprocess.Popen([str(exe)] + args, cwd=str(root))
    else:
        main_py = root / "main.py"
        if not main_py.is_file():
            return f"启动失败: 未找到 main.py（已检查 {main_py}）。"
        _main_chat_process = subprocess.Popen([sys.executable, str(main_py)] + args, cwd=str(root))
    return f"聊天进程已启动！PID: {_main_chat_process.pid}"


def _list_templates(state: BridgeState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(_template_dir(state).glob("*.txt"), key=lambda item: item.name.lower()):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        scenario, system = _parse_stored_template(raw)
        rows.append(
            {
                "content": _compose_for_llm(scenario, system),
                "id": _template_id(path),
                "name": path.stem,
                "path": path.as_posix(),
                "scenario": scenario,
                "system": system,
                "updatedAt": str(int(path.stat().st_mtime)),
            }
        )
    return rows


def _save_template_summary(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    template = payload.get("template", payload)
    if not isinstance(template, dict):
        raise ValueError("template payload must be an object")
    name = str(template.get("name") or template.get("id") or "").strip()
    if not name:
        raise ValueError("template name is required")
    scenario = str(template.get("scenario") or template.get("content") or "")
    system = str(template.get("system") or "")
    file_name = name if name.endswith(".txt") else f"{name}.txt"
    (_template_dir(state) / file_name).write_text(_compose_stored_template(scenario, system), encoding="utf-8")
    file_name = f"{name}.txt" if not name.endswith(".txt") else name
    for row in _list_templates(state):
        if row["id"] == file_name:
            return row
    raise RuntimeError("template was saved but not found")


def _generate_template_summary(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    selected = payload.get("characters") or []
    if not isinstance(selected, list):
        raise ValueError("characters must be a list")
    background = str(payload.get("backgroundName") or "")
    voice_language = str(payload.get("voiceLanguage") or "").strip()
    if voice_language:
        sc = state.config_manager.config.system_config.model_copy(deep=True)
        sc.voice_language = voice_language
        state.config_manager.config.system_config = sc
        state.config_manager.save_system_config()
    max_speech_chars = max(0, int(payload.get("maxSpeechChars") or 0))
    max_dialog_items = max(0, int(payload.get("maxDialogItems") or 0))
    content, result = state.template_generator.generate_chat_template(
        selected,
        background,
        bool(payload.get("useEffect", True)),
        bool(payload.get("useCg", False)),
        bool(payload.get("useTranslation", True)),
        bool(payload.get("useCot", False)),
        bool(payload.get("useChoice", True)),
        bool(payload.get("useNarration", True)),
        bool(payload.get("useStat", True)),
        max_speech_chars=max_speech_chars,
        max_dialog_items=max_dialog_items,
    )
    output_name = str(result or "").strip()
    name = str(output_name or payload.get("name") or "generated").strip()
    scenario = str(payload.get("scenario") or "")
    row = {
        "content": _compose_for_llm(scenario, content),
        "id": "",
        "name": name,
        "path": "",
        "scenario": scenario,
        "system": content,
        "updatedAt": "",
    }
    row["generationMessage"] = result
    return row


def _safe_session_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _template_session_to_frontend(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    return {
        "background": str(raw.get("background") or ""),
        "filenameStub": str(raw.get("filename_stub") or ""),
        "historyPath": str(raw.get("history_file") or ""),
        "initSpritePath": str(raw.get("init_sprite_path") or ""),
        "maxDialogItems": _safe_session_int(raw.get("max_dialog_items")),
        "maxSpeechChars": _safe_session_int(raw.get("max_speech_chars")),
        "roomId": str(raw.get("room_id") or ""),
        "scenario": str(raw.get("scenario_text") or ""),
        "selectedCharacters": [str(item) for item in (raw.get("selected_characters") or []) if str(item)],
        "system": str(raw.get("system_template_text") or ""),
        "templateFileDropdown": str(raw.get("template_file_dropdown") or ""),
        "useCg": bool(raw.get("use_cg_yes", False)),
        "useChoice": bool(raw.get("use_choice_yes", True)),
        "useCot": bool(raw.get("use_cot_yes", False)),
        "useEffect": bool(raw.get("use_effect_yes", True)),
        "useNarration": bool(raw.get("use_narration_yes", True)),
        "useStat": bool(raw.get("use_stat_yes", True)),
        "useTranslation": bool(raw.get("use_tr_yes", True)),
        "voiceLanguage": str(raw.get("voice_lang") or ""),
    }


def _load_template_session_payload(state: BridgeState) -> dict[str, Any] | None:
    from ui.settings_ui.services.template_tab_session import load_template_session

    raw = load_template_session(state.template_dir_path)
    raw = _repair_template_session_if_needed(state, raw)
    return _template_session_to_frontend(raw)


def _save_template_session_payload(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.services.template_tab_session import save_template_session

    data = {
        "selected_characters": payload.get("selectedCharacters") or [],
        "background": str(payload.get("background") or ""),
        "voice_lang": str(payload.get("voiceLanguage") or ""),
        "use_effect_yes": bool(payload.get("useEffect", True)),
        "use_tr_yes": bool(payload.get("useTranslation", True)),
        "use_cg_yes": bool(payload.get("useCg", False)),
        "use_cot_yes": bool(payload.get("useCot", False)),
        "use_choice_yes": bool(payload.get("useChoice", True)),
        "use_narration_yes": bool(payload.get("useNarration", True)),
        "use_stat_yes": bool(payload.get("useStat", True)),
        "max_speech_chars": _safe_session_int(payload.get("maxSpeechChars")),
        "max_dialog_items": _safe_session_int(payload.get("maxDialogItems")),
        "scenario_text": str(payload.get("scenario") or ""),
        "system_template_text": str(payload.get("system") or ""),
        "filename_stub": str(payload.get("filenameStub") or ""),
        "template_file_dropdown": str(payload.get("templateFileDropdown") or ""),
        "init_sprite_path": str(payload.get("initSpritePath") or ""),
        "history_file": str(payload.get("historyPath") or ""),
        "room_id": str(payload.get("roomId") or ""),
    }
    save_template_session(state.template_dir_path, data)
    loaded = _load_template_session_payload(state)
    if loaded is None:
        raise RuntimeError("template session was saved but not found")
    return loaded


def _has_untranslated_template_keys(*values: Any) -> bool:
    return any("template_gen." in str(value or "") for value in values)


def _repair_template_session_if_needed(state: BridgeState, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw or not _has_untranslated_template_keys(raw.get("scenario_text"), raw.get("system_template_text")):
        return raw
    selected = raw.get("selected_characters") or []
    if not isinstance(selected, list) or not selected:
        return raw
    content, _result = state.template_generator.generate_chat_template(
        [str(item) for item in selected if str(item)],
        str(raw.get("background") or ""),
        bool(raw.get("use_effect_yes", True)),
        bool(raw.get("use_cg_yes", False)),
        bool(raw.get("use_tr_yes", True)),
        bool(raw.get("use_cot_yes", False)),
        bool(raw.get("use_choice_yes", True)),
        bool(raw.get("use_narration_yes", True)),
        bool(raw.get("use_stat_yes", True)),
        max_speech_chars=_safe_session_int(raw.get("max_speech_chars")),
        max_dialog_items=_safe_session_int(raw.get("max_dialog_items")),
    )
    repaired = dict(raw)
    if _has_untranslated_template_keys(repaired.get("scenario_text")):
        repaired["scenario_text"] = ""
    repaired["system_template_text"] = content
    try:
        from ui.settings_ui.services.template_tab_session import save_template_session

        save_template_session(state.template_dir_path, repaired)
    except Exception:
        pass
    return repaired


def _extract_prompt_from_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    match = re.match(r"^[^:]+[:：]\s*(.+)$", text)
    if match:
        return match.group(1).strip()
    return text


def _sprite_output_dir(state: BridgeState, character_name: str, requested: Any = "") -> Path:
    raw = str(requested or "").strip()
    if raw:
        return Path(raw)
    character = state.config_manager.get_character_by_name(character_name)
    if character is None:
        raise KeyError(f"character not found: {character_name}")
    return Path("data/sprite") / str(character.sprite_prefix or character.name or "sprites")


def _generate_sprite_prompts(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.generate_sprites import ImageGenerator

    character_name = str(payload.get("characterName") or "").strip()
    if not character_name:
        raise ValueError("characterName is required")
    count = int(payload.get("count") or 1)
    if count < 1 or count > 100:
        raise ValueError("count must be between 1 and 100")
    character = state.config_manager.get_character_by_name(character_name)
    if character is None:
        raise KeyError(f"character not found: {character_name}")

    _update_task(state, task_id, message="正在生成立绘提示词。", phase="prompt", progress=0.18)
    prompts = ImageGenerator().generate_prompts(count, str(character.character_setting or ""))
    result = {"prompts": [str(item) for item in prompts]}
    _update_task(state, task_id, message="提示词已生成。", phase="completed", progress=1, result=result)
    return result


def _generate_sprites(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.generate_sprites import ImageGenerator

    character_name = str(payload.get("characterName") or "").strip()
    if not character_name:
        raise ValueError("characterName is required")
    reference = Path(str(payload.get("referenceImage") or "").strip())
    if not reference.is_file():
        raise ValueError("referenceImage must point to an existing file")
    raw_prompts = payload.get("prompts") or []
    if isinstance(raw_prompts, str):
        prompts = [_extract_prompt_from_line(line) for line in raw_prompts.splitlines()]
    elif isinstance(raw_prompts, list):
        prompts = [_extract_prompt_from_line(str(item)) for item in raw_prompts]
    else:
        raise ValueError("prompts must be a list or string")
    prompts = [item for item in prompts if item]
    if not prompts:
        raise ValueError("at least one prompt is required")

    output_dir = _sprite_output_dir(state, character_name, payload.get("outputDir"))
    _update_task(state, task_id, message="正在批量生成立绘。", phase="generate", progress=0.12)
    files = ImageGenerator().batch_generate_sprites(reference, prompts, output_dir)
    paths = [Path(item).as_posix() for item in files if item and Path(item).is_file()]
    result = {
        "files": paths,
        "message": f"已生成 {len(paths)} 张（输出目录: {output_dir.as_posix()}）",
        "outputDir": output_dir.as_posix(),
    }
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _crop_sprites(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.crop_sprite import batch_crop_upper_half

    input_dir = Path(str(payload.get("inputDir") or "").strip())
    ratio = float(payload.get("ratio") or 1.0)
    requested_output = str(payload.get("outputDir") or "").strip()
    output_dir = Path(requested_output) if requested_output else input_dir / f"cropped_upper_{ratio}"

    _update_task(state, task_id, message="正在批量裁剪立绘。", phase="crop", progress=0.25)
    message = batch_crop_upper_half(ratio, input_dir.as_posix(), requested_output or None)
    result = {"message": str(message), "outputDir": output_dir.as_posix()}
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _remove_sprite_background(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tools.remove_bg import batch_remove_background

    input_dir = Path(str(payload.get("inputDir") or "").strip())
    requested_output = str(payload.get("outputDir") or "").strip()
    output_dir = Path(requested_output) if requested_output else input_dir / "removed_backgrounds"

    _update_task(state, task_id, message="正在批量抠出立绘。", phase="remove-background", progress=0.25)
    message = batch_remove_background(input_dir.as_posix(), requested_output or None)
    result = {"message": str(message), "outputDir": output_dir.as_posix()}
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _llm_model_provider_kind(provider: str, base_url: str) -> str:
    low_provider = provider.strip().lower()
    low_base = base_url.strip().lower()
    if "gemini" in low_provider or "generativelanguage.googleapis.com" in low_base:
        return "gemini"
    if "deepseek" in low_provider or "api.deepseek.com" in low_base:
        return "deepseek"
    if low_provider == "claude" or "claude" in low_provider or "anthropic.com" in low_base:
        return "anthropic"
    if (
        "dashscope.aliyuncs.com" in low_base
        or "通义" in low_provider
        or "qwen" in low_provider
        or "dashscope" in low_provider
    ):
        return "dashscope"
    return "openai_compatible"


def _openai_models_endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    if base.lower().endswith("/models"):
        return base
    return f"{base}/models"


def _llm_models_endpoint(provider: str, base_url: str, api_key: str) -> str:
    kind = _llm_model_provider_kind(provider, base_url)
    base = base_url.strip().rstrip("/")
    if kind == "gemini" and "generativelanguage.googleapis.com" in base.lower():
        marker_ix = base.lower().rfind("/openai")
        if marker_ix >= 0:
            base = base[:marker_ix]
        if not base.lower().endswith("/v1beta"):
            base = "https://generativelanguage.googleapis.com/v1beta"
        return f"{base}/models?{urllib.parse.urlencode({'key': api_key.strip()})}"
    if kind == "deepseek" and "api.deepseek.com" in base.lower() and base.lower().endswith("/v1"):
        base = base[:-3]
    if kind == "dashscope":
        low_base = base.lower()
        query = urllib.parse.urlencode(
            {"page_no": 1, "page_size": 100, "version": "v1.0", "model_source": "base"}
        )
        if low_base.endswith("/compatible-mode/v1"):
            base = base[: -len("/compatible-mode/v1")] + "/api/v1"
        if base.lower().endswith("/api/v1"):
            return f"{base}/deployments/models?{query}"
    return _openai_models_endpoint(base)


def _llm_model_request_headers(provider: str, base_url: str, api_key: str) -> dict[str, str]:
    key = api_key.strip()
    if not key:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": _MODEL_REQUEST_USER_AGENT,
    }
    kind = _llm_model_provider_kind(provider, base_url)
    if kind == "gemini" and "generativelanguage.googleapis.com" in base_url.lower():
        return headers
    if kind == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        headers["Content-Type"] = "application/json"
        return headers
    headers["Authorization"] = f"Bearer {key}"
    if kind == "dashscope":
        headers["Content-Type"] = "application/json"
    return headers


def _iter_llm_model_items(payload: Any):
    if isinstance(payload, list):
        yield from payload
        return
    if not isinstance(payload, dict):
        return
    for key in ("data", "models", "items", "deployments"):
        raw = payload.get(key)
        if isinstance(raw, list):
            yield from raw
        elif isinstance(raw, dict):
            yield from _iter_llm_model_items(raw)
    for key in ("output", "result"):
        raw = payload.get(key)
        if isinstance(raw, (dict, list)):
            yield from _iter_llm_model_items(raw)


def _llm_model_id_is_image_only(model_id: str) -> bool:
    low = model_id.strip().removeprefix("models/").lower()
    if any(marker in low for marker in _IMAGE_ONLY_MODEL_MARKERS):
        return True
    parts = [part for part in low.replace("_", "-").replace(".", "-").split("-") if part]
    return "image" in parts and (
        "generation" in parts or "preview" in parts or low.startswith("gemini-")
    )


def _llm_model_item_supports_chat(item: dict[str, Any]) -> bool:
    actions = item.get("supportedGenerationMethods") or item.get("supportedActions")
    if isinstance(actions, list):
        normalized = {str(action).strip().lower() for action in actions}
        return bool({"generatecontent", "chat.completions", "chat"} & normalized)
    endpoints = item.get("supported_endpoint_types") or item.get("supportedEndpointTypes")
    if isinstance(endpoints, list):
        normalized = {str(endpoint).strip().lower() for endpoint in endpoints}
        if any("chat" in endpoint or endpoint == "responses" for endpoint in normalized):
            return True
        if any("image" in endpoint for endpoint in normalized):
            return False
    return True


def _modalities_to_tags(input_modalities: Any, output_modalities: Any) -> list[str]:
    def _as_set(raw: Any) -> set[str]:
        if isinstance(raw, list):
            return {str(item).strip().lower() for item in raw if str(item).strip()}
        if isinstance(raw, str) and raw.strip():
            return {
                part.strip().lower()
                for part in raw.replace("+", ",").replace("->", ",").split(",")
                if part.strip()
            }
        return set()

    inputs = _as_set(input_modalities)
    outputs = _as_set(output_modalities)
    tags: list[str] = []
    if "text" in outputs or "text" in inputs or not outputs:
        tags.append("text")
    if "image" in inputs:
        tags.append("vision")
    if "file" in inputs:
        tags.append("file")
    if "audio" in inputs:
        tags.append("audio")
    if "video" in inputs:
        tags.append("video")
    if "image" in outputs:
        tags.append("image_out")
    out: list[str] = []
    for tag in tags or ["unknown"]:
        if tag not in out:
            out.append(tag)
    return out


def _llm_model_option_from_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        model_id = item.strip()
        if not model_id or _llm_model_id_is_image_only(model_id):
            return None
        return {"id": model_id, "tags": ["text"]}
    if not isinstance(item, dict) or not _llm_model_item_supports_chat(item):
        return None
    model_id = ""
    for key in ("id", "model", "model_id", "modelId", "model_name", "modelName", "name", "deployed_model", "base_model"):
        model_id = str(item.get(key) or "").strip()
        if model_id:
            break
    if model_id.startswith("models/"):
        model_id = model_id.split("/", 1)[1].strip()
    if not model_id or _llm_model_id_is_image_only(model_id):
        return None
    arch = item.get("architecture")
    arch = arch if isinstance(arch, dict) else {}
    tags = _modalities_to_tags(arch.get("input_modalities"), arch.get("output_modalities"))
    return {"id": model_id, "tags": tags}


def _fetch_llm_models(payload: dict[str, Any]) -> list[dict[str, Any]]:
    provider = str(payload.get("provider") or "").strip()
    base_url = str(payload.get("baseUrl") or "").strip()
    api_key = str(payload.get("apiKey") or "").strip()
    if not base_url or not api_key:
        raise ValueError("请先填写 LLM 基础地址和 API Key。")
    endpoint = _llm_models_endpoint(provider, base_url, api_key)
    headers = _llm_model_request_headers(provider, base_url, api_key)
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response: {exc}") from exc
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _iter_llm_model_items(data):
        option = _llm_model_option_from_item(item)
        if option is None or option["id"] in seen:
            continue
        seen.add(option["id"])
        out.append(option)
    return out


def _display_path(path: Path) -> str:
    return path.resolve(strict=False).as_posix()


def _filesystem_roots(project_root: Path) -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, path: Path) -> None:
        try:
            resolved = path.resolve(strict=False)
        except Exception:
            return
        if not resolved.exists():
            return
        value = resolved.as_posix()
        key = value.lower() if os.name == "nt" else value
        if key in seen:
            return
        seen.add(key)
        roots.append({"label": label, "path": value})

    add("Shinsekai", project_root)
    add("Data", project_root / "data")
    add("Home", Path.home())

    anchor = project_root.resolve(strict=False).anchor
    if anchor:
        add(anchor, Path(anchor))

    if os.name == "nt":
        for code in range(ord("A"), ord("Z") + 1):
            drive = Path(f"{chr(code)}:/")
            if drive.exists():
                add(f"{chr(code)}:", drive)

    return roots


def _browse_local_files(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(payload.get("path") or "").strip()
    show_hidden = bool(payload.get("showHidden"))
    root_raw = os.environ.get("EASYAI_PROJECT_ROOT") or str(Path.cwd())
    project_root = Path(root_raw).expanduser().resolve(strict=False)
    target = Path(raw_path).expanduser() if raw_path else project_root
    if not target.is_absolute():
        target = project_root / target

    try:
        target = target.resolve(strict=False)
    except Exception:
        pass

    if target.exists() and target.is_file():
        target = target.parent

    if not target.exists():
        raise FileNotFoundError(f"路径不存在: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是目录: {target}")

    entries: list[dict[str, Any]] = []
    try:
        children = list(target.iterdir())
    except PermissionError:
        raise
    except OSError as exc:
        raise RuntimeError(f"无法读取目录: {target}: {exc}") from exc

    for child in children:
        name = child.name
        if not show_hidden and name.startswith("."):
            continue
        try:
            item_stat = child.stat()
            is_dir = child.is_dir()
        except OSError:
            continue
        entries.append(
            {
                "kind": "directory" if is_dir else "file",
                "modifiedAt": item_stat.st_mtime,
                "name": name,
                "path": _display_path(child),
                "size": None if is_dir else item_stat.st_size,
            }
        )

    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
    parent = target.parent if target.parent != target else None
    return {
        "cwd": _display_path(target),
        "entries": entries,
        "parent": _display_path(parent) if parent is not None else "",
        "roots": _filesystem_roots(project_root),
    }


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


def _resolve_loaded_plugin_for_manifest_entry(entry: str, manager: Any | None) -> Any | None:
    if manager is None:
        return None
    raw = entry.strip()
    try:
        plugins = manager.plugins
    except Exception:
        return None
    for plugin in plugins:
        cls = plugin.__class__
        full = f"{cls.__module__}:{cls.__qualname__}"
        if full == raw:
            return plugin
        if ":" not in raw and cls.__module__ == raw:
            return plugin
    return None


def _display_title_for_offline_plugin_entry(entry: str) -> str:
    value = entry.strip()
    if ":" in value:
        return value.rpartition(":")[2]
    return value.rpartition(".")[2] if "." in value else value


def _plugin_rows() -> list[dict[str, Any]]:
    try:
        from core.plugins.plugin_host import (
            collect_chat_ui_contributions,
            collect_settings_contributions,
            collect_tools_tab_contributions,
            get_plugin_manager,
            infer_plugin_package_directory,
            read_plugin_manifest_items,
        )
    except Exception:
        return []

    manager = get_plugin_manager()
    settings_by_plugin: dict[str, list[str]] = {}
    tools_by_plugin: dict[str, list[str]] = {}
    chat_by_plugin: dict[str, list[str]] = {}
    for contribution in collect_settings_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        label = str(getattr(contribution, "nav_label", "") or "").strip()
        if plugin_id and label:
            settings_by_plugin.setdefault(plugin_id, []).append(label)
    for contribution in collect_tools_tab_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        label = str(getattr(contribution, "title", "") or "").strip()
        if plugin_id and label:
            tools_by_plugin.setdefault(plugin_id, []).append(label)
    for contribution in collect_chat_ui_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        placement = str(getattr(contribution, "placement", "") or "").strip()
        if plugin_id and placement:
            chat_by_plugin.setdefault(plugin_id, []).append(placement)

    def _row(
        *,
        author: str,
        description: str,
        enabled: bool,
        entry: str,
        permissions: list[Any] | None,
        plugin_id: str,
        title: str,
        version: str,
        directory: str = "",
        load_error: str = "",
        loaded: bool = True,
    ) -> dict[str, Any]:
        settings_pages = settings_by_plugin.get(plugin_id, [])
        tools_tabs = tools_by_plugin.get(plugin_id, [])
        slots: set[str] = set()
        if settings_pages:
            slots.add("settings-extension")
        if tools_tabs:
            slots.add("settings-tools")
        if chat_by_plugin.get(plugin_id):
            slots.add("chat-output")
        if not slots:
            slots.add("settings-extension")
        return {
            "author": author,
            "description": description,
            "directory": directory,
            "enabled": enabled,
            "entry": entry,
            "id": plugin_id,
            "loadError": load_error,
            "loaded": loaded,
            "permissions": list(permissions or []),
            "settingsPages": settings_pages,
            "slots": sorted(slots),
            "title": title,
            "toolsTabs": tools_tabs,
            "version": version,
        }

    rows: list[dict[str, Any]] = []
    seen_plugin_ids: set[str] = set()
    manifest_items = read_plugin_manifest_items()
    if manifest_items:
        for item in manifest_items:
            entry = str(item.get("entry") or "").strip()
            if not entry:
                continue
            plugin = _resolve_loaded_plugin_for_manifest_entry(entry, manager)
            enabled = bool(item.get("enabled", True))
            if plugin is not None:
                plugin_id = str(plugin.plugin_id)
                seen_plugin_ids.add(plugin_id)
                version = str(plugin.plugin_version)
                title = str(plugin.plugin_name).strip() or plugin_id
                description = str(plugin.plugin_description or "").strip()
                author = str(plugin.plugin_author or "").strip()
                loaded = True
                load_error = ""
            else:
                plugin_id = entry
                version = "—"
                title = _display_title_for_offline_plugin_entry(entry)
                description = ""
                author = ""
                loaded = False
                load_error = "插件配置已启用，但插件代码未安装或导入失败。" if enabled else ""
            slots = set(str(slot) for slot in (item.get("slots") or []) if str(slot).strip())
            directory = infer_plugin_package_directory(entry)
            row = _row(
                author=author,
                description=description,
                directory=directory.as_posix() if directory is not None else "",
                enabled=enabled,
                entry=entry,
                load_error=load_error,
                loaded=loaded,
                permissions=list(item.get("permissions") or []),
                plugin_id=plugin_id,
                title=title,
                version=version,
            )
            if slots:
                row["slots"] = sorted(set(row["slots"]) | slots)
            rows.append(row)
    else:
        for plugin in getattr(manager, "plugins", []) if manager is not None else []:
            plugin_id = str(plugin.plugin_id)
            seen_plugin_ids.add(plugin_id)
            rows.append(
                _row(
                    author=str(plugin.plugin_author or "").strip(),
                    description=str(plugin.plugin_description or "").strip(),
                    directory="",
                    enabled=True,
                    entry="",
                    permissions=[],
                    plugin_id=plugin_id,
                    title=str(plugin.plugin_name).strip() or plugin_id,
                    version=str(plugin.plugin_version),
                )
            )
        for key in sorted(set(settings_by_plugin.keys()) | set(tools_by_plugin.keys())):
            if key in seen_plugin_ids:
                continue
            label = key
            if key.startswith("_:"):
                labels = settings_by_plugin.get(key) or tools_by_plugin.get(key) or [key]
                label = labels[0]
            rows.append(
                _row(
                    author="",
                    description="",
                    directory="",
                    enabled=True,
                    entry="",
                    permissions=[],
                    plugin_id=key,
                    title=label,
                    version="",
                )
            )
    return rows


def _plugin_registry_rows() -> list[dict[str, Any]]:
    from core.plugins.registry_catalog import fetch_registry_plugins
    from core.plugins.registry_download import load_downloaded_repos, normalize_manifest_entry, normalize_repo_slug

    installed_entries = {
        normalize_manifest_entry(str(row.get("entry") or row.get("id") or ""))
        for row in _plugin_rows()
        if str(row.get("entry") or row.get("id") or "").strip()
    }
    downloaded_repos = load_downloaded_repos()
    rows: list[dict[str, Any]] = []
    for rec in fetch_registry_plugins():
        entry = str(rec.entry or "").strip()
        repo = str(rec.repo or "").strip()
        norm_entry = normalize_manifest_entry(entry) if entry else ""
        norm_repo = normalize_repo_slug(repo)
        installed = bool(norm_entry and norm_entry in installed_entries)
        downloaded = bool(norm_repo and norm_repo in downloaded_repos)
        rows.append(
            {
                "author": str(rec.author or ""),
                "description": str(rec.description or ""),
                "downloaded": downloaded,
                "entry": entry,
                "installed": installed,
                "name": str(rec.name or repo),
                "repo": repo,
            }
        )
    return rows


def _app_update_info() -> dict[str, Any]:
    from core.plugins.github_bundle_update import default_app_github_repo_slug, read_local_version, resolve_project_root

    return {
        "repo": default_app_github_repo_slug(),
        "version": read_local_version(resolve_project_root()).strip(),
    }


def _app_update_tags() -> dict[str, Any]:
    from core.plugins.github_bundle_update import default_app_github_repo_slug, fetch_recent_tag_names

    slug = default_app_github_repo_slug().strip()
    if not slug or slug.count("/") < 1:
        raise ValueError("无法解析主程序 GitHub 仓库。")
    return {"tags": fetch_recent_tag_names(slug)}


def _repo_tags(payload: dict[str, Any]) -> dict[str, Any]:
    from core.plugins.github_bundle_update import fetch_recent_tag_names
    from core.plugins.registry_download import normalize_repo_slug

    slug = normalize_repo_slug(str(payload.get("repo") or ""))
    if not slug or slug.count("/") < 1:
        raise ValueError("repo is required")
    return {"tags": fetch_recent_tag_names(slug)}


def _run_app_update(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from core.plugins.github_bundle_update import (
        default_app_github_repo_slug,
        overwrite_merge_app_tree,
        read_local_version,
        resolve_project_root,
    )
    from core.plugins.plugin_requirements_install import install_plugin_requirements_txt
    from core.plugins.registry_download import format_download_error

    slug = default_app_github_repo_slug().strip()
    if not slug or slug.count("/") < 1:
        raise ValueError("无法解析主程序 GitHub 仓库。")
    ref_kind = str(payload.get("refKind") or "latest").strip()
    if ref_kind not in {"latest", "head", "tag"}:
        ref_kind = "latest"
    tag_name = str(payload.get("tagName") or "").strip()
    if ref_kind == "tag" and not tag_name:
        raise ValueError("请选择一个有效的 tag。")

    _update_task(state, task_id, message=f"正在下载 {slug} 源码归档。", phase="download", progress=0.05)

    def _progress(current: int, total: int | None) -> None:
        if total:
            ratio = min(max(current / total, 0), 1)
            progress = 0.05 + ratio * 0.58
            message = f"正在下载 {current}/{total} bytes。"
        else:
            progress = 0.2
            message = f"已下载 {current} bytes。"
        _update_task(state, task_id, message=message, phase="download", progress=round(progress, 4))

    def _phase(phase: str) -> None:
        if phase == "extract":
            _update_task(state, task_id, message="正在合并到程序目录。", phase="merge", progress=0.68)

    try:
        overwrite_merge_app_tree(
            slug,
            ref_kind,  # type: ignore[arg-type]
            tag_name,
            progress=_progress,
            on_phase=_phase,
        )
    except Exception as exc:
        raise RuntimeError(format_download_error(exc)) from exc

    _update_task(state, task_id, message="正在检查主程序 requirements.txt。", phase="pip", progress=0.88)

    def _pip_line(line: str) -> None:
        _append_task_log(state, task_id, line)

    pip_code, detail = install_plugin_requirements_txt(resolve_project_root(), on_output_line=_pip_line)
    if detail:
        _append_task_log(state, task_id, detail)
    version = read_local_version(resolve_project_root()).strip()
    result = {
        "detail": detail,
        "message": "文件已合并到当前目录。建议关闭本程序后重新启动以使代码生效。",
        "pipCode": pip_code,
        "version": version,
    }
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _set_plugin_enabled(plugin_id: str, enabled: bool) -> dict[str, Any]:
    from core.plugins.plugin_host import set_plugin_manifest_enabled

    if not set_plugin_manifest_enabled(plugin_id, enabled):
        raise KeyError(f"plugin not found: {plugin_id}")
    for row in _plugin_rows():
        if row["entry"] == plugin_id or row["id"] == plugin_id:
            return row
    raise KeyError(f"plugin not found: {plugin_id}")


def _uninstall_plugin(plugin_id: str) -> dict[str, Any]:
    from core.plugins.plugin_host import infer_plugin_package_directory, remove_plugin_manifest_entry
    from core.plugins.registry_download import unmark_repo_for_manifest_entry

    entry = plugin_id.strip()
    if not entry:
        raise ValueError("plugin id is required")
    row_title = entry
    for row in _plugin_rows():
        if row["entry"] == entry or row["id"] == entry:
            row_title = str(row.get("title") or entry)
            break
    if not remove_plugin_manifest_entry(entry):
        raise KeyError(f"plugin not found: {entry}")

    unmark_repo_for_manifest_entry(entry)

    folder_note = ""
    directory = infer_plugin_package_directory(entry)
    if directory is not None and directory.is_dir():
        plugins_root = Path("plugins").resolve()
        try:
            target = directory.resolve()
        except OSError as exc:
            folder_note = str(exc)
        else:
            if target == plugins_root or plugins_root not in target.parents:
                folder_note = f"跳过删除插件目录：{target.as_posix()}"
            else:
                try:
                    shutil.rmtree(target)
                except OSError as exc:
                    folder_note = str(exc)

    return {
        "folderNote": folder_note,
        "message": f"{row_title} 已从插件清单移除。重启后生效。",
    }


def _repo_slug_from_source(source: str) -> str:
    raw = source.strip()
    if raw.startswith("https://github.com/") or raw.startswith("http://github.com/"):
        raw = raw.split("github.com/", 1)[1]
    raw = raw.split("#", 1)[0].split("?", 1)[0].strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(parts) < 2:
        return ""
    return "/".join(parts[:2])


def _is_repo_source(source: str) -> bool:
    return bool(_repo_slug_from_source(source)) and ":" not in source


def _lookup_registry_plugin(source: str) -> Any | None:
    repo_slug = _repo_slug_from_source(source).lower()
    source_key = source.strip().lower()
    try:
        from core.plugins.registry_catalog import fetch_registry_plugins
        from core.plugins.registry_download import normalize_repo_slug
    except Exception:
        return None
    try:
        records = fetch_registry_plugins(timeout_sec=12)
    except Exception:
        return None
    for rec in records:
        rec_repo = normalize_repo_slug(rec.repo)
        if rec_repo and rec_repo == repo_slug:
            return rec
        if rec.name.strip().lower() == source_key:
            return rec
        if rec.entry.strip().lower() == source_key:
            return rec
    return None


def _plugin_class_from_file(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ""
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "PluginBase":
                return node.name
            if isinstance(base, ast.Attribute) and base.attr == "PluginBase":
                return node.name
    return ""


def _infer_plugin_entry(plugin_root: Path) -> str:
    package = plugin_root.name
    candidates = [plugin_root / "plugin.py", *sorted(plugin_root.glob("*/plugin.py"))]
    for path in candidates:
        if not path.is_file():
            continue
        class_name = _plugin_class_from_file(path)
        if not class_name:
            continue
        rel = path.relative_to(plugin_root).with_suffix("")
        module_parts = [package, *rel.parts]
        if all(part.isidentifier() for part in module_parts):
            return f"plugins.{'.'.join(module_parts)}:{class_name}"
    return ""


def _plugin_result_from_manifest(entry: str) -> dict[str, Any]:
    from core.plugins.plugin_host import append_plugin_manifest_entry_if_missing, normalize_manifest_entry

    append_plugin_manifest_entry_if_missing(entry, enabled=True)
    norm = normalize_manifest_entry(entry)
    return _set_plugin_enabled(norm, True)


def _synthetic_plugin_result(
    *,
    description: str,
    enabled: bool,
    plugin_id: str,
    title: str,
    version: str = "",
) -> dict[str, Any]:
    return {
        "author": "",
        "description": description,
        "directory": "",
        "enabled": enabled,
        "entry": plugin_id,
        "id": plugin_id,
        "loadError": "",
        "loaded": enabled,
        "permissions": [],
        "settingsPages": [],
        "slots": ["settings-extension"],
        "title": title,
        "toolsTabs": [],
        "version": version,
    }


def _as_str_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _mcp_config_response(data: dict[str, Any] | None = None) -> dict[str, Any]:
    from llm.tools.mcp_config_file import DEFAULT_MCP_CONFIG_PATH, read_mcp_config

    cfg = read_mcp_config(DEFAULT_MCP_CONFIG_PATH) if data is None else data
    servers: list[dict[str, Any]] = []
    for raw in cfg.get("servers") or []:
        if not isinstance(raw, dict):
            continue
        transport = str(raw.get("transport") or "sse").strip().lower()
        if transport not in {"sse", "stdio", "streamable_http"}:
            transport = "sse"
        entry: dict[str, Any] = {
            "enabled": raw.get("enabled") is not False,
            "name_prefix": str(raw.get("name_prefix") or ""),
            "transport": transport,
        }
        group = str(raw.get("group") or "").strip()
        if group:
            entry["group"] = group
        if raw.get("call_timeout") is not None:
            try:
                value = float(raw.get("call_timeout"))
                if value > 0:
                    entry["call_timeout"] = value
            except (TypeError, ValueError):
                pass
        if transport in {"sse", "streamable_http"}:
            entry["url"] = str(raw.get("url") or "")
            entry["headers"] = _as_str_map(raw.get("headers"))
        else:
            entry["command"] = str(raw.get("command") or "")
            entry["args"] = _as_str_list(raw.get("args"))
            entry["env"] = _as_str_map(raw.get("env"))
        servers.append(entry)
    try:
        default_timeout = float(cfg.get("default_call_timeout", 300))
    except (TypeError, ValueError):
        default_timeout = 300.0
    return {
        "default_call_timeout": default_timeout,
        "enabled": cfg.get("enabled") is not False,
        "path": DEFAULT_MCP_CONFIG_PATH.as_posix(),
        "servers": servers,
    }


def _validate_mcp_server(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("MCP server must be an object")
    transport = str(raw.get("transport") or "sse").strip().lower()
    if transport not in {"sse", "stdio", "streamable_http"}:
        raise ValueError(f"Unknown MCP transport: {transport!r}")
    entry: dict[str, Any] = {
        "enabled": raw.get("enabled") is not False,
        "name_prefix": str(raw.get("name_prefix") or "").strip(),
        "transport": transport,
    }
    group = str(raw.get("group") or "").strip()
    if group:
        entry["group"] = group
    if raw.get("call_timeout") not in (None, ""):
        try:
            timeout = float(raw.get("call_timeout"))
        except (TypeError, ValueError) as exc:
            raise ValueError("MCP call_timeout must be a number") from exc
        if timeout > 0:
            entry["call_timeout"] = timeout

    if transport in {"sse", "streamable_http"}:
        url = str(raw.get("url") or "").strip()
        if not url:
            raise ValueError("MCP HTTP server requires a URL")
        entry["url"] = url
        headers = raw.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("MCP headers must be an object")
        entry["headers"] = _as_str_map(headers)
    else:
        command = str(raw.get("command") or "").strip()
        if not command:
            raise ValueError("MCP stdio server requires a command")
        args = raw.get("args")
        env = raw.get("env")
        if args is not None and not isinstance(args, list):
            raise ValueError("MCP stdio args must be an array")
        if env is not None and not isinstance(env, dict):
            raise ValueError("MCP stdio env must be an object")
        entry["command"] = command
        entry["args"] = _as_str_list(args)
        entry["env"] = _as_str_map(env)
    return entry


def _validate_mcp_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = payload.get("config", payload)
    if not isinstance(cfg, dict):
        raise ValueError("MCP config payload must be an object")
    try:
        default_timeout = float(cfg.get("default_call_timeout", 300))
    except (TypeError, ValueError) as exc:
        raise ValueError("MCP default_call_timeout must be a number") from exc
    if default_timeout <= 0:
        raise ValueError("MCP default_call_timeout must be greater than 0")
    servers = cfg.get("servers") or []
    if not isinstance(servers, list):
        raise ValueError("MCP servers must be a list")
    return {
        "default_call_timeout": default_timeout,
        "enabled": cfg.get("enabled") is not False,
        "servers": [_validate_mcp_server(item) for item in servers],
    }


def _preview_mcp_tools_from_payload(state: BridgeState, task_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    from llm.tools.mcp_config_file import write_mcp_config
    from llm.tools.mcp_tool_setup import preview_mcp_tools_from_config

    cfg = _validate_mcp_config_payload(payload)
    _update_task(state, task_id, message="正在写入临时 MCP 配置。", phase="write", progress=0.2)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        write_mcp_config(cfg, temp_path)
        _update_task(state, task_id, message="正在连接 MCP 服务并枚举工具。", phase="probe", progress=0.55)
        rows = preview_mcp_tools_from_config(temp_path)
        valid = [dict(item) for item in rows if isinstance(item, dict)]
        _update_task(state, task_id, message=f"已获取 {len(valid)} 个 MCP 工具。", progress=0.92)
        return valid
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _save_and_apply_mcp_config(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from llm.tools.mcp_config_file import DEFAULT_MCP_CONFIG_PATH, write_mcp_config
    from llm.tools.mcp_tool_setup import reload_mcp_tools_from_config
    from llm.tools.tool_manager import ToolManager

    cfg = _validate_mcp_config_payload(payload)
    _update_task(state, task_id, message="正在写入 data/config/mcp.yaml。", phase="write", progress=0.35)
    write_mcp_config(cfg, DEFAULT_MCP_CONFIG_PATH)
    _update_task(state, task_id, message="正在重新注册 MCP 工具。", phase="reload", progress=0.72)
    reload_mcp_tools_from_config(ToolManager(), DEFAULT_MCP_CONFIG_PATH)
    return _mcp_config_response(cfg)


def _open_mcp_config_file() -> dict[str, str]:
    from llm.tools.mcp_config_file import DEFAULT_MCP_CONFIG_PATH, default_mcp_config, write_mcp_config

    path = DEFAULT_MCP_CONFIG_PATH
    if not path.is_file():
        write_mcp_config(default_mcp_config(), path)
    webbrowser.open(path.resolve().as_uri())
    return {"path": path.as_posix()}


def _install_plugin_source(
    state: BridgeState,
    task_id: str,
    source: str,
    *,
    ref_kind: str = "latest",
    tag_name: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    source = source.strip()
    if not source:
        raise ValueError("plugin id is required")
    ref_kind = ref_kind if ref_kind in {"latest", "head", "tag"} else "latest"
    tag_name = tag_name.strip()
    if ref_kind == "tag" and not tag_name:
        raise ValueError("tagName is required when refKind is tag")

    if not _is_repo_source(source):
        _update_task(
            state,
            task_id,
            message="正在写入插件清单。",
            phase="manifest",
            progress=0.45,
        )
        result = _plugin_result_from_manifest(source)
        _update_task(state, task_id, message="插件清单已更新。", progress=0.9)
        return result

    from core.plugins.github_bundle_update import install_github_plugin_under_plugins
    from core.plugins.plugin_requirements_install import install_plugin_requirements_txt
    from core.plugins.registry_download import format_download_error, mark_repo_downloaded, normalize_repo_slug

    repo_slug = normalize_repo_slug(_repo_slug_from_source(source))
    _update_task(
        state,
        task_id,
        message="正在查询插件索引。",
        phase="registry",
        progress=0.04,
    )
    registry_rec = _lookup_registry_plugin(repo_slug)
    entry = str(getattr(registry_rec, "entry", "") or "").strip()
    display_name = str(getattr(registry_rec, "name", "") or "").strip()
    description = str(getattr(registry_rec, "description", "") or "").strip()

    _update_task(
        state,
        task_id,
        message=f"正在下载 {repo_slug}。",
        phase="download",
        progress=0.08,
    )

    def _progress(current: int, total: int | None) -> None:
        if total:
            ratio = min(max(current / total, 0), 1)
            progress = 0.08 + ratio * 0.55
            message = f"正在下载 {current}/{total} bytes。"
        else:
            progress = 0.18
            message = f"已下载 {current} bytes。"
        _update_task(state, task_id, message=message, phase="download", progress=round(progress, 4))

    def _phase(phase: str) -> None:
        if phase == "extract":
            _update_task(state, task_id, message="正在解压插件源码。", phase="extract", progress=0.66)

    try:
        plugin_root = install_github_plugin_under_plugins(
            repo_slug,
            catalog_display_name=display_name,
            ref_kind=ref_kind,  # type: ignore[arg-type]
            tag_name=tag_name,
            overwrite=overwrite,
            plugins_parent=Path("plugins"),
            progress=_progress,
            on_phase=_phase,
        )
    except Exception as exc:
        raise RuntimeError(format_download_error(exc)) from exc

    _update_task(
        state,
        task_id,
        message="正在检查并安装插件 requirements.txt。",
        phase="pip",
        progress=0.72,
    )

    def _pip_line(line: str) -> None:
        _append_task_log(state, task_id, line)

    pip_code, pip_detail = install_plugin_requirements_txt(plugin_root, on_output_line=_pip_line)
    if pip_code in {"pip_failed", "pip_timeout", "pip_exception"}:
        detail = pip_detail or pip_code
        raise RuntimeError(f"插件依赖安装失败：{detail}")

    if not entry:
        entry = _infer_plugin_entry(plugin_root)

    _update_task(state, task_id, message="正在登记插件安装状态。", phase="manifest", progress=0.9)
    mark_repo_downloaded(repo_slug, manifest_entry=entry or None)
    if entry:
        return _plugin_result_from_manifest(entry)

    return _synthetic_plugin_result(
        description=description or f"源码已下载到 {plugin_root.as_posix()}，但未找到 manifest entry。",
        enabled=False,
        plugin_id=repo_slug,
        title=display_name or plugin_root.name,
    )


def _as_character_config(character: Any) -> Any:
    from config.character_config import CharacterConfig

    data = character.model_dump(mode="json") if hasattr(character, "model_dump") else dict(character)
    return CharacterConfig.parse_dic(data)


def _optional_suffix_check(value: str, suffix: str, label: str) -> tuple[bool, str]:
    if not value:
        return True, ""
    if value.lower().endswith(suffix):
        return True, ""
    return False, f"{label}: 文件后缀应为 {suffix}"


def _validate_character_payload_like_pyqt(body: dict[str, Any]) -> None:
    from sdk.ui.validators import (
        ascii_only,
        audio_duration_between,
        check_all,
        file_exists,
        no_quotes,
        not_empty,
    )

    sprite_prefix = str(body.get("sprite_prefix") or "").strip()
    gpt_model_path = str(body.get("gpt_model_path") or "").strip()
    sovits_model_path = str(body.get("sovits_model_path") or "").strip()
    refer_audio_path = str(body.get("refer_audio_path") or "").strip()
    ok, errors = check_all(
        not_empty(sprite_prefix, "立绘目录"),
        ascii_only(sprite_prefix, "立绘目录"),
        no_quotes(gpt_model_path, "GPT 模型路径"),
        file_exists(gpt_model_path, "GPT 模型路径"),
        _optional_suffix_check(gpt_model_path, ".ckpt", "GPT 模型路径"),
        no_quotes(sovits_model_path, "SoVITS 模型路径"),
        file_exists(sovits_model_path, "SoVITS 模型路径"),
        _optional_suffix_check(sovits_model_path, ".pth", "SoVITS 模型路径"),
        no_quotes(refer_audio_path, "参考音频"),
        file_exists(refer_audio_path, "参考音频"),
        audio_duration_between(refer_audio_path, 3.0, 10.0, "参考音频"),
    )
    if not ok:
        raise ValueError("\n".join(errors))


def _sprite_voice_path(sprite: Any) -> str:
    if hasattr(sprite, "voice_path"):
        return str(sprite.voice_path or "")
    if isinstance(sprite, dict):
        return str(sprite.get("voice_path") or "")
    return ""


def _validate_sprite_voice_duration(voice_path: str, voice_text: str) -> None:
    if not voice_text.strip():
        return
    from sdk.ui.validators import audio_duration_between

    ok, err = audio_duration_between(voice_path, 3.0, 10.0, "语音")
    if not ok:
        raise ValueError(err)


def _save_character(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("character", payload)
    if not isinstance(body, dict):
        raise ValueError("character payload must be an object")
    original_name = str(payload.get("originalName") or body.get("name") or "").strip()
    _validate_character_payload_like_pyqt(body)
    character = Character.model_validate(body)
    saved_name = character.name.strip()
    message, _names = state.character_manager.add_character(
        saved_name,
        str(character.color or "").strip() or "#d07d7d",
        character.sprite_prefix.strip() or "temp",
        str(character.gpt_model_path or "").strip(),
        str(character.sovits_model_path or "").strip(),
        str(character.refer_audio_path or "").strip(),
        str(character.prompt_text or "").strip(),
        str(character.prompt_lang or "").strip(),
        str(character.character_setting or "").strip(),
        speech_speed=character.speech_speed,
        speech_volume=character.speech_volume,
        pronunciation_map=character.pronunciation_map,
        edit_as_name=original_name,
    )
    if message.startswith("名称不能为空") or "已与其他角色重复" in message or message.startswith("保存失败"):
        raise RuntimeError(message)
    state.config_manager.reload()
    saved = state.config_manager.get_character_by_name(saved_name)
    return _jsonify(saved or character)


def _character_by_name(state: BridgeState, name: str) -> Any:
    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise KeyError(f"character not found: {name}")
    return character


def _character_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    return _jsonify(_character_by_name(state, name))


def _character_agent_id(name: str) -> str:
    value = str(name or "").strip()
    return value if value else "user"


def _list_character_memories(name: str) -> dict[str, Any]:
    from llm.tools.memory_tools import _get_mem0

    agent_id = _character_agent_id(name)
    mem = _get_mem0()
    raw = mem.get_all(filters={"user_id": agent_id}, limit=200)
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    memories = []
    for row in rows:
        if isinstance(row, dict):
            memories.append({"id": str(row.get("id") or ""), "memory": str(row.get("memory") or row.get("content") or "")})
        else:
            memories.append({"id": "", "memory": str(row)})
    return {"agentId": agent_id, "count": len(memories), "memories": memories}


def _add_character_memory(name: str, content: str) -> dict[str, Any]:
    from llm.tools.memory_tools import memory_remember

    text = str(content or "").strip()
    if not text:
        raise ValueError("memory content is required")
    result = memory_remember(text, character_name=_character_agent_id(name))
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))
    return _list_character_memories(name)


def _delete_character_memory(name: str, memory_id: str) -> dict[str, Any]:
    from llm.tools.memory_tools import memory_forget

    mid = str(memory_id or "").strip()
    if not mid:
        raise ValueError("memory id is required")
    result = memory_forget(mid)
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))
    return _list_character_memories(name)


def _generate_character_setting(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    setting = str(payload.get("setting") or "")
    message, character_setting = state.character_manager.generate_character_setting(name, setting)
    return {"characterSetting": character_setting, "message": message}


def _translate_character_fields(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.ai_field_translate import translate_character_name_and_tags

    ui_language = str(getattr(state.config_manager.config.system_config, "ui_language", "") or "")
    error, name, emotion_tags, character_setting = translate_character_name_and_tags(
        state.config_manager,
        ui_language,
        str(payload.get("name") or ""),
        str(payload.get("emotionTags") or ""),
        str(payload.get("characterSetting") or ""),
    )
    if error:
        return {"characterSetting": character_setting, "emotionTags": emotion_tags, "error": error, "name": name}
    return {"characterSetting": character_setting, "emotionTags": emotion_tags, "name": name}


def _upload_sprite_voice(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    voice_path = str(payload.get("voicePath") or "").strip()
    voice_text = str(payload.get("voiceText") or "").strip()
    if not voice_path:
        raise ValueError("voice path is required")
    _validate_sprite_voice_duration(voice_path, voice_text)
    message, _path = state.character_manager.upload_voice(name, sprite_index, voice_path, voice_text)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _upload_character_sprites(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    emotion_tags = str(payload.get("emotionTags") or "")
    paths = payload.get("paths") or []
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    message, _paths, _tags = state.character_manager.upload_sprites(
        name,
        _path_namespace_list([str(item) for item in paths]),
        emotion_tags,
    )
    if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _save_character_emotion_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    emotion_tags = str(payload.get("emotionTags") or "")
    message = state.character_manager.upload_emotion_tags(name, emotion_tags)
    if (
        message.startswith("请先")
        or message.startswith("请输入")
        or message.startswith("找不到")
        or message.startswith("标注出错")
    ):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _delete_character_sprite(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    message, _paths, _tags = state.character_manager.delete_single_sprite(name, sprite_index)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _delete_all_character_sprites(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message, _paths, _tags = state.character_manager.delete_all_sprites(name)
    if message.startswith("找不到") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _save_sprite_scale(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scale = float(payload.get("scale") or 0)
    message = state.character_manager.save_sprite_scale(name, scale)
    text = str(message[0] if isinstance(message, tuple) else message)
    if text.startswith("名称不能为空") or text.startswith("找不到"):
        raise RuntimeError(text)
    return _character_json_after_reload(state, name)


def _save_sprite_voice_text(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    voice_text = str(payload.get("voiceText") or "").strip()
    character = _character_by_name(state, name)
    sprites = getattr(character, "sprites", []) or []
    if 0 <= sprite_index < len(sprites):
        voice_path = _sprite_voice_path(sprites[sprite_index])
        if voice_path and Path(voice_path).is_file():
            _validate_sprite_voice_duration(voice_path, voice_text)
    message = state.character_manager.save_sprite_voice_text(name, sprite_index, voice_text)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _delete_sprite_voice(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    message = state.character_manager.delete_sprite_voice(name, sprite_index)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _save_background(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("background", payload)
    if not isinstance(body, dict):
        raise ValueError("background payload must be an object")
    name = str(body.get("name") or "").strip()
    prefix = str(body.get("sprite_prefix") or "temp").strip() or "temp"
    original_name = str(payload.get("originalName") or "").strip()
    message, _names = state.background_manager.add_background(name, prefix, edit_as_name=original_name or None)
    if message.startswith("名称") or "重复" in message or message.startswith("找不到"):
        raise RuntimeError(message)
    state.config_manager.reload()
    saved = state.config_manager.get_background_by_name(name)
    if saved is None:
        raise RuntimeError(message)
    return _jsonify(saved)


def _background_by_name(state: BridgeState, name: str) -> Any:
    background = state.config_manager.get_background_by_name(name)
    if background is None:
        raise KeyError(f"background not found: {name}")
    return background


def _background_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    return _jsonify(_background_by_name(state, name))


def _numbered_background_bgm_tags(tags: list[str]) -> str:
    return "".join(f"音乐 {index + 1}：{str(tag or '').strip()}\n" for index, tag in enumerate(tags))


def _tag_content(text: Any) -> str:
    value = str(text or "")
    if "：" in value:
        return value.split("：", 1)[1].strip()
    if ":" in value:
        return value.split(":", 1)[1].strip()
    return value.strip()


def _path_namespace_list(paths: Any) -> list[Any]:
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    out = []
    for item in paths:
        path = str(item or "").strip()
        if path:
            out.append(SimpleNamespace(name=path))
    if not out:
        raise ValueError("at least one path is required")
    return out


def _translate_background_fields(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.ai_field_translate import translate_background_fields

    row_tag_payload = payload.get("bgmRowTags")
    if isinstance(row_tag_payload, list):
        bgm_row_tags = [str(item or "") for item in row_tag_payload]
    else:
        bgm_row_tags = [_tag_content(line) for line in str(payload.get("bgmTags") or "").splitlines()]
    ui_language = str(getattr(state.config_manager.config.system_config, "ui_language", "") or "")
    error, name, bg_tags, bgm_tags, bgm_row_tags = translate_background_fields(
        state.config_manager,
        ui_language,
        str(payload.get("name") or ""),
        str(payload.get("bgTags") or ""),
        str(payload.get("bgmTags") or ""),
        bgm_row_tags,
    )
    response_bgm_tags = _numbered_background_bgm_tags(bgm_row_tags) if bgm_row_tags else bgm_tags
    if bgm_row_tags:
        bgm_tags = response_bgm_tags
    if error:
        return {"bgTags": bg_tags, "bgmRowTags": bgm_row_tags, "bgmTags": bgm_tags, "error": error, "name": name}
    return {"bgTags": bg_tags, "bgmRowTags": bgm_row_tags, "bgmTags": bgm_tags, "name": name}


def _upload_background_images(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    files = _path_namespace_list(payload.get("paths") or [])
    message, _paths, _tags = state.background_manager.upload_sprites(name, files, str(payload.get("bgTags") or ""))
    if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _upload_background_bgm(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    files = _path_namespace_list(payload.get("paths") or [])
    background = _background_by_name(state, name)
    background.bgm_tags = str(payload.get("bgmTags") or background.bgm_tags or "")
    state.config_manager.save_background_config()
    message, _df, _tags = state.background_manager.upload_bgms(name, files)
    if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _save_background_image_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message = state.background_manager.upload_bg_tags(name, str(payload.get("bgTags") or ""))
    if message.startswith("找不到") or message.startswith("请") or "出错" in message:
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _save_background_bgm_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message = state.background_manager.upload_bgm_tags(name, str(payload.get("bgmTags") or ""))
    if message.startswith("找不到") or message.startswith("请") or "出错" in message:
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_background_image(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    index = int(payload.get("index") or 0)
    message, _paths, _tags = state.background_manager.delete_single_sprite(name, index)
    if message.startswith("找不到") or message.startswith("背景图片不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_all_background_images(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message, _paths, _tags = state.background_manager.delete_all_sprites(name)
    if message.startswith("找不到") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_background_bgm(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    index = int(payload.get("index") or 0)
    message, _paths, _tags = state.background_manager.delete_single_bgm(name, index)
    if message.startswith("找不到") or message.startswith("背景音乐不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_all_background_bgm(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message, _paths, _tags = state.background_manager.delete_all_bgms(name)
    if message.startswith("找不到") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _resolve_project_file(raw_path: str | Path) -> Path:
    root = Path.cwd().resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if root not in path.parents and path != root:
        raise PermissionError("path is outside project root")
    return path


def _chat_history_path(state: BridgeState, payload: dict[str, Any], template: dict[str, Any]) -> Path:
    raw = str(payload.get("historyPath") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else Path.cwd() / path
    template_hash = _history_id_from_scenario(
        str(template.get("scenario") or template.get("content") or ""),
        str(template.get("system") or ""),
    )
    return _resolve_project_file(Path(state.history_dir) / f"{template_hash}.json")


def _sprite_path(sprite: Any) -> str:
    return str(sprite.path if hasattr(sprite, "path") else sprite.get("path", ""))


def _chat_session_media(state: BridgeState) -> tuple[str, str, list[dict[str, str]]]:
    config = state.config_manager.config
    character_name = str(state.chat_session.get("characterName") or "")
    background_name = str(state.chat_session.get("backgroundName") or "")
    character = state.config_manager.get_character_by_name(character_name) if character_name else None
    background = state.config_manager.get_background_by_name(background_name) if background_name else None
    if character is None:
        character = config.characters[0] if config.characters else None
    if background is None:
        background = config.background_list[0] if config.background_list else None
    sprites = []
    if character and character.sprites:
        sprite = character.sprites[0]
        sprites.append({"id": f"{character.name}-0", "label": character.name, "path": _sprite_path(sprite)})
    bg_path = ""
    if background and background.sprites:
        sprite = background.sprites[0]
        bg_path = _sprite_path(sprite)
    return bg_path, character.name if character else "", sprites


def _chat_snapshot(
    state: BridgeState,
    status: str = "idle",
    message: str = "",
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bg_path, character_name, sprites = _chat_session_media(state)
    history_path = str(state.chat_session.get("historyPath") or "")
    return {
        "backgroundPath": bg_path,
        "characterName": character_name,
        "dialogText": message or "React bridge 已连接，启动聊天后主进程会接管实时演出窗口。",
        "historyPath": history_path,
        "inputDraft": "",
        "numericInfo": status,
        "options": [],
        "sprites": sprites,
        "status": status,
        **(extra or {}),
    }


def _plain_history_text(raw: Any) -> str:
    if not isinstance(raw, list):
        return ""
    rows: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
            if content:
                rows.append(f"{role}: {content}" if role else content)
        else:
            text = re.sub(r"<[^>]+>", "", str(item)).strip()
            if text:
                rows.append(text)
    return "\n".join(rows)


def _read_history_file(path: Path) -> Any:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _handle_chat_command(state: BridgeState, body: dict[str, Any]) -> dict[str, Any]:
    command = str(body.get("type") or "").strip()
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    history_path = _resolve_project_file(history_raw) if history_raw else None

    if command == "copy-history":
        if history_path is None:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        if not history_path.exists():
            raise FileNotFoundError(history_path.as_posix())
        text = _plain_history_text(_read_history_file(history_path))
        return _chat_snapshot(
            state,
            "idle",
            "历史记录已复制。",
            extra={"clipboardText": text, "openedPath": history_path.as_posix()},
        )

    if command == "open-history":
        if history_path is None:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        if not history_path.exists():
            raise FileNotFoundError(history_path.as_posix())
        rel = history_path.relative_to(Path.cwd().resolve()).as_posix()
        return _chat_snapshot(
            state,
            "idle",
            "历史文件已打开。",
            extra={"downloadUrl": f"/api/download?path={quote(rel)}", "openedPath": rel},
        )

    if command == "clear-history":
        if history_path is None:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        history_path.unlink(missing_ok=True)
        return _chat_snapshot(state, "idle", "历史记录已经清空。")

    if command == "send-message":
        text = str(body.get("payload") or "").strip()
        if not text:
            raise ValueError("消息内容不能为空。")
        return _chat_snapshot(state, "generating", f"已提交：{text}")

    if command == "submit-option":
        option = str(body.get("payload") or "").strip()
        if not option:
            raise ValueError("选项不能为空。")
        return _chat_snapshot(state, "generating", f"已选择：{option}")

    if command == "skip-speech":
        return _chat_snapshot(state, "idle", "已跳过当前语音。")
    if command == "pause-asr":
        return _chat_snapshot(state, "paused", "语音识别已暂停。")
    if command == "reroll":
        return _chat_snapshot(state, "generating", "正在请求重新生成。")

    raise ValueError(f"未知聊天命令：{command}")


def _chat_theme_payload(state: BridgeState) -> dict[str, Any]:
    system_config = state.config_manager.config.system_config
    raw_path = str(system_config.chat_ui_theme_path or "").strip()
    path = Path(raw_path) if raw_path else Path("data") / "chat_ui_theme.json"
    if not path.is_absolute():
        path = Path.cwd() / path
    data: Any = {}
    if path.is_file():
        with path.open(encoding="utf-8") as file:
            parsed = json.load(file)
        if isinstance(parsed, dict):
            data = parsed
    return {
        "path": path.as_posix() if path.exists() else "",
        "raw": data,
        "themeColor": str(system_config.theme_color or ""),
    }


class FrontendBridgeHandler(BaseHTTPRequestHandler):
    server_version = "ShinsekaiFrontendBridge/0.1"

    @property
    def state(self) -> BridgeState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[frontend_bridge] {self.address_string()} - {fmt % args}")

    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Task-Id")

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(_jsonify(data), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_error_json(self, exc: Exception, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._send_json({"error": str(exc), "type": exc.__class__.__name__}, status)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _read_upload_files(self) -> tuple[Path, list[Path]]:
        ctype = self.headers.get("Content-Type", "")
        if not ctype.lower().startswith("multipart/form-data"):
            raise ValueError("request must be multipart/form-data")
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            raise ValueError("request body is empty")
        temp_dir = Path(tempfile.mkdtemp(prefix="shinsekai-frontend-upload-"))
        body = self.rfile.read(length)
        message = BytesParser(policy=default_email_policy).parsebytes(
            f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        paths: list[Path] = []
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if part.get_param("name", header="content-disposition") != "files":
                continue
            filename = Path(str(part.get_filename() or "")).name
            if not filename:
                continue
            dest = temp_dir / filename
            dest.write_bytes(part.get_payload(decode=True) or b"")
            paths.append(dest)
        if not paths:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise ValueError("no files uploaded")
        return temp_dir, paths

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/health":
                self._send_json({"ok": True})
            elif path == "/api/config":
                self._send_json(_app_config_response(self.state))
            elif path == "/api/characters":
                self._send_json(self.state.config_manager.config.characters)
            elif path == "/api/backgrounds":
                self._send_json(self.state.config_manager.config.background_list)
            elif path == "/api/templates":
                self._send_json(_list_templates(self.state))
            elif path == "/api/templates/session":
                self._send_json(_load_template_session_payload(self.state))
            elif path == "/api/plugins":
                self._send_json(_plugin_rows())
            elif path == "/api/plugins/app-update/info":
                self._send_json(_app_update_info())
            elif path == "/api/plugins/registry":
                self._send_json(_plugin_registry_rows())
            elif path == "/api/mcp/config":
                self._send_json(_mcp_config_response())
            elif path.startswith("/api/tasks/"):
                task_id = unquote(path.rsplit("/", 1)[-1])
                self._send_json(_get_task(self.state, task_id))
            elif path == "/api/chat/snapshot":
                self._send_json(_chat_snapshot(self.state))
            elif path == "/api/chat/theme":
                self._send_json(_chat_theme_payload(self.state))
            elif path == "/api/download":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_file(target, attachment=True)
            elif path == "/api/media":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_file(target, attachment=False)
            elif path.startswith("/assets/") or path.startswith("/data/"):
                self._send_file(path.lstrip("/"))
            elif self._try_send_frontend(path):
                return
            else:
                self._send_error_json(FileNotFoundError(path), HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_error_json(exc, HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self._send_error_json(exc, HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            self._send_error_json(exc, HTTPStatus.FORBIDDEN)
        except Exception as exc:
            self._send_error_json(exc)

    def do_POST(self) -> None:  # noqa: N802
        self._handle_write("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_write("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle_write("DELETE")

    def _handle_write(self, method: str) -> None:
        try:
            path = urlparse(self.path).path
            is_upload = method == "POST" and path in {
                "/api/characters/import-upload",
                "/api/backgrounds/import-upload",
            }
            body = {} if method == "DELETE" or is_upload else self._read_json()
            if method in {"POST", "PUT"} and path == "/api/config/api":
                self._send_json(_save_api_config(self.state, body))
            elif method in {"POST", "PUT"} and path == "/api/config/system":
                config = SystemConfig.model_validate(body)
                self.state.config_manager.config.system_config = config
                self.state.config_manager.save_system_config()
                try:
                    from i18n import init_i18n

                    init_i18n(config.ui_language)
                except Exception:
                    pass
                self._send_json(config)
            elif method == "POST" and path == "/api/config/llm-models":
                self._send_json(_fetch_llm_models(body))
            elif method == "POST" and path == "/api/files/browse":
                self._send_json(_browse_local_files(self.state, body))
            elif method == "POST" and path == "/api/music-cover/search":
                self._send_json(_music_cover_search(self.state, body))
            elif method == "POST" and path == "/api/music-cover/config":
                self._send_json(_save_music_cover_config(self.state, body))
            elif method == "POST" and path == "/api/music-cover/run":
                task = _create_task(
                    self.state,
                    kind="music-cover",
                    title="音乐翻唱流水线",
                    message="音乐翻唱流水线已排队。",
                )
                threading.Thread(
                    daemon=True,
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _run_music_cover(
                            self.state, task_id, payload
                        ),
                    ),
                ).start()
                self._send_json(task)
            elif method == "POST" and path == "/api/config/tts-bundle/download":
                task = _create_task(
                    self.state,
                    kind="tts-bundle",
                    title="TTS 整合包下载",
                    message="TTS 整合包下载已排队。",
                )
                threading.Thread(
                    daemon=True,
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _download_tts_bundle(
                            self.state, task_id, payload
                        ),
                    ),
                ).start()
                self._send_json(task)
            elif method in {"POST", "PUT"} and path == "/api/characters":
                self._send_json(_save_character(self.state, body))
            elif method == "POST" and path == "/api/characters/ai-setting":
                self._send_json(_generate_character_setting(self.state, body))
            elif method == "POST" and path == "/api/characters/translate":
                self._send_json(_translate_character_fields(self.state, body))
            elif method == "POST" and path == "/api/characters/memories/list":
                self._send_json(_list_character_memories(str(body.get("name") or "")))
            elif method == "POST" and path == "/api/characters/memories/add":
                self._send_json(_add_character_memory(str(body.get("name") or ""), str(body.get("content") or "")))
            elif method == "POST" and path == "/api/characters/memories/delete":
                self._send_json(
                    _delete_character_memory(str(body.get("name") or ""), str(body.get("memoryId") or ""))
                )
            elif method == "POST" and path == "/api/characters/sprite-voice/upload":
                self._send_json(_upload_sprite_voice(self.state, body))
            elif method == "POST" and path == "/api/characters/sprites/upload":
                self._send_json(_upload_character_sprites(self.state, body))
            elif method == "POST" and path == "/api/characters/emotion-tags":
                self._send_json(_save_character_emotion_tags(self.state, body))
            elif method == "POST" and path == "/api/characters/sprites/delete":
                self._send_json(_delete_character_sprite(self.state, body))
            elif method == "POST" and path == "/api/characters/sprites/delete-all":
                self._send_json(_delete_all_character_sprites(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-scale":
                self._send_json(_save_sprite_scale(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-voice/text":
                self._send_json(_save_sprite_voice_text(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-voice/delete":
                self._send_json(_delete_sprite_voice(self.state, body))
            elif method == "DELETE" and path.startswith("/api/characters/"):
                name = unquote(path.rsplit("/", 1)[-1])
                message, names = self.state.character_manager.delete_character(name)
                self._send_json({"message": message, "names": names})
            elif method == "POST" and path == "/api/characters/import":
                paths = body.get("paths") or []
                if not isinstance(paths, list):
                    raise ValueError("paths must be a list")
                import tools.file_util as file_util

                imported = []
                for item in paths:
                    imported.extend(file_util.import_character(str(item)))
                self.state.config_manager.reload()
                self._send_json([item.__dict__ for item in imported])
            elif method == "POST" and path == "/api/characters/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    import tools.file_util as file_util

                    imported = []
                    for item in paths:
                        imported.extend(file_util.import_character(str(item)))
                    self.state.config_manager.reload()
                    self._send_json([item.__dict__ for item in imported])
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/characters/export":
                name = str(body.get("name") or "")
                character = self.state.config_manager.get_character_by_name(name)
                if character is None:
                    raise KeyError(f"character not found: {name}")
                output = Path("output") / f"{name}.char"
                output.parent.mkdir(parents=True, exist_ok=True)
                import tools.file_util as file_util

                file_util.export_character([_as_character_config(character)], output.as_posix(), open_folder=False)
                self._send_json({"downloadUrl": f"/api/download?path={output.as_posix()}", "path": output.as_posix()})
            elif method == "POST" and path == "/api/backgrounds/translate":
                self._send_json(_translate_background_fields(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/images/upload":
                self._send_json(_upload_background_images(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm/upload":
                self._send_json(_upload_background_bgm(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/images/delete":
                self._send_json(_delete_background_image(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/images/delete-all":
                self._send_json(_delete_all_background_images(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm/delete":
                self._send_json(_delete_background_bgm(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm/delete-all":
                self._send_json(_delete_all_background_bgm(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/tags":
                self._send_json(_save_background_image_tags(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm-tags":
                self._send_json(_save_background_bgm_tags(self.state, body))
            elif method in {"POST", "PUT"} and path == "/api/backgrounds":
                self._send_json(_save_background(self.state, body))
            elif method == "DELETE" and path.startswith("/api/backgrounds/"):
                name = unquote(path.rsplit("/", 1)[-1])
                message, names = self.state.background_manager.delete_background(name)
                if message.startswith("找不到") or message.startswith("请选择") or "失败" in message:
                    raise RuntimeError(message)
                self._send_json({"message": message, "names": names})
            elif method == "POST" and path == "/api/backgrounds/import":
                paths = body.get("paths") or []
                if not isinstance(paths, list):
                    raise ValueError("paths must be a list")
                self._send_json(self._import_background_paths([str(item) for item in paths]))
            elif method == "POST" and path == "/api/backgrounds/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(self._import_background_paths([str(item) for item in paths]))
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/backgrounds/export":
                name = str(body.get("name") or "")
                background = self.state.config_manager.get_background_by_name(name)
                if background is None:
                    raise KeyError(f"background not found: {name}")
                output = Path("output") / f"{name}.bg"
                import tools.file_util as file_util

                file_util.export_background([background], output.as_posix(), open_folder=False)
                self._send_json({"downloadUrl": f"/api/download?path={output.as_posix()}", "path": output.as_posix()})
            elif method in {"POST", "PUT"} and path == "/api/templates":
                self._send_json(_save_template_summary(self.state, body))
            elif method == "POST" and path == "/api/templates/session":
                self._send_json(_save_template_session_payload(self.state, body))
            elif method == "POST" and path == "/api/templates/generate":
                self._send_json(_generate_template_summary(self.state, body))
            elif method == "POST" and path == "/api/tools/sprite-prompts":
                task = _create_task(
                    self.state,
                    kind="tools-prompts",
                    message="立绘提示词生成任务已排队。",
                    title="生成立绘提示词",
                )
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _generate_sprite_prompts(
                            self.state, task_id, payload
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/tools/sprites/generate":
                task = _create_task(
                    self.state,
                    kind="tools-sprites",
                    message="立绘批量生成任务已排队。",
                    title="批量生成立绘",
                )
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _generate_sprites(
                            self.state, task_id, payload
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/tools/sprites/crop":
                task = _create_task(
                    self.state,
                    kind="tools-crop",
                    message="立绘裁剪任务已排队。",
                    title="批量裁剪立绘",
                )
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _crop_sprites(
                            self.state, task_id, payload
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/tools/sprites/remove-background":
                task = _create_task(
                    self.state,
                    kind="tools-rmbg",
                    message="立绘抠图任务已排队。",
                    title="批量抠出立绘",
                )
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _remove_sprite_background(
                            self.state, task_id, payload
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/mcp/config/open":
                self._send_json(_open_mcp_config_file())
            elif method == "POST" and path == "/api/mcp/config/apply":
                task = _create_task(
                    self.state,
                    kind="mcp-apply",
                    message="MCP 保存应用任务已排队。",
                    title="保存并应用 MCP 配置",
                )
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _save_and_apply_mcp_config(
                            self.state, task_id, payload
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/mcp/preview":
                task = _create_task(
                    self.state,
                    kind="mcp-preview",
                    message="MCP 工具预览任务已排队。",
                    title="刷新 MCP 工具列表",
                )
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _preview_mcp_tools_from_payload(
                            self.state, task_id, payload
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/plugins/install":
                plugin_id = str(body.get("source") or body.get("id") or "").strip()
                if not plugin_id:
                    raise ValueError("plugin id is required")
                ref_kind = str(body.get("refKind") or "latest").strip()
                tag_name = str(body.get("tagName") or "").strip()
                overwrite = bool(body.get("overwrite"))
                with self.state.task_lock:
                    running = [
                        dict(task)
                        for task in self.state.tasks.values()
                        if task.get("kind") == "plugin-install"
                        and task.get("source") == plugin_id
                        and _is_running_task(task)
                    ]
                if running:
                    self._send_json(running[0], HTTPStatus.ACCEPTED)
                    return
                task = _create_task(
                    self.state,
                    kind="plugin-install",
                    message="插件安装任务已排队。",
                    title=f"安装插件 {plugin_id}",
                )
                _update_task(self.state, task["id"], source=plugin_id)
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda source=plugin_id, task_id=task["id"], rk=ref_kind, tn=tag_name, ow=overwrite: _install_plugin_source(
                            self.state, task_id, source, ref_kind=rk, tag_name=tn, overwrite=ow
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/plugins/repo-tags":
                self._send_json(_repo_tags(body))
            elif method == "POST" and path == "/api/plugins/app-update/tags":
                self._send_json(_app_update_tags())
            elif method == "POST" and path == "/api/plugins/app-update/run":
                ref_kind = str(body.get("refKind") or "latest").strip()
                tag_name = str(body.get("tagName") or "").strip()
                task = _create_task(
                    self.state,
                    kind="app-update",
                    message="主程序更新任务已排队。",
                    title="更新主程序",
                )
                _update_task(self.state, task["id"], refKind=ref_kind, tagName=tag_name)
                thread = threading.Thread(
                    target=_run_background_task,
                    args=(
                        self.state,
                        task["id"],
                        lambda task_id=task["id"], payload=body: _run_app_update(
                            self.state, task_id, payload
                        ),
                    ),
                    daemon=True,
                )
                thread.start()
                self._send_json(_get_task(self.state, task["id"]), HTTPStatus.ACCEPTED)
            elif method == "POST" and path.startswith("/api/plugins/") and path.endswith("/enabled"):
                plugin_id = unquote(path[len("/api/plugins/") : -len("/enabled")])
                self._send_json(_set_plugin_enabled(plugin_id, bool(body.get("enabled"))))
            elif method == "DELETE" and path.startswith("/api/plugins/"):
                plugin_id = unquote(path[len("/api/plugins/") :])
                self._send_json(_uninstall_plugin(plugin_id))
            elif method == "POST" and path == "/api/chat/launch":
                self._send_json(self._launch_chat(body))
            elif method == "POST" and path == "/api/chat/resume-last":
                self._send_json(self._resume_last_chat())
            elif method == "POST" and path == "/api/chat/command":
                self._send_json(_handle_chat_command(self.state, body))
            else:
                self._send_error_json(FileNotFoundError(path), HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_error_json(exc, HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self._send_error_json(exc, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error_json(exc)

    def _import_background_paths(self, paths: list[str]) -> list[dict[str, Any]]:
        import tools.file_util as file_util

        existing = self.state.config_manager.config.background_list
        imported = []
        for item in paths:
            batch = file_util.import_background(str(item), existing)
            imported.extend(batch)
            for background in batch:
                if background not in existing:
                    existing.append(background)
        self.state.config_manager.save_background_config()
        self.state.config_manager.reload()
        return [_jsonify(item) for item in imported]

    def _launch_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        template_id = str(body.get("templateId") or "")
        rows = _list_templates(self.state)
        row = next((item for item in rows if item["id"] == template_id), None)
        has_inline_template = "scenario" in body or "system" in body
        if has_inline_template:
            scenario = str(body.get("scenario") or "")
            system_template = str(body.get("system") or "")
            row = {
                "content": _compose_for_llm(scenario, system_template),
                "id": template_id or "_temp.txt",
                "name": str(body.get("templateName") or template_id or "_temp"),
                "scenario": scenario,
                "system": system_template,
            }
        elif row is None:
            raise KeyError(f"template not found: {template_id}")
        characters = body.get("characters") or []
        first_character = ""
        if isinstance(characters, list) and characters:
            first_character = str(characters[0])
        init_sprite_path = ""
        character = self.state.config_manager.get_character_by_name(first_character)
        if character and character.sprites:
            sprite = character.sprites[0]
            init_sprite_path = _sprite_path(sprite)
        init_sprite_path = str(body.get("initSpritePath") or init_sprite_path)
        room_id = str(body.get("roomId") or self.state.config_manager.config.system_config.live_room_id or "")
        history_path = _chat_history_path(self.state, body, row)
        default_history_path = _chat_history_path(self.state, {"historyPath": ""}, row)
        reset_history = bool(body.get("resetHistory"))
        if reset_history:
            for item in {history_path, default_history_path}:
                try:
                    if item.exists():
                        item.unlink()
                except OSError:
                    pass
        user_scenario = str(row.get("scenario") or row.get("content") or "")
        system_template = str(row.get("system") or "")
        if _has_untranslated_template_keys(user_scenario, system_template):
            from ui.settings_ui.services.template_tab_session import load_template_session

            repaired = _repair_template_session_if_needed(self.state, load_template_session(self.state.template_dir_path))
            if repaired:
                user_scenario = str(repaired.get("scenario_text") or "")
                system_template = str(repaired.get("system_template_text") or "")
        message = _launch_chat(
            self.state,
            history_file="" if reset_history else history_path.as_posix(),
            init_sprite_path=init_sprite_path,
            room_id=room_id,
            selected_bg=str(body.get("backgroundName") or ""),
            system_template=system_template,
            use_cg=bool(body.get("useCg")),
            user_scenario=user_scenario,
        )
        if message.startswith("启动失败"):
            raise RuntimeError(message)
        self.state.chat_session = {
            "backgroundName": str(body.get("backgroundName") or ""),
            "characterName": first_character,
            "historyPath": (default_history_path if reset_history else history_path).as_posix(),
            "templateId": template_id,
        }
        return _chat_snapshot(self.state, "idle", message)

    def _resume_last_chat(self) -> dict[str, Any]:
        history_path = _latest_history_json(self.state.history_dir)
        if history_path is None:
            raise FileNotFoundError("未找到聊天记录（*.json）。请先在主窗口进行过对话。")
        template_parts = _resume_template_parts(self.state)
        if template_parts is None:
            raise FileNotFoundError("未找到可用模板（.txt）。请先在聊天模板页生成、保存或启动过一次。")
        scenario, system_template, template_id = template_parts
        room_id = self.state.config_manager.config.system_config.live_room_id
        message = _launch_chat(
            self.state,
            history_file=history_path.resolve().as_posix(),
            init_sprite_path="",
            room_id=str(room_id or ""),
            selected_bg=TRANSPARENT_BACKGROUND_NAME,
            system_template=system_template,
            use_cg=False,
            user_scenario=scenario,
        )
        if message.startswith("启动失败"):
            raise RuntimeError(message)
        self.state.chat_session = {
            "backgroundName": TRANSPARENT_BACKGROUND_NAME,
            "characterName": "",
            "historyPath": history_path.as_posix(),
            "templateId": template_id,
        }
        return _chat_snapshot(self.state, "idle", message)

    def _resolve_project_path(self, raw_path: str) -> Path:
        root = Path.cwd().resolve()
        raw = str(raw_path or "").strip()
        if not raw:
            raise FileNotFoundError(raw_path)
        if Path(raw).is_absolute():
            path = Path(raw).resolve()
            if root not in path.parents and path != root:
                raise PermissionError("path is outside project root")
            return path

        candidates: list[str] = [raw]
        slash_path = raw.replace("\\", "/")
        if slash_path != raw:
            candidates.append(slash_path)

        parts = [part for part in slash_path.split("/") if part and part != "."]
        if len(parts) >= 5 and parts[0] == "data":
            family, prefix = parts[1], parts[2]
            if parts[3] == family and parts[4] == prefix:
                candidates.append("/".join(parts[:3] + parts[5:]))
            if family in {"backgrounds", "bgm", "speech", "sprite"}:
                candidates.append("/".join(parts[:3] + [parts[-1]]))

        first_valid: Path | None = None
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            path = (root / candidate).resolve()
            if root not in path.parents and path != root:
                raise PermissionError("path is outside project root")
            if first_valid is None:
                first_valid = path
            if path.is_file():
                return path
        return first_valid if first_valid is not None else (root / raw).resolve()

    def _resolve_static_path(self, root: Path, request_path: str) -> Path:
        base = root.resolve()
        target = (base / request_path.lstrip("/")).resolve()
        if base not in target.parents and target != base:
            raise PermissionError("path is outside static root")
        return target

    def _send_local_file(self, path: Path, *, attachment: bool = False) -> None:
        if not path.is_file():
            raise FileNotFoundError(path.as_posix())
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._send_cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def _try_send_frontend(self, request_path: str) -> bool:
        dist_root = _frontend_dist_root(self.state)
        if dist_root is None or not dist_root.is_dir():
            return False
        index_path = dist_root / "index.html"
        if not index_path.is_file():
            return False

        if request_path in {"", "/", "/index.html"}:
            self._send_local_file(index_path)
            return True

        candidate = self._resolve_static_path(dist_root, request_path)
        if candidate.is_file():
            self._send_local_file(candidate)
            return True

        if request_path.startswith("/web-assets/"):
            raise FileNotFoundError(request_path)

        self._send_local_file(index_path)
        return True

    def _send_file(self, relative_path: str, *, attachment: bool = False) -> None:
        self._send_local_file(self._resolve_project_path(relative_path), attachment=attachment)


def run(
    host: str,
    port: int,
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    open_browser: bool = False,
) -> None:
    repo_root = Path(__file__).resolve().parent
    resolved_frontend_dist = ""
    if frontend_dist:
        dist_path = Path(frontend_dist).expanduser()
        if not dist_path.is_absolute():
            dist_path = repo_root / dist_path
        resolved_frontend_dist = str(dist_path.resolve())

    if project_root:
        root = Path(project_root).expanduser().resolve()
        os.environ["EASYAI_PROJECT_ROOT"] = str(root)
        os.chdir(root)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    global ApiConfig, Background, BackgroundManager, Character, CharacterManager, ConfigManager, SystemConfig, TemplateGenerator
    from config.background_manager import BackgroundManager
    from config.character_manager import CharacterManager
    from config.config_manager import ConfigManager
    from config.schema import ApiConfig, Background, Character, SystemConfig
    from i18n import init_i18n
    from llm.template_generator import TemplateGenerator

    config_manager = ConfigManager()
    init_i18n(config_manager.config.system_config.ui_language)

    state = BridgeState(
        config_manager=config_manager,
        character_manager=CharacterManager(),
        background_manager=BackgroundManager(),
        template_generator=TemplateGenerator(),
        frontend_dist_dir=resolved_frontend_dist,
    )
    try:
        from core.plugins.plugin_host import ensure_plugins_loaded

        ensure_plugins_loaded(state.config_manager)
    except Exception as exc:
        print(f"Plugin load failed: {exc}")
    server = ThreadingHTTPServer((host, port), FrontendBridgeHandler)
    server.state = state  # type: ignore[attr-defined]
    print(f"Shinsekai frontend bridge listening on http://{host}:{port}")
    frontend_index = Path(resolved_frontend_dist) / "index.html" if resolved_frontend_dist else None
    if frontend_index and frontend_index.is_file():
        print(f"Serving built frontend from {frontend_index.parent}")
        if open_browser:
            _schedule_browser_open(f"http://{host}:{port}/#/settings/api")
    elif resolved_frontend_dist:
        print(f"Built frontend not found at {resolved_frontend_dist}; API bridge only.")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Shinsekai React frontend HTTP bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument(
        "--project-root",
        default="",
        help="Project/data root to use for relative data/config paths. Defaults to the current directory.",
    )
    parser.add_argument(
        "--frontend-dist",
        default="frontend/dist",
        help="Built frontend directory to serve. Relative paths resolve from the repository root.",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the built React settings UI in the default browser after startup.",
    )
    args = parser.parse_args()
    run(
        args.host,
        args.port,
        args.project_root or None,
        args.frontend_dist or None,
        args.open_browser,
    )


if __name__ == "__main__":
    main()
