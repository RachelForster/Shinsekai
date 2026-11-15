from __future__ import annotations

import io
import json
import math
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
import wave

import numpy as np
import pytest
import yaml

from application.characters import (
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
)
from application.characters.voice.pipeline import run_character_voice_prepare
from application.characters.voice.pipeline.gsv_runtime import (
    CancellableGsvRunner,
    SubprocessFailed,
)
from application.characters.voice.pipeline.gsv_training import safe_rmtree_child
from application.characters.voice.pipeline.prepare_voice import (
    _build_experiment_name,
    _normalize_aliases,
)
from application.runtime.tasks import (
    TaskCancelled,
    _create_task,
    _request_task_cancel,
)
from config.schema import Character


@pytest.fixture(autouse=True)
def _stub_community_model_search(monkeypatch):
    monkeypatch.setattr(
        "application.characters.voice.pipeline.prepare_voice.search_community_gsv_models",
        lambda *args, **kwargs: [],
    )


def _make_speech_wav_bytes(seconds: float = 5.6, rate: int = 32_000) -> bytes:
    total = max(1, int(seconds * rate))
    t = np.arange(total, dtype=np.float32) / float(rate)
    envelope = (np.sin(2.0 * math.pi * 2.4 * t) > -0.35).astype(np.float32)
    sig = np.sin(2.0 * math.pi * 210.0 * t) * 0.24 * envelope
    pad = min(int(rate * 0.05), total // 6)
    if pad > 0:
        sig[:pad] = 0.0
        sig[-pad:] = 0.0
    pcm = np.clip(sig * 32767.0, -32768.0, 32767.0).astype("<i2")

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
    def __init__(
        self,
        project_root: Path,
        gsv_root: Path,
        character: Character,
        *,
        gsv_url: str = "http://127.0.0.1:9880/",
        tts_provider: str = "gpt-sovits",
    ) -> None:
        self.project_root_dir = project_root
        self.task_lock = threading.RLock()
        self.tasks: dict[str, dict] = {}
        self._characters: dict[str, Character] = {character.name: character}

        api_config = SimpleNamespace(
            tts_provider=tts_provider,
            gpt_sovits_url=gsv_url,
            gpt_sovits_api_path=str(gsv_root),
        )
        outer = self

        class _CfgMgr:
            config = SimpleNamespace(api_config=api_config)

            @staticmethod
            def get_gpt_sovits_config():
                return (gsv_url, str(gsv_root), tts_provider)

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
                    speech_speed=kwargs.get("speech_speed", 1.0),
                    speech_volume=kwargs.get("speech_volume", 1.0),
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
    monkeypatch.setattr(
        "sdk.url_safety.socket.getaddrinfo",
        lambda host, port, *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port or 443))],
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
        return SimpleNamespace(ok=True, status_code=200, headers={}, text="", close=lambda: None)

    def fake_session_post(self, url, *args, **kwargs):
        return SimpleNamespace(ok=True, status_code=200, content=wav_5s, text="")

    monkeypatch.setattr("ai.tts.tts_adapter.requests.Session.get", fake_session_get)
    monkeypatch.setattr("ai.tts.tts_adapter.requests.Session.post", fake_session_post)

    captured_community_args: dict[str, object] = {}

    def fake_community_search(character_name: str, query: str = "", *, aliases=(), max_results: int = 5):
        captured_community_args["name"] = character_name
        captured_community_args["query"] = query
        captured_community_args["aliases"] = list(aliases)
        return [
            {
                "platform": "bilibili",
                "title": "这是一条关于山田凉和喜多郁代的模型分享",
                "url": "https://www.bilibili.com/video/BV1p2TfzrE6D",
                "author": "头上生艹_",
                "summary": "训练模型版本：v2-ProPlus",
                "downloads": 8448,
                "likes": 546,
                "score": 97.0,
            }
        ]

    monkeypatch.setattr(
        "application.characters.voice.pipeline.prepare_voice.search_community_gsv_models",
        fake_community_search,
    )

    result = run_character_voice_prepare(
        state,
        task_id,
        {
            "name": "山田凉",
            "query": "山田凉 孤独摇滚",
            "aliases": ["Ryo Yamada", "山田リョウ"],
            "useUvr": "auto",
            "train": False,
            "verifySynthesis": True,
        },
    )

    assert executed_stages == ["yt-dlp 音轨提取", "UVR5 人声分离", "语音切分", "Faster Whisper ASR"]
    assert captured_community_args == {
        "name": "山田凉",
        "query": "山田凉 孤独摇滚",
        "aliases": ["Ryo Yamada", "山田リョウ"],
    }
    assert len(result["communityModels"]) == 1
    assert result["communityModels"][0]["url"] == "https://www.bilibili.com/video/BV1p2TfzrE6D"
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


def test_prepare_character_voice_optional_training_isolates_run_and_ignores_stale_weights(monkeypatch, tmp_path):
    gsv_root = _create_fake_gsv_bundle(tmp_path, with_train_assets=True)
    local_voice = tmp_path / "clean_voice.wav"
    local_voice.write_bytes(_make_speech_wav_bytes(6.0))

    # Pre-seed higher-epoch stale weights from an older run; the current e15/e8 run MUST NOT pick them!
    stale_gpt_dir = gsv_root / "GPT_weights_v2ProPlus"
    stale_sovits_dir = gsv_root / "SoVITS_weights_v2ProPlus"
    stale_gpt_dir.mkdir(parents=True, exist_ok=True)
    stale_sovits_dir.mkdir(parents=True, exist_ok=True)
    (stale_gpt_dir / "ch_tae_01-e20.ckpt").write_bytes(b"stale-e20")
    (stale_sovits_dir / "ch_tae_01_e16_s999.pth").write_bytes(b"stale-e16")

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
    observed_run_exp = ""

    def fake_runner_run(self, label: str, command, *, cwd=None, extra_env=None):
        nonlocal observed_run_exp
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
            s2_cfg_path = Path(cmd_list[cmd_list.index("--config") + 1])
            s2_cfg = json.loads(s2_cfg_path.read_text(encoding="utf-8"))
            observed_run_exp = s2_cfg["name"]
            (stale_sovits_dir / f"{observed_run_exp}_e8_s64.pth").write_bytes(b"trained-sovits")
        elif label == "GPT 训练":
            s1_cfg_path = Path(cmd_list[cmd_list.index("--config_file") + 1])
            s1_cfg = yaml.safe_load(s1_cfg_path.read_text(encoding="utf-8"))
            exp_id = s1_cfg["train"]["exp_name"]
            (stale_gpt_dir / f"{exp_id}-e15.ckpt").write_bytes(b"trained-gpt")

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
    assert observed_run_exp.startswith("ch_tae_01_")
    assert result["mode"] == "trained_v2proplus"
    assert result["trained"] is True
    assert result["models"]["gptModelPath"].endswith(f"GPT_weights_v2ProPlus/{observed_run_exp}-e15.ckpt")
    assert result["models"]["sovitsModelPath"].endswith(f"SoVITS_weights_v2ProPlus/{observed_run_exp}_e8_s64.pth")
    # Temporary logs and config folders for this run must be cleaned up
    assert not (gsv_root / "logs" / observed_run_exp).exists()
    assert not (gsv_root / "TEMP" / "shinsekai_voice_prepare" / observed_run_exp).exists()


def test_reserved_dot_sprite_prefix_never_deletes_parent_or_shared_dirs(monkeypatch, tmp_path):
    assert _build_experiment_name("角色A", ".").startswith("char_")
    assert _build_experiment_name("角色A", "..").startswith("char_")
    assert _build_experiment_name("角色A", ".hidden").startswith("char_")

    parent = tmp_path / "logs"
    parent.mkdir()
    sentinel = parent / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(PermissionError):
        safe_rmtree_child(parent, parent / ".")
    with pytest.raises(PermissionError):
        safe_rmtree_child(parent, parent / "..")
    assert sentinel.is_file()

    gsv_root = _create_fake_gsv_bundle(tmp_path)
    local_voice = tmp_path / "clean_voice.wav"
    wav_5s = _make_speech_wav_bytes(5.2)
    local_voice.write_bytes(wav_5s)

    # Character with sprite_prefix=".." (permitted by legacy ASCII character validator)
    dotdot_char = Character(name="特殊角色", color="#d07d7d", sprite_prefix="..")
    state = _FakeState(tmp_path, gsv_root, dotdot_char)
    task = _create_task(state, kind="character-voice-prepare", title="dotdot")

    def fake_run(self, label: str, command, *, cwd=None, extra_env=None):
        cmd_list = [str(x) for x in command]
        if label == "语音切分":
            sdir = Path(cmd_list[cmd_list.index("tools/slice_audio.py") + 2])
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "001.wav").write_bytes(wav_5s)
        elif label == "Faster Whisper ASR":
            sdir = Path(cmd_list[cmd_list.index("-i") + 1])
            adir = Path(cmd_list[cmd_list.index("-o") + 1])
            adir.mkdir(parents=True, exist_ok=True)
            (adir / f"{sdir.name}.list").write_text(
                f"{sdir / '001.wav'}|sp|ZH|你好，今天天气很不错。\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        "application.characters.voice.pipeline.gsv_runtime.CancellableGsvRunner.run",
        fake_run,
    )
    result = run_character_voice_prepare(
        state,
        task["id"],
        {"name": "特殊角色", "sources": [str(local_voice)], "useUvr": False, "verifySynthesis": False},
        file_access_roots=(tmp_path,),
    )
    assert gsv_root.is_dir()
    assert "/data/speech/char_" in result["referenceAudio"]["path"]


def test_uvr5_script_resolved_from_source_root_when_project_root_is_separate(monkeypatch, tmp_path):
    bundled_source = tmp_path / "bundled_source"
    user_project = tmp_path / "writable_user_data"
    user_project.mkdir(parents=True)
    uvr_entry = bundled_source / "tools" / "uvr5_headless_entry.py"
    uvr_entry.parent.mkdir(parents=True)
    uvr_entry.write_text("# bundled uvr5 entry\n", encoding="utf-8")

    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", str(bundled_source))

    gsv_root = _create_fake_gsv_bundle(tmp_path)
    wav_5s = _make_speech_wav_bytes(5.5)
    local_voice = user_project / "raw_voice.wav"
    local_voice.write_bytes(wav_5s)

    state = _FakeState(user_project, gsv_root, Character(name="打包角色", color="#d07d7d", sprite_prefix="ch_pkg"))
    task = _create_task(state, kind="character-voice-prepare", title="packaged")
    seen_uvr_script: list[Path] = []

    def fake_run(self, label: str, command, *, cwd=None, extra_env=None):
        cmd_list = [str(x) for x in command]
        if "UVR5" in label:
            seen_uvr_script.append(Path(cmd_list[5]))
            out_dir = Path(cmd_list[cmd_list.index("--output-dir") + 1])
            report = Path(cmd_list[cmd_list.index("--report-json") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "vocal.wav").write_bytes(wav_5s)
            report.write_text(json.dumps({"vocalModel": "HP2_all_vocals", "dereverbModel": ""}), encoding="utf-8")
        elif label == "语音切分":
            sdir = Path(cmd_list[cmd_list.index("tools/slice_audio.py") + 2])
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "001.wav").write_bytes(wav_5s)
        elif label == "Faster Whisper ASR":
            sdir = Path(cmd_list[cmd_list.index("-i") + 1])
            adir = Path(cmd_list[cmd_list.index("-o") + 1])
            adir.mkdir(parents=True, exist_ok=True)
            (adir / f"{sdir.name}.list").write_text(
                f"{sdir / '001.wav'}|pkg|JA|こんにちは、今日も元気だよ。\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        "application.characters.voice.pipeline.gsv_runtime.CancellableGsvRunner.run",
        fake_run,
    )
    run_character_voice_prepare(
        state,
        task["id"],
        {"name": "打包角色", "sources": [str(local_voice)], "useUvr": True, "verifySynthesis": False},
        file_access_roots=(user_project,),
    )
    assert seen_uvr_script == [uvr_entry.resolve()]


def test_remote_gpt_sovits_and_kaggle_endpoints_are_rejected_before_download(monkeypatch, tmp_path):
    gsv_root = _create_fake_gsv_bundle(tmp_path)
    char = Character(name="远程角色", color="#d07d7d", sprite_prefix="ch_remote")

    acquire_called = False

    def fail_if_called(**_kwargs):
        nonlocal acquire_called
        acquire_called = True
        raise AssertionError("acquire_voice_sources should not be called for remote GSV")

    monkeypatch.setattr(
        "application.characters.voice.pipeline.prepare_voice.acquire_voice_sources",
        fail_if_called,
    )

    remote_state = _FakeState(tmp_path, gsv_root, char, gsv_url="https://remote-gsv.example.com:9880/")
    t1 = _create_task(remote_state, kind="character-voice-prepare", title="remote")
    with pytest.raises(ValueError, match="本机回环"):
        run_character_voice_prepare(remote_state, t1["id"], {"name": "远程角色", "query": "test"})

    kaggle_state = _FakeState(tmp_path, gsv_root, char, tts_provider="kaggle-gpt-sovits")
    t2 = _create_task(kaggle_state, kind="character-voice-prepare", title="kaggle")
    with pytest.raises(ValueError, match="Kaggle"):
        run_character_voice_prepare(kaggle_state, t2["id"], {"name": "远程角色", "query": "test"})

    assert acquire_called is False


def test_synthesis_self_check_failure_does_not_commit_character_or_orphan_speech_file(monkeypatch, tmp_path):
    gsv_root = _create_fake_gsv_bundle(tmp_path)
    wav_5s = _make_speech_wav_bytes(5.4)
    local_voice = tmp_path / "voice.wav"
    local_voice.write_bytes(wav_5s)

    initial_char = Character(
        name="自检失败角色",
        color="#d07d7d",
        sprite_prefix="ch_fail_verify",
        refer_audio_path="",
        prompt_text="",
    )
    state = _FakeState(tmp_path, gsv_root, initial_char)
    task = _create_task(state, kind="character-voice-prepare", title="verify-fail")

    def fake_run(self, label: str, command, *, cwd=None, extra_env=None):
        cmd_list = [str(x) for x in command]
        if label == "语音切分":
            sdir = Path(cmd_list[cmd_list.index("tools/slice_audio.py") + 2])
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "001.wav").write_bytes(wav_5s)
        elif label == "Faster Whisper ASR":
            sdir = Path(cmd_list[cmd_list.index("-i") + 1])
            adir = Path(cmd_list[cmd_list.index("-o") + 1])
            adir.mkdir(parents=True, exist_ok=True)
            (adir / f"{sdir.name}.list").write_text(
                f"{sdir / '001.wav'}|fv|JA|テスト用のセリフです、よろしくね。\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        "application.characters.voice.pipeline.gsv_runtime.CancellableGsvRunner.run",
        fake_run,
    )
    monkeypatch.setattr(
        "ai.tts.tts_adapter.requests.Session.get",
        lambda self, *a, **kw: SimpleNamespace(ok=True, status_code=200, text=""),
    )
    # Return empty/invalid audio so verify_tts_synthesis fails!
    monkeypatch.setattr(
        "ai.tts.tts_adapter.requests.Session.post",
        lambda self, *a, **kw: SimpleNamespace(ok=True, status_code=200, content=b"", text=""),
    )

    with pytest.raises(RuntimeError, match="短句合成自检失败"):
        run_character_voice_prepare(
            state,
            task["id"],
            {
                "name": "自检失败角色",
                "sources": [str(local_voice)],
                "useUvr": False,
                "verifySynthesis": True,
            },
            file_access_roots=(tmp_path,),
        )

    unchanged = state.config_manager.get_character_by_name("自检失败角色")
    assert unchanged.refer_audio_path == ""
    assert unchanged.prompt_text == ""
    assert not list((tmp_path / "data" / "speech").rglob("*.wav"))


def test_atomic_bind_voice_preserves_concurrent_character_edits_and_serializes_same_character(monkeypatch, tmp_path):
    gsv_root = _create_fake_gsv_bundle(tmp_path)
    wav_5s = _make_speech_wav_bytes(5.4)
    local_voice = tmp_path / "voice.wav"
    local_voice.write_bytes(wav_5s)

    initial_char = Character(
        name="并发角色",
        color="#4a6fa5",
        sprite_prefix="ch_concurrent",
        character_setting="旧设定",
        speech_speed=1.0,
    )
    state = _FakeState(tmp_path, gsv_root, initial_char)

    active_runs = 0
    max_concurrent_runs = 0
    counter_lock = threading.Lock()

    def fake_run(self, label: str, command, *, cwd=None, extra_env=None):
        nonlocal active_runs, max_concurrent_runs
        cmd_list = [str(x) for x in command]
        with counter_lock:
            active_runs += 1
            max_concurrent_runs = max(max_concurrent_runs, active_runs)
        try:
            if label == "语音切分":
                time.sleep(0.05)
                # Simulate a user saving new character_setting and speech_speed mid-pipeline!
                CharacterUseCase(state, file_access_roots=(tmp_path,)).execute(
                    parse_character_request(
                        CharacterOperation.SAVE,
                        {
                            "originalName": "并发角色",
                            "character": {
                                "name": "并发角色",
                                "color": "#4a6fa5",
                                "sprite_prefix": "ch_concurrent",
                                "character_setting": "并发更新后的新设定",
                                "speech_speed": 1.25,
                            },
                        },
                    )
                )
                sdir = Path(cmd_list[cmd_list.index("tools/slice_audio.py") + 2])
                sdir.mkdir(parents=True, exist_ok=True)
                (sdir / "001.wav").write_bytes(wav_5s)
            elif label == "Faster Whisper ASR":
                sdir = Path(cmd_list[cmd_list.index("-i") + 1])
                adir = Path(cmd_list[cmd_list.index("-o") + 1])
                adir.mkdir(parents=True, exist_ok=True)
                (adir / f"{sdir.name}.list").write_text(
                    f"{sdir / '001.wav'}|cc|ZH|这是并发测试的参考语音片段。\n",
                    encoding="utf-8",
                )
        finally:
            with counter_lock:
                active_runs -= 1

    monkeypatch.setattr(
        "application.characters.voice.pipeline.gsv_runtime.CancellableGsvRunner.run",
        fake_run,
    )

    t1 = _create_task(state, kind="character-voice-prepare", title="run1")
    t2 = _create_task(state, kind="character-voice-prepare", title="run2")
    errors: list[BaseException] = []

    def _worker(tid: str):
        try:
            run_character_voice_prepare(
                state,
                tid,
                {
                    "name": "并发角色",
                    "sources": [str(local_voice)],
                    "useUvr": False,
                    "verifySynthesis": False,
                },
                file_access_roots=(tmp_path,),
            )
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    th1 = threading.Thread(target=_worker, args=(t1["id"],))
    th2 = threading.Thread(target=_worker, args=(t2["id"],))
    th1.start()
    th2.start()
    th1.join(timeout=10)
    th2.join(timeout=10)

    assert not errors
    assert max_concurrent_runs == 1

    final_char = state.config_manager.get_character_by_name("并发角色")
    assert final_char.character_setting == "并发更新后的新设定"
    assert final_char.speech_speed == 1.25
    assert final_char.prompt_text == "这是并发测试的参考语音片段。"
    assert Path(final_char.refer_audio_path).is_file()


def test_posix_kill_tree_terminates_process_group_and_reaps(monkeypatch):
    signals_sent: list[tuple[int, int]] = []
    waited_timeouts: list[float] = []

    class _FakePosixProc:
        pid = 4242
        _dead = False

        def poll(self):
            return 0 if self._dead else None

        def wait(self, timeout=None):
            waited_timeouts.append(timeout)
            if not self._dead:
                raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)
            return -9

        def terminate(self):
            pass

        def kill(self):
            self._dead = True

    proc = _FakePosixProc()
    sigkill_num = getattr(signal, "SIGKILL", 9)

    def fake_killpg(pgid: int, sig: int):
        signals_sent.append((pgid, int(sig)))
        if int(sig) == int(sigkill_num):
            proc._dead = True

    monkeypatch.setattr("application.characters.voice.pipeline.gsv_runtime.os.name", "posix")
    monkeypatch.setattr("application.characters.voice.pipeline.gsv_runtime.os.getpgid", lambda pid: 7777, raising=False)
    monkeypatch.setattr("application.characters.voice.pipeline.gsv_runtime.os.killpg", fake_killpg, raising=False)
    monkeypatch.setattr("application.characters.voice.pipeline.gsv_runtime.signal.SIGKILL", sigkill_num, raising=False)

    CancellableGsvRunner._kill_tree(proc)  # type: ignore[arg-type]

    assert signals_sent == [(7777, int(signal.SIGTERM)), (7777, int(sigkill_num))]
    assert len(waited_timeouts) == 2


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


def test_community_model_search_failure_or_disable_never_blocks_voice_prepare(monkeypatch, tmp_path):
    assert _normalize_aliases({"aliases": "Furina, 芙卡洛斯 / Focalors"}) == ["Furina", "芙卡洛斯", "Focalors"]
    with pytest.raises(ValueError, match="aliases"):
        _normalize_aliases({"aliases": 123})

    gsv_root = _create_fake_gsv_bundle(tmp_path)
    wav_5s = _make_speech_wav_bytes(5.4)
    local_voice = tmp_path / "voice.wav"
    local_voice.write_bytes(wav_5s)
    state = _FakeState(tmp_path, gsv_root, Character(name="容错角色", color="#d07d7d", sprite_prefix="ch_resilient"))

    def fake_run(self, label: str, command, *, cwd=None, extra_env=None):
        cmd_list = [str(x) for x in command]
        if label == "语音切分":
            sdir = Path(cmd_list[cmd_list.index("tools/slice_audio.py") + 2])
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "001.wav").write_bytes(wav_5s)
        elif label == "Faster Whisper ASR":
            sdir = Path(cmd_list[cmd_list.index("-i") + 1])
            adir = Path(cmd_list[cmd_list.index("-o") + 1])
            adir.mkdir(parents=True, exist_ok=True)
            (adir / f"{sdir.name}.list").write_text(
                f"{sdir / '001.wav'}|rs|ZH|即使社区模型搜索超时，主流程依然正常完成。\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        "application.characters.voice.pipeline.gsv_runtime.CancellableGsvRunner.run",
        fake_run,
    )

    called_count = 0

    def exploding_search(*_args, **_kwargs):
        nonlocal called_count
        called_count += 1
        raise RuntimeError("simulated community search crash")

    monkeypatch.setattr(
        "application.characters.voice.pipeline.prepare_voice.search_community_gsv_models",
        exploding_search,
    )

    t1 = _create_task(state, kind="character-voice-prepare", title="resilient-1")
    res1 = run_character_voice_prepare(
        state,
        t1["id"],
        {"name": "容错角色", "sources": [str(local_voice)], "useUvr": False, "verifySynthesis": False},
        file_access_roots=(tmp_path,),
    )
    assert called_count == 1
    assert res1["communityModels"] == []
    assert res1["mode"] == "zero_shot_pretrained"

    t2 = _create_task(state, kind="character-voice-prepare", title="resilient-2")
    res2 = run_character_voice_prepare(
        state,
        t2["id"],
        {
            "name": "容错角色",
            "sources": [str(local_voice)],
            "useUvr": False,
            "verifySynthesis": False,
            "searchCommunityModels": False,
        },
        file_access_roots=(tmp_path,),
    )
    assert called_count == 1  # Not called when searchCommunityModels=False
    assert res2["communityModels"] == []

