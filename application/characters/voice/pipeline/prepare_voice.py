"""End-to-end character voice preparation coordinator (default zero-shot pretrained, optional GSV fine-tuning)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from application.characters import (
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
)
from application.characters.voice.pipeline.gsv_runtime import (
    CancellableGsvRunner,
    SubprocessFailed,
    detect_runtime_profile,
    resolve_asr_model_arg_and_env,
    resolve_gpt_sovits_settings,
    validate_asr_list_complete,
    validate_gsv_bundle,
)
from application.characters.voice.pipeline.gsv_training import run_v2proplus_training
from application.characters.voice.pipeline.reference_selection import (
    copy_reference_clip_to_character_speech,
    load_asr_transcripts,
    select_best_reference_clip,
)
from application.characters.voice.pipeline.source_acquisition import acquire_voice_sources
from application.characters.voice.pipeline.synthesis_verification import verify_tts_synthesis
from application.runtime.state import _jsonify
from application.runtime.tasks import TaskCancelled, _update_task


_SAFE_EXP_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_ALLOWED_ASR_LANGS = {"auto", "zh", "ja", "en", "yue", "ko"}


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


def _build_experiment_name(character_name: str, sprite_prefix: str) -> str:
    prefix = str(sprite_prefix or "").strip()
    if prefix and _SAFE_EXP_RE.fullmatch(prefix):
        return prefix[:64]
    digest = hashlib.sha1(character_name.encode("utf-8")).hexdigest()[:10]
    return f"char_{digest}"


def run_character_voice_prepare(
    state: Any,
    task_id: str,
    payload: Mapping[str, Any],
    *,
    file_access_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    """Acquire, clean (UVR5), slice, transcribe (ASR), pick optimal reference clip, and bind character voice."""
    if not isinstance(payload, Mapping):
        raise ValueError("请求参数必须为 JSON 对象")

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("角色名称（name）不能为空")

    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise KeyError(f"找不到角色：{name}，请先保存角色设定。")

    sources = _normalize_sources(payload)
    query = str(payload.get("query") or "").strip()
    use_uvr = _parse_use_uvr(payload)
    dereverb = _parse_bool_flag(payload, "dereverb", False)
    train = _parse_bool_flag(payload, "train", False)
    verify_synthesis = _parse_bool_flag(payload, "verifySynthesis", True)

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
    runner = CancellableGsvRunner(
        state=state,
        task_id=task_id,
        gsv_root=gsv_root,
        gsv_python=gsv_python,
        profile=profile,
    )

    sprite_prefix = str(
        character.get("sprite_prefix")
        if isinstance(character, Mapping)
        else getattr(character, "sprite_prefix", "")
    ).strip()
    exp_name = _build_experiment_name(name, sprite_prefix)

    work_dir = project_root / "cache" / "voice_prepare" / task_id
    raw_dir = work_dir / "raw"
    clean_dir = work_dir / "clean"
    if train:
        sliced_dir = gsv_root / "output" / "slicer_opt" / exp_name
        asr_dir = gsv_root / "output" / "asr_opt"
        if sliced_dir.exists():
            shutil.rmtree(sliced_dir, ignore_errors=True)
    else:
        sliced_dir = work_dir / "slicer_opt" / exp_name
        asr_dir = work_dir / "asr_opt"

    try:
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
                uvr_script = project_root / "tools" / "uvr5_headless_entry.py"
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

        # Stage 3: Audio slicing
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

        # Stage 4: Faster-Whisper ASR
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

        # Stage 5: Smart reference clip selection & permanent copy
        _update_task(
            state,
            task_id,
            phase="select-reference",
            progress=0.58,
            message="正在评估切片清晰度、语速与时长，优选最佳参考语音。",
        )
        transcripts = load_asr_transcripts(list_path)
        best_clip = select_best_reference_clip([sliced_dir], transcripts)
        persisted_ref = copy_reference_clip_to_character_speech(
            best_clip,
            project_root=project_root,
            sprite_prefix=sprite_prefix or exp_name,
        )
        refer_audio_str = persisted_ref.resolve().as_posix()

        # Stage 6: Default zero-shot pretrained vs optional GSV fine-tuning
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

        # Stage 7: Persist voice fields onto latest character state without clobbering concurrent sprite imports
        runner.check_cancelled()
        _update_task(
            state,
            task_id,
            phase="save-character",
            progress=0.92,
            message="正在绑定角色参考语音与模型设置。",
        )
        state.config_manager.reload()
        latest_character = state.config_manager.get_character_by_name(name)
        if latest_character is None:
            raise KeyError(f"保存语音时找不到角色：{name}")
        char_payload = dict(_jsonify(latest_character))
        char_payload.update(
            {
                "gpt_model_path": gpt_model_str,
                "sovits_model_path": sovits_model_str,
                "refer_audio_path": refer_audio_str,
                "prompt_text": best_clip.prompt_text,
                "prompt_lang": best_clip.prompt_lang,
            }
        )
        saved_character = CharacterUseCase(
            state, file_access_roots=file_access_roots
        ).execute(
            parse_character_request(
                CharacterOperation.SAVE,
                {"originalName": name, "character": char_payload},
            )
        )

        # Stage 8: Synthesis self-check
        synthesis_check: dict[str, Any] = {"verified": False, "skipped": not verify_synthesis}
        if verify_synthesis:
            runner.check_cancelled()
            _update_task(
                state,
                task_id,
                phase="verify-synthesis",
                progress=0.96,
                message="正在加载预训练白模/角色权重执行短句合成校验。",
            )
            synthesis_check = verify_tts_synthesis(
                state,
                gsv_url=gsv_url,
                gsv_root=gsv_root,
                character_name=name,
                gpt_model_path=gpt_model_str,
                sovits_model_path=sovits_model_str,
                refer_audio_path=refer_audio_str,
                prompt_text=best_clip.prompt_text,
                prompt_lang=best_clip.prompt_lang,
                work_dir=work_dir,
            )

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
            "synthesisCheck": synthesis_check,
            "character": saved_character,
        }
    except TaskCancelled:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
