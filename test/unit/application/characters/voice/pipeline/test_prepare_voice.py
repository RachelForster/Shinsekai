from __future__ import annotations

import io
import json
import math
from pathlib import Path
import threading
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from application.characters.voice.pipeline import run_character_voice_prepare
from application.characters.voice.pipeline.gsv_runtime import SubprocessFailed
from application.runtime.tasks import TaskCancelled, _create_task, _request_task_cancel
from config.schema import Character


def _make_speech_wav_bytes(seconds: float = 5.6, rate: int = 32_000) -> bytes:
    total = max(1, int(seconds * rate))
    t = np.arange(total, dtype=np.float32) / float(rate)
    envelope = (np.sin(2.0 * math.pi * 2.4 * t) > -0.35).astype(np.float32)
    signal = np.sin(2.0 * math.pi * 210.0 * t) * 0.24 * envelope
    pad = min(int(rate * 0.05), total // 6)
    if pad > 0:
        signal[:pad] = 0.0
        signal[-pad:] = 0.0
    pcm = np.clip(signal * 32767.0, -32768.0, 32767.0).astype("<i2")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return buf.getvalue()


def _create_fake_gsv_bundle(root: Path, *, with_train_assets: bool = True) -> Path:
    gsv = root / "GPT-SoVITS"
    files = [
        gsv / "api_v2.py",
        gsv / "runtime" / "python.exe",
        gsv / "runtime" / "python",
        gsv / "ffmpeg.exe",
        gsv / "tools" / "slice_audio.py",
        gsv / "tools" / "asr" / "fasterwhisper_asr.py",
        gsv / "tools" / "uvr5" / "uvr5_weights" / "HP2_all_vocals.pth",
        gsv / "GPT_SoVITS" / "pretrained_models" / "s1v3.ckpt",
        gsv / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2ProPlus.pth",
    ]
    if with_train_assets:
        files.extend(
            [
                gsv / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Dv2ProPlus.pth",
                gsv / "GPT_SoVITS" / "pretrained_models" / "chinese-hubert-base" / "config.json",
                gsv / "GPT_SoVITS" / "pretrained_models" / "chinese-roberta-wwm-ext-large" / "config.json",
                gsv / "GPT_SoVITS" / "pretrained_models" / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt",
            ]
        )
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"stub")

    if with_train_assets:
        s2_cfg = gsv / "GPT_SoVITS" / "configs" / "s2v2ProPlus.json"
        s2_cfg.parent.mkdir(parents=True, exist_ok=True)
        s2_cfg.write_text(
            json.dumps({"train": {}, "model": {}, "data": {}}),
            encoding="utf-8",
        )
        s1_cfg = gsv / "GPT_SoVITS" / "configs" / "s1longer-v2.yaml"
        s1_cfg.write_text("train:\n  epochs: 10\n", encoding="utf-8")
    return gsv


class _FakeState:
    def __init__(self, project_root: Path, gsv_root: Path, character: Character) -> None:
        self.project_root_dir = project_root
        self.task_lock = threading.RLock()
        self.tasks: dict[str, dict] = {}
        self._characters: dict[str, Character] = {character.name: character}

        api_config = SimpleNamespace(
            tts_provider="gpt-sovits",
            gpt_sovits_url="http://127.0.0.1:9880/",
            gpt_sovits_api_path=str(gsv_root),
        )
        outer = self

        class _CfgMgr:
            config = SimpleNamespace(api_config=api_config)

            @staticmethod
            def get_gpt_sovits_config():
                return ("http://127.0.0.1:9880/", str(gsv_root), "gpt-sovits")

            @staticmethod
            def merged_tts_factory_kwargs(_provider, base):
                return dict(base)

            @staticmethod
            def reload():
                return None

            @staticmethod
            def get_character_by_name(name: str):
                return outer._characters.get(name)

        class _CharMgr:
            @staticmethod
            def add_character(
                saved_name,
                color,
                sprite_prefix,
                gpt_model_path,
                sovits_model_path,
                refer_audio_path,
                prompt_text,
                prompt_lang,
                character_setting,
                **kwargs,
            ):
                existing = outer._characters.get(kwargs.get("edit_as_name") or saved_name)
                sprites = list(existing.sprites) if existing else []
                updated = Character(
                    name=saved_name,
                    color=color,
                    sprite_prefix=sprite_prefix,
                    gpt_model_path=gpt_model_path,
                    sovits_model_path=sovits_model_path,
                    refer_audio_path=refer_audio_path,
                    prompt_text=prompt_text,
                    prompt_lang=prompt_lang,
                    character_setting=character_setting,
                    character_brief=kwargs.get("character_brief", ""),
                    emotion_tags=kwargs.get("emotion_tags", ""),
                    sprites=sprites,
                )
                outer._characters[saved_name] = updated
                return ("保存成功", list(outer._characters))

        self.config_manager = _CfgMgr()
        self.character_manager = _CharMgr()


def test_prepare_character_voice_default_zero_shot_pretrained_flow(monkeypatch, tmp_path):
    gsv_root = _create_fake_gsv_bundle(tmp_path)
    initial_char = Character(
        name="山田凉",
        color="#4a6fa5",
        sprite_prefix="ch_ryo_demo",
        character_brief="下北泽贝斯手，冷面幽默。",
        character_setting="山田凉的背景信息：\n1.姓名和出处：山田凉，《孤独摇滚》。",
        sprites=[{"path": "data/sprite/ch_ryo_demo/01.png", "tagging": "平静"}],
    )
    state = _FakeState(tmp_path, gsv_root, initial_char)
    task = _create_task(state, kind="character-voice-prepare", title="准备语音")
    task_id = task["id"]

    yt_dlp_path = tmp_path / "data" / "tools" / "yt-dlp" / ("yt-dlp.exe" if hasattr(Path, "drive") else "yt-dlp")
    yt_dlp_path.parent.mkdir(parents=True, exist_ok=True)
    yt_dlp_path.write_bytes(b"yt-dlp")
    monkeypatch.setattr(
        "application.characters.voice.pipeline.source_acquisition.ensure_yt_dlp_binary",
        lambda *args, **kwargs: yt_dlp_path,
    )
    monkeypatch.setattr(
        "application.characters.voice.pipeline.source_acquisition.search_bilibili_voice_urls",
        lambda query, **kwargs: ["https://www.bilibili.com/video/BV1xx411c7mD"],
    )

    wav_5s = _make_speech_wav_bytes(5.6)
    wav_2s = _make_speech_wav_bytes(2.0)
    executed_stages: list[str] = []

    def fake_runner_run(self, label: str, command, *, cwd=None, extra_env=None):
        executed_stages.append(label)
        cmd_list = [str(x) for x in command]
        if "yt-dlp" in label:
            out_idx = cmd_list.index("-o") + 1
            out_dir = Path(cmd_list[out_idx]).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "video_001_BV1xx411c7mD.wav").write_bytes(wav_5s)
        elif "UVR5" in label:
            out_dir = Path(cmd_list[cmd_list.index("--output-dir") + 1])
            report_path = Path(cmd_list[cmd_list.index("--report-json") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "vocal_0001.wav").write_bytes(wav_5s)
            report_path.write_text(
                json.dumps(
                    {
                        "vocalModel": "HP2_all_vocals",
                        "dereverbModel": "",
                        "outputs": [str(out_dir / "vocal_0001.wav")],
                    }
                ),
                encoding="utf-8",
            )
        elif label == "语音切分":
            sliced_dir = Path(cmd_list[cmd_list.index("tools/slice_audio.py") + 2])
            sliced_dir.mkdir(parents=True, exist_ok=True)
            (sliced_dir / "001_short.wav").write_bytes(wav_2s)
            (sliced_dir / "002_good.wav").write_bytes(wav_5s)
        elif label == "Faster Whisper ASR":
            sliced_dir = Path(cmd_list[cmd_list.index("-i") + 1])
            asr_dir = Path(cmd_list[cmd_list.index("-o") + 1])
            asr_dir.mkdir(parents=True, exist_ok=True)
            list_file = asr_dir / f"{sliced_dir.name}.list"
            list_file.write_text(
                f"{sliced_dir / '001_short.wav'}|ryo|JA|うん。\n"
                f"{sliced_dir / '002_good.wav'}|ryo|JA|あの、ベースの山田リョウです。今日もよろしく。\n",
                encoding="utf-8",
            )
            if hasattr(pytest, "WindowsError") or "nt" in __import__("os").name:
                raise SubprocessFailed(label, 0xC0000409, "teardown")

    monkeypatch.setattr(
        "application.characters.voice.pipeline.gsv_runtime.CancellableGsvRunner.run",
        fake_runner_run,
    )

    switched_weights: list[tuple[str, str]] = []

    def fake_session_get(self, url, *args, **kwargs):
        if url.endswith("set_gpt_weights") or url.endswith("set_sovits_weights"):
            switched_weights.append((url.rsplit("/", 1)[-1], kwargs["params"]["weights_path"]))
        return SimpleNamespace(ok=True, status_code=200, text="")

    def fake_session_post(self, url, *args, **kwargs):
        return SimpleNamespace(ok=True, status_code=200, content=wav_5s, text="")

    monkeypatch.setattr("ai.tts.tts_adapter.requests.Session.get", fake_session_get)
    monkeypatch.setattr("ai.tts.tts_adapter.requests.Session.post", fake_session_post)

    result = run_character_voice_prepare(
        state,
        task_id,
        {
            "name": "山田凉",
            "query": "山田凉 孤独摇滚",
            "useUvr": "auto",
            "train": False,
            "verifySynthesis": True,
        },
    )

    assert executed_stages == ["yt-dlp 音轨提取", "UVR5 人声分离", "语音切分", "Faster Whisper ASR"]
    assert result["mode"] == "zero_shot_pretrained"
    assert result["trained"] is False
    assert result["uvrUsed"] is True
    assert result["uvrVocalModel"] == "HP2_all_vocals"
    assert result["referenceAudio"]["promptLang"] == "ja"
    assert result["referenceAudio"]["promptText"] == "あの、ベースの山田リョウです。今日もよろしく。"
    assert Path(result["referenceAudio"]["path"]).is_file()
    assert "data/speech/ch_ryo_demo/" in result["referenceAudio"]["path"]

    saved = state.config_manager.get_character_by_name("山田凉")
    assert saved.gpt_model_path == ""
    assert saved.sovits_model_path == ""
    assert saved.refer_audio_path == result["referenceAudio"]["path"]
    assert len(saved.sprites) == 1

    assert result["synthesisCheck"]["verified"] is True
    assert switched_weights == [
        ("set_gpt_weights", (gsv_root / "GPT_SoVITS/pretrained_models/s1v3.ckpt").resolve().as_posix()),
        ("set_sovits_weights", (gsv_root / "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth").resolve().as_posix()),
    ]


def test_prepare_character_voice_optional_training_binds_finetuned_weights(monkeypatch, tmp_path):
    gsv_root = _create_fake_gsv_bundle(tmp_path, with_train_assets=True)
    local_voice = tmp_path / "clean_voice.wav"
    local_voice.write_bytes(_make_speech_wav_bytes(6.0))

    initial_char = Character(
        name="多惠",
        color="#d07d7d",
        sprite_prefix="ch_tae_01",
        character_setting="多惠的背景信息：\n1.姓名和出处：花园多惠。",
    )
    state = _FakeState(tmp_path, gsv_root, initial_char)
    task = _create_task(state, kind="character-voice-prepare", title="训练语音")
    wav_6s = _make_speech_wav_bytes(6.0)
    stages: list[str] = []

    def fake_runner_run(self, label: str, command, *, cwd=None, extra_env=None):
        stages.append(label)
        cmd_list = [str(x) for x in command]
        if label == "语音切分":
            sliced_dir = Path(cmd_list[cmd_list.index("tools/slice_audio.py") + 2])
            sliced_dir.mkdir(parents=True, exist_ok=True)
            (sliced_dir / "001.wav").write_bytes(wav_6s)
        elif label == "Faster Whisper ASR":
            sliced_dir = Path(cmd_list[cmd_list.index("-i") + 1])
            asr_dir = Path(cmd_list[cmd_list.index("-o") + 1])
            asr_dir.mkdir(parents=True, exist_ok=True)
            (asr_dir / f"{sliced_dir.name}.list").write_text(
                f"{sliced_dir / '001.wav'}|tae|JA|今日もギターの練習を頑張ろうね。\n",
                encoding="utf-8",
            )
        elif label == "1A 文本特征提取":
            opt_dir = Path(extra_env["opt_dir"])
            (opt_dir / "2-name2text-0.txt").write_text("001.wav\tphonemes\tword2ph\ttext\n", encoding="utf-8")
        elif label == "1C 语义 Token 提取":
            opt_dir = Path(extra_env["opt_dir"])
            (opt_dir / "6-name2semantic-0.tsv").write_text("001.wav\t1 2 3 4\n", encoding="utf-8")
        elif label == "SoVITS 训练":
            wdir = gsv_root / "SoVITS_weights_v2ProPlus"
            wdir.mkdir(parents=True, exist_ok=True)
            (wdir / "ch_tae_01_e8_s64.pth").write_bytes(b"trained-sovits")
        elif label == "GPT 训练":
            wdir = gsv_root / "GPT_weights_v2ProPlus"
            wdir.mkdir(parents=True, exist_ok=True)
            (wdir / "ch_tae_01-e15.ckpt").write_bytes(b"trained-gpt")

    monkeypatch.setattr(
        "application.characters.voice.pipeline.gsv_runtime.CancellableGsvRunner.run",
        fake_runner_run,
    )

    result = run_character_voice_prepare(
        state,
        task["id"],
        {
            "name": "多惠",
            "sources": [str(local_voice)],
            "useUvr": False,
            "train": True,
            "verifySynthesis": False,
        },
        file_access_roots=(tmp_path,),
    )

    assert stages == [
        "语音切分",
        "Faster Whisper ASR",
        "1A 文本特征提取",
        "1B HuBERT/WAV32K 特征提取",
        "1B 说话人向量提取",
        "1C 语义 Token 提取",
        "SoVITS 训练",
        "GPT 训练",
    ]
    assert result["mode"] == "trained_v2proplus"
    assert result["trained"] is True
    assert result["models"]["gptModelPath"].endswith("GPT_weights_v2ProPlus/ch_tae_01-e15.ckpt")
    assert result["models"]["sovitsModelPath"].endswith("SoVITS_weights_v2ProPlus/ch_tae_01_e8_s64.pth")


def test_prepare_character_voice_respects_task_cancellation(tmp_path):
    gsv_root = _create_fake_gsv_bundle(tmp_path)
    local_voice = tmp_path / "clean_voice.wav"
    local_voice.write_bytes(_make_speech_wav_bytes(5.0))

    initial_char = Character(name="测试角色", color="#d07d7d", sprite_prefix="ch_cancel")
    state = _FakeState(tmp_path, gsv_root, initial_char)
    task = _create_task(state, kind="character-voice-prepare", title="取消测试")
    _request_task_cancel(state, task["id"])

    with pytest.raises(TaskCancelled):
        run_character_voice_prepare(
            state,
            task["id"],
            {"name": "测试角色", "sources": [str(local_voice)]},
            file_access_roots=(tmp_path,),
        )
    assert not (tmp_path / "cache" / "voice_prepare" / task["id"]).exists()


def test_character_voice_prepare_route_and_bundled_skill_budget(monkeypatch, tmp_path):
    from application.agent.skills import bundled_skill_paths
    from core.paths import resource_path
    from frontend_bridge_core.routes.api import _API_ROUTER
    from frontend_bridge_core.routes.router import ApiRequest, TaskResponse

    policy_text = Path(resource_path("assets/agent/system-policy.md")).read_text(encoding="utf-8")
    skill_blocks = [
        f"## {ref}\n\n{Path(src).read_text(encoding='utf-8')}"
        for ref, src in bundled_skill_paths().items()
    ]
    combined = (
        policy_text
        + "\n\n# 宿主预载的任务 skills\n\n"
        + "下方已提供完整技能正文。根据用户任务匹配使用，无需再读取技能文件。"
        + "技能说明不授予工具权限；只有当前实际提供的工具可以执行操作。\n\n"
        + "\n\n".join(skill_blocks)
    )
    assert len(combined.encode("utf-8")) <= 65536

    match = _API_ROUTER.match("POST", "/api/characters/voice/prepare")
    assert match is not None
    captured = {}

    def fake_prepare(state, task_id, body, *, file_access_roots=()):
        captured["task_id"] = task_id
        captured["body"] = dict(body)
        return {"ok": True}

    monkeypatch.setattr(
        "frontend_bridge_core.routes.character_routes.run_character_voice_prepare",
        fake_prepare,
    )
    fake_state = SimpleNamespace(project_root_dir=tmp_path)
    req = ApiRequest(
        state=fake_state,
        method="POST",
        path="/api/characters/voice/prepare",
        query={},
        params={},
        body={"name": "山田凉", "query": "山田凉 语音合集", "train": False},
    )
    resp = match.route.handler(req)
    assert isinstance(resp, TaskResponse)
    assert resp.kind == "character-voice-prepare"
    assert resp.worker("task-xyz") == {"ok": True}
    assert captured["task_id"] == "task-xyz"
    assert captured["body"]["name"] == "山田凉"
    assert captured["body"]["train"] is False
