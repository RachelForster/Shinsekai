"""End-to-end character voice preparation coordinator (default zero-shot pretrained, optional GSV fine-tuning)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import uuid

from application.characters import (
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
)
from application.characters.voice.pipeline.community_models import search_community_gsv_models
from application.characters.voice.pipeline.gsv_runtime import (
    CancellableGsvRunner,
    SubprocessFailed,
    detect_runtime_profile,
    resolve_asr_model_arg_and_env,
    resolve_gpt_sovits_settings,
    validate_asr_list_complete,
    validate_gsv_bundle,
)
from application.characters.voice.pipeline.gsv_training import (
    run_v2proplus_training,
    safe_rmtree_child,
)
from application.characters.voice.pipeline.reference_selection import (
    copy_reference_clip_to_character_speech,
    is_safe_single_dir_name,
    load_asr_transcripts,
    select_best_reference_clip,
)
from application.characters.voice.pipeline.source_acquisition import acquire_voice_sources
from application.characters.voice.pipeline.synthesis_verification import verify_tts_synthesis
from application.runtime.tasks import (
    TaskCancelled,
    _is_task_cancel_requested,
    _update_task,
)
from core.paths import resource_path


_ALLOWED_ASR_LANGS = {"auto", "zh", "ja", "en", "yue", "ko"}
_CHARACTER_PREPARE_LOCKS_GUARD = threading.Lock()
_CHARACTER_PREPARE_LOCKS: dict[str, threading.Lock] = {}


def _parse_bool_flag(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    raw = payload.get(key, default)
    if not isinstance(raw, bool):
        raise ValueError(f"{key} 必须为布尔值")
    return raw


def _parse_use_uvr(payload: Mapping[str, Any]) -> str | bool:
    raw = payload.get("useUvr", "auto")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() == "auto":
        return "auto"
    raise ValueError('useUvr 必须为布尔值或 "auto"')


def _normalize_sources(payload: Mapping[str, Any]) -> list[str]:
    raw = payload.get("sources")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [item.strip() for item in raw if item.strip()]
    raise ValueError("sources 必须为字符串列表")


def _normalize_aliases(payload: Mapping[str, Any]) -> list[str]:
    raw = payload.get("aliases")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part.strip() for part in re.split(r"[,，;/]+", raw) if part.strip()]
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [item.strip() for item in raw if item.strip()]
    raise ValueError("aliases 必须为字符串列表")


def _build_experiment_name(character_name: str, sprite_prefix: str) -> str:
    prefix = str(sprite_prefix or "").strip()
    if is_safe_single_dir_name(prefix):
        return prefix[:64]
    digest = hashlib.sha1(character_name.encode("utf-8")).hexdigest()[:10]
    return f"char_{digest}"


def _safe_task_dirname(task_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(task_id or "").strip())
    if is_safe_single_dir_name(cleaned):
        return cleaned
    return f"task_{uuid.uuid4().hex[:12]}"


@contextlib.contextmanager
def _acquire_character_prepare_lock(
    state: Any,
    task_id: str,
    character_name: str,
) -> Iterator[None]:
    """Serialize voice-preparation tasks targeting the same character while honoring cancellation."""
    with _CHARACTER_PREPARE_LOCKS_GUARD:
        char_lock = _CHARACTER_PREPARE_LOCKS.get(character_name)
        if char_lock is None:
            char_lock = threading.Lock()
            _CHARACTER_PREPARE_LOCKS[character_name] = char_lock

    waited = False
    while not char_lock.acquire(timeout=0.1):
        if _is_task_cancel_requested(state, task_id):
            raise TaskCancelled()
        if not waited and hasattr(state, "tasks"):
            waited = True
            _update_task(
                state,
                task_id,
                phase="queued",
                message=f"正在等待角色「{character_name}」的前序语音任务完成。",
            )
    try:
        if _is_task_cancel_requested(state, task_id):
            raise TaskCancelled()
        yield
    finally:
        char_lock.release()


def run_character_voice_prepare(
    state: Any,
    task_id: str,
    payload: Mapping[str, Any],
    *,
    file_access_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    """Acquire, clean (UVR5), slice, transcribe (ASR), verify synthesis, and atomically bind character voice."""
    if not isinstance(payload, Mapping):
        raise ValueError("请求参数必须为 JSON 对象")

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("角色名称（name）不能为空")

    if state.config_manager.get_character_by_name(name) is None:
        raise KeyError(f"找不到角色：{name}，请先保存角色设定。")

    sources = _normalize_sources(payload)
    aliases = _normalize_aliases(payload)
    query = str(payload.get("query") or "").strip()
    use_uvr = _parse_use_uvr(payload)
    dereverb = _parse_bool_flag(payload, "dereverb", False)
    train = _parse_bool_flag(payload, "train", False)
    verify_synthesis = _parse_bool_flag(payload, "verifySynthesis", True)
    search_community_models = _parse_bool_flag(payload, "searchCommunityModels", not train)

    asr_lang = str(payload.get("language") or "auto").strip().lower() or "auto"
    if asr_lang not in _ALLOWED_ASR_LANGS:
        raise ValueError(f"不支持的 ASR 语言参数：{asr_lang}")

    default_max_sec = 900 if train else 180
    raw_max_sec = payload.get("maxDownloadSeconds", default_max_sec)
    if isinstance(raw_max_sec, bool) or not isinstance(raw_max_sec, int) or not 15 <= raw_max_sec <= 7200:
        raise ValueError("maxDownloadSeconds 必须为 15–7200 之间的整数")

    project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd()).resolve()
    gsv_url, gsv_root, _tts_provider = resolve_gpt_sovits_settings(state, project_root)
    gsv_python, base_gpt, base_sovits = validate_gsv_bundle(gsv_root, train=train)
    profile = detect_runtime_profile()

    with _acquire_character_prepare_lock(state, task_id, name):
        state.config_manager.reload()
        character = state.config_manager.get_character_by_name(name)
        if character is None:
            raise KeyError(f"找不到角色：{name}，请先保存角色设定。")

        sprite_prefix = str(
            character.get("sprite_prefix")
            if isinstance(character, Mapping)
            else getattr(character, "sprite_prefix", "")
        ).strip()
        exp_name = _build_experiment_name(name, sprite_prefix)
        speech_subdir = sprite_prefix if is_safe_single_dir_name(sprite_prefix) else exp_name

        work_root = project_root / "cache" / "voice_prepare"
        work_dir = work_root / _safe_task_dirname(task_id)
        raw_dir = work_dir / "raw"
        clean_dir = work_dir / "clean"
        sliced_dir = work_dir / "slicer_opt" / exp_name
        asr_dir = work_dir / "asr_opt"

        safe_rmtree_child(work_root, work_dir)
        runner = CancellableGsvRunner(
            state=state,
            task_id=task_id,
            gsv_root=gsv_root,
            gsv_python=gsv_python,
            profile=profile,
        )

        community_pool: ThreadPoolExecutor | None = None
        community_future: Future[list[dict[str, Any]]] | None = None
        try:
            with runner:
                runner.check_cancelled()
                if search_community_models:
                    community_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-community")
                    community_future = community_pool.submit(
                        search_community_gsv_models,
                        name,
                        query,
                        aliases=aliases,
                        max_results=5,
                    )

                # Stage 1: Acquire audio
                _update_task(
                    state,
                    task_id,
                    phase="download",
                    progress=0.08,
                    message="正在获取角色语音素材。",
                )
                acquired = acquire_voice_sources(
                    sources=sources,
                    query=query,
                    raw_dir=raw_dir,
                    project_root=project_root,
                    gsv_root=gsv_root,
                    allowed_roots=file_access_roots,
                    max_download_seconds=raw_max_sec,
                    on_log=runner.log,
                    check_cancelled=runner.check_cancelled,
                    run_subprocess=lambda label, cmd: runner.run(label, cmd, cwd=work_dir),
                )

                # Stage 2: Optional UVR5 vocal separation
                should_run_uvr = acquired.needs_uvr_by_default if use_uvr == "auto" else bool(use_uvr)
                uvr_weights_dir = gsv_root / "tools" / "uvr5" / "uvr5_weights"
                uvr_used = False
                uvr_vocal_model = ""
                uvr_dereverb_model = ""
                slice_input_dir = raw_dir

                if should_run_uvr:
                    has_uvr_weights = uvr_weights_dir.is_dir() and any(
                        p.suffix.lower() == ".pth" for p in uvr_weights_dir.iterdir() if p.is_file()
                    )
                    if not has_uvr_weights and use_uvr == "auto":
                        runner.log(f"未检测到 UVR5 权重目录（{uvr_weights_dir}），自动跳过人声分离。")
                    else:
                        _update_task(
                            state,
                            task_id,
                            phase="uvr5",
                            progress=0.25,
                            message="正在调用 GPT-SoVITS 内置 UVR5 分离人声、去除背景音乐与杂音。",
                        )
                        uvr_script = resource_path("tools/uvr5_headless_entry.py")
                        if not uvr_script.is_file():
                            raise FileNotFoundError(f"未找到内置 UVR5 入口脚本：{uvr_script}")
                        report_path = work_dir / "uvr5_report.json"
                        uvr_cmd = runner.python_cmd(
                            uvr_script,
                            "--gsv-root",
                            str(gsv_root),
                            "--input-dir",
                            str(raw_dir),
                            "--output-dir",
                            str(clean_dir),
                            "--report-json",
                            str(report_path),
                        )
                        if dereverb:
                            uvr_cmd.append("--dereverb")
                        runner.run("UVR5 人声分离", uvr_cmd)
                        if report_path.is_file():
                            uvr_report = json.loads(report_path.read_text(encoding="utf-8"))
                            uvr_vocal_model = str(uvr_report.get("vocalModel") or "")
                            uvr_dereverb_model = str(uvr_report.get("dereverbModel") or "")
                        uvr_used = True
                        slice_input_dir = clean_dir

                # Stage 3: Audio slicing (task-isolated directory)
                _update_task(
                    state,
                    task_id,
                    phase="slice",
                    progress=0.42,
                    message="正在切分角色语音片段。",
                )
                sliced_dir.mkdir(parents=True, exist_ok=True)
                slice_cmd = runner.python_cmd(
                    "tools/slice_audio.py",
                    str(slice_input_dir),
                    str(sliced_dir),
                    "-34",
                    "4000",
                    "300",
                    "10",
                    "500",
                    "0.9",
                    "0.25",
                    "0",
                    "1",
                )
                runner.run("语音切分", slice_cmd)
                sliced_wavs = [p for p in sliced_dir.glob("*.wav") if p.is_file()]
                if not sliced_wavs:
                    raise RuntimeError("语音切分未产生任何有效 WAV 片段，请更换更清晰的角色语音来源。")

                # Stage 4: Faster-Whisper ASR (task-isolated directory)
                _update_task(
                    state,
                    task_id,
                    phase="asr",
                    progress=0.52,
                    message=f"正在运行 Faster Whisper 识别 {len(sliced_wavs)} 条语音切片文本。",
                )
                asr_dir.mkdir(parents=True, exist_ok=True)
                list_path = asr_dir / f"{exp_name}.list"
                list_path.unlink(missing_ok=True)
                model_size_arg, asr_env = resolve_asr_model_arg_and_env(gsv_root)
                asr_cmd = runner.python_cmd(
                    "tools/asr/fasterwhisper_asr.py",
                    "-i",
                    str(sliced_dir),
                    "-o",
                    str(asr_dir),
                    "-s",
                    model_size_arg,
                    "-l",
                    asr_lang,
                    "-p",
                    profile.asr_precision,
                )
                try:
                    runner.run("Faster Whisper ASR", asr_cmd, extra_env=asr_env)
                except SubprocessFailed as exc:
                    if os.name != "nt" or exc.return_code not in {0xC0000409, -1073740791}:
                        raise
                    validate_asr_list_complete(list_path)
                    runner.log("ASR 已完整写入标注文件，忽略退出清理阶段的 0xC0000409。")
                validate_asr_list_complete(list_path)

                # Stage 5: Smart reference clip selection (staged in work_dir only; do not persist yet)
                _update_task(
                    state,
                    task_id,
                    phase="select-reference",
                    progress=0.58,
                    message="正在评估切片清晰度、语速与时长，优选最佳参考语音。",
                )
                transcripts = load_asr_transcripts(list_path)
                best_clip = select_best_reference_clip([sliced_dir], transcripts)
                staged_refer_audio_str = best_clip.path.resolve().as_posix()

                # Stage 6: Default zero-shot pretrained vs optional isolated GSV fine-tuning
                if train:
                    gpt_ckpt, sovits_pth = run_v2proplus_training(
                        runner,
                        exp_name=exp_name,
                        sliced_dir=sliced_dir,
                        list_path=list_path,
                    )
                    gpt_model_str = gpt_ckpt.resolve().as_posix()
                    sovits_model_str = sovits_pth.resolve().as_posix()
                    voice_mode = "trained_v2proplus"
                else:
                    gpt_model_str = ""
                    sovits_model_str = ""
                    voice_mode = "zero_shot_pretrained"

                # Stage 7: Synthesis self-check against staged reference clip BEFORE committing
                synthesis_check: dict[str, Any] = {"verified": False, "skipped": not verify_synthesis}
                if verify_synthesis:
                    runner.check_cancelled()
                    _update_task(
                        state,
                        task_id,
                        phase="verify-synthesis",
                        progress=0.90,
                        message="正在加载预训练白模/角色权重执行短句合成校验。",
                    )
                    synthesis_check = verify_tts_synthesis(
                        state,
                        gsv_url=gsv_url,
                        gsv_root=gsv_root,
                        character_name=name,
                        gpt_model_path=gpt_model_str,
                        sovits_model_path=sovits_model_str,
                        refer_audio_path=staged_refer_audio_str,
                        prompt_text=best_clip.prompt_text,
                        prompt_lang=best_clip.prompt_lang,
                        work_dir=work_dir,
                    )

                # Stage 8: Copy permanent reference WAV & atomically merge voice fields under _mutation_lock
                runner.check_cancelled()
                _update_task(
                    state,
                    task_id,
                    phase="save-character",
                    progress=0.96,
                    message="正在绑定角色参考语音与模型设置。",
                )
                state.config_manager.reload()
                latest_before_copy = state.config_manager.get_character_by_name(name)
                if latest_before_copy is None:
                    raise KeyError(f"保存语音时找不到角色：{name}")
                latest_prefix = str(
                    latest_before_copy.get("sprite_prefix")
                    if isinstance(latest_before_copy, Mapping)
                    else getattr(latest_before_copy, "sprite_prefix", "")
                ).strip()
                speech_subdir = latest_prefix if is_safe_single_dir_name(latest_prefix) else exp_name
                ref_digest = hashlib.sha1(best_clip.path.read_bytes()).hexdigest()[:10]
                expected_ref_path = project_root / "data" / "speech" / speech_subdir / f"ref_{ref_digest}.wav"
                ref_existed_before = expected_ref_path.exists()
                persisted_ref = copy_reference_clip_to_character_speech(
                    best_clip,
                    project_root=project_root,
                    sprite_prefix=speech_subdir,
                )
                refer_audio_str = persisted_ref.resolve().as_posix()
                try:
                    saved_character = CharacterUseCase(
                        state, file_access_roots=file_access_roots
                    ).execute(
                        parse_character_request(
                            CharacterOperation.BIND_VOICE,
                            {
                                "name": name,
                                "gpt_model_path": gpt_model_str,
                                "sovits_model_path": sovits_model_str,
                                "refer_audio_path": refer_audio_str,
                                "prompt_text": best_clip.prompt_text,
                                "prompt_lang": best_clip.prompt_lang,
                            },
                        )
                    )
                except BaseException:
                    if not ref_existed_before:
                        persisted_ref.unlink(missing_ok=True)
                    raise

                community_models: list[dict[str, Any]] = []
                if community_future is not None:
                    try:
                        community_models = community_future.result(timeout=4.0)
                    except Exception:
                        community_models = []
                    if community_models:
                        runner.log(f"检测到 {len(community_models)} 个社区已训练的 GPT-SoVITS 模型候选。")

                return {
                    "name": name,
                    "mode": voice_mode,
                    "trained": train,
                    "sources": list(acquired.resolved_sources),
                    "uvrUsed": uvr_used,
                    "uvrVocalModel": uvr_vocal_model,
                    "uvrDereverbModel": uvr_dereverb_model,
                    "slicedCount": len(sliced_wavs),
                    "transcribedCount": len(transcripts),
                    "referenceAudio": {
                        "path": refer_audio_str,
                        "durationSeconds": round(best_clip.duration_seconds, 2),
                        "promptText": best_clip.prompt_text,
                        "promptLang": best_clip.prompt_lang,
                        "qualityScore": best_clip.score,
                    },
                    "models": {
                        "gptModelPath": gpt_model_str,
                        "sovitsModelPath": sovits_model_str,
                        "pretrainedFallbackGpt": base_gpt if not train else "",
                        "pretrainedFallbackSovits": base_sovits if not train else "",
                    },
                    "communityModels": community_models,
                    "synthesisCheck": synthesis_check,
                    "character": saved_character,
                }
        finally:
            if community_pool is not None:
                community_pool.shutdown(wait=False, cancel_futures=True)
            safe_rmtree_child(work_root, work_dir)
