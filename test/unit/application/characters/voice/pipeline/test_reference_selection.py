from __future__ import annotations

import math
from pathlib import Path
import wave

import numpy as np
import pytest

from application.characters.voice.pipeline.reference_selection import (
    copy_reference_clip_to_character_speech,
    is_hallucinated_transcript,
    load_asr_transcripts,
    score_reference_candidate,
    select_best_reference_clip,
)
from application.characters.voice.pipeline.wav_acoustics import analyze_wav_acoustics
from tools.uvr5_headless_entry import select_dereverb_weight, select_vocal_weight


def _write_speech_like_wav(
    path: Path,
    *,
    seconds: float,
    amplitude: float = 0.25,
    rate: int = 32_000,
    quiet_edges: bool = True,
    clip: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = max(1, int(seconds * rate))
    t = np.arange(total, dtype=np.float32) / float(rate)
    envelope = (np.sin(2.0 * math.pi * 2.5 * t) > -0.35).astype(np.float32)
    signal = np.sin(2.0 * math.pi * 220.0 * t) * amplitude * envelope
    if quiet_edges and total > int(rate * 0.2):
        pad = int(rate * 0.06)
        signal[:pad] = 0.0
        signal[-pad:] = 0.0
    if clip:
        signal = np.clip(signal * 12.0, -1.0, 1.0)
    pcm = np.clip(signal * 32767.0, -32768.0, 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def test_hallucination_detector_rejects_whisper_artifacts_and_accepts_dialogue():
    assert is_hallucinated_transcript("")
    assert is_hallucinated_transcript("……？！")
    assert is_hallucinated_transcript("字幕")
    assert is_hallucinated_transcript("请不吝点赞 订阅 转发 打赏支持明镜与点点栏目")
    assert is_hallucinated_transcript("ご視聴ありがとうございました！")
    assert is_hallucinated_transcript("啊啊啊啊啊啊啊啊啊啊")
    assert not is_hallucinated_transcript("あの、ベースの山田リョウです。よろしく。")
    assert not is_hallucinated_transcript("先别急着下结论，让我再检查一遍。")


def test_select_best_reference_clip_prefers_clean_conversational_clip(tmp_path):
    sliced = tmp_path / "slicer_opt" / "ryo"
    too_short = sliced / "01_short.wav"
    too_long = sliced / "02_long.wav"
    silent = sliced / "03_silent.wav"
    clipped = sliced / "04_clipped.wav"
    hallucinated = sliced / "05_hallucinated.wav"
    mediocre = sliced / "06_mediocre.wav"
    ideal = sliced / "07_ideal.wav"

    _write_speech_like_wav(too_short, seconds=2.1)
    _write_speech_like_wav(too_long, seconds=11.4)
    _write_speech_like_wav(silent, seconds=5.5, amplitude=0.0001)
    _write_speech_like_wav(clipped, seconds=5.5, amplitude=0.5, clip=True)
    _write_speech_like_wav(hallucinated, seconds=5.6, amplitude=0.22)
    _write_speech_like_wav(mediocre, seconds=3.2, amplitude=0.06, quiet_edges=False)
    _write_speech_like_wav(ideal, seconds=5.8, amplitude=0.22, quiet_edges=True)

    asr_list = tmp_path / "asr_opt" / "ryo.list"
    asr_list.parent.mkdir(parents=True, exist_ok=True)
    asr_list.write_text(
        "\n".join(
            [
                f"{too_short}|ryo|JA|うん、わかった。",
                f"{too_long}|ryo|JA|今日はスタジオの予約が入っているから、遅れないように機材を持って集合してね。",
                f"{silent}|ryo|JA|聞こえてるかな、テスト中だよ。",
                f"{clipped}|ryo|JA|ちょっと音が大きすぎたかもしれないね。",
                f"{hallucinated}|ryo|ZH|谢谢观看，请不吝点赞订阅！",
                f"{mediocre}|ryo|JA|えっと、その件だけど",
                f"{ideal}|ryo|JA|あの、ベースの山田リョウです。今日もよろしくね。",
            ]
        ),
        encoding="utf-8",
    )

    transcripts = load_asr_transcripts(asr_list)
    assert score_reference_candidate(too_short, *transcripts[too_short.name]) is None
    assert score_reference_candidate(too_long, *transcripts[too_long.name]) is None
    assert score_reference_candidate(silent, *transcripts[silent.name]) is None
    assert score_reference_candidate(clipped, *transcripts[clipped.name]) is None
    assert score_reference_candidate(hallucinated, *transcripts[hallucinated.name]) is None

    winner = select_best_reference_clip([sliced], transcripts)
    assert winner.path == ideal
    assert winner.prompt_lang == "ja"
    assert winner.prompt_text == "あの、ベースの山田リョウです。今日もよろしくね。"
    assert 5.5 <= winner.duration_seconds <= 6.0

    copied = copy_reference_clip_to_character_speech(
        winner,
        project_root=tmp_path,
        sprite_prefix="ch_ryo_01",
    )
    assert copied.is_file()
    assert copied.parent == (tmp_path / "data" / "speech" / "ch_ryo_01").resolve()
    assert analyze_wav_acoustics(copied) is not None

    with pytest.raises(ValueError, match="目录前缀"):
        copy_reference_clip_to_character_speech(
            winner,
            project_root=tmp_path,
            sprite_prefix="../escape",
        )


def test_uvr5_weight_selection_prefers_hp2_and_deecho_normal(tmp_path):
    weights = tmp_path / "uvr5_weights"
    weights.mkdir(parents=True)
    (weights / "VR-DeEchoNormal.pth").write_bytes(b"deecho")
    (weights / "HP5_only_main_vocal.pth").write_bytes(b"hp5")
    assert select_vocal_weight(weights).name == "HP5_only_main_vocal.pth"

    (weights / "HP2_all_vocals.pth").write_bytes(b"hp2")
    assert select_vocal_weight(weights).name == "HP2_all_vocals.pth"
    assert select_vocal_weight(weights, explicit_name="HP5_only_main_vocal").name == "HP5_only_main_vocal.pth"
    assert select_dereverb_weight(weights) == ("deecho", weights / "VR-DeEchoNormal.pth")
