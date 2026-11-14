"""Score and select optimal 3-10s reference voice clips from sliced + ASR outputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shutil

from application.characters.voice.pipeline.wav_acoustics import (
    WavAcoustics,
    analyze_wav_acoustics,
    audio_duration_from_span,
)


REF_MIN_SECONDS = 3.0
REF_MAX_SECONDS = 10.0
REF_IDEAL_MIN_SECONDS = 4.5
REF_IDEAL_MAX_SECONDS = 7.5
AUDIO_SUFFIXES = {".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_SPOKEN_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9]")
_TERMINAL_PUNCT_RE = re.compile(r"[。！？.!?…～~」』）\)]$")

_PROMPT_LANGS = {
    "ja": "ja",
    "jp": "ja",
    "all_ja": "ja",
    "japanese": "ja",
    "zh": "zh",
    "cn": "zh",
    "yue": "zh",
    "all_zh": "zh",
    "chinese": "zh",
    "en": "en",
    "english": "en",
}

_HALLUCINATION_SUBSTRINGS = (
    "谢谢观看",
    "感谢观看",
    "请不吝点赞",
    "点赞订阅",
    "明镜与点点",
    "优优独播剧场",
    "字幕组",
    "字幕制作",
    "amara.org",
    "subtitles by",
    "thank you for watching",
    "thanks for watching",
    "ご視聴ありがとうございました",
    "チャンネル登録",
    "高評価よろしく",
)

_HALLUCINATION_EXACT = {
    "字幕",
    "音乐",
    "bgm",
    "music",
    "applause",
    "掌声",
    "笑声",
}


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    path: Path
    duration_seconds: float
    prompt_text: str
    prompt_lang: str
    score: float
    acoustics: WavAcoustics | None = None


def normalize_prompt_lang(raw: str, text: str = "") -> str:
    key = str(raw or "").strip().lower()
    if key in _PROMPT_LANGS:
        return _PROMPT_LANGS[key]
    if any("\u3040" <= ch <= "\u30ff" for ch in text):
        return "ja"
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return "zh"
    if any("a" <= ch.lower() <= "z" for ch in text):
        return "en"
    return "ja"


def load_asr_transcripts(list_path: Path) -> dict[str, tuple[str, str]]:
    """Parse GPT-SoVITS `.list` lines (`path|speaker|lang|text`) keyed by filename."""
    if not list_path.is_file():
        return {}
    try:
        lines = list_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    transcripts: dict[str, tuple[str, str]] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.count("|") < 3:
            continue
        audio_path, _speaker, lang, text = line.split("|", 3)
        filename = Path(audio_path.strip()).name
        prompt = text.strip()
        if not filename or not prompt:
            continue
        transcripts[filename] = (prompt, normalize_prompt_lang(lang, prompt))
    return transcripts


def is_hallucinated_transcript(text: str) -> bool:
    """Detect empty, punctuation-only, repetitive, or Whisper BGM hallucination text."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return True

    spoken = _SPOKEN_CHAR_RE.findall(cleaned)
    if not spoken:
        return True

    lowered = cleaned.casefold()
    if lowered in _HALLUCINATION_EXACT:
        return True
    for phrase in _HALLUCINATION_SUBSTRINGS:
        if phrase in lowered:
            return True

    if len(spoken) >= 8:
        counts: dict[str, int] = {}
        for ch in spoken:
            key = ch.casefold()
            counts[key] = counts.get(key, 0) + 1
        most_common = max(counts.values())
        if len(counts) <= 2 and most_common / len(spoken) >= 0.75:
            return True
    return False


def _duration_score(duration: float, min_seconds: float, max_seconds: float) -> float:
    if REF_IDEAL_MIN_SECONDS <= duration <= REF_IDEAL_MAX_SECONDS:
        return 35.0
    if duration < REF_IDEAL_MIN_SECONDS:
        span = max(0.01, REF_IDEAL_MIN_SECONDS - min_seconds)
        ratio = max(0.0, (duration - min_seconds) / span)
        return 18.0 + 17.0 * ratio
    span = max(0.01, max_seconds - REF_IDEAL_MAX_SECONDS)
    ratio = max(0.0, (max_seconds - duration) / span)
    return 20.0 + 15.0 * ratio


def _speaking_rate_score(text: str, lang: str, duration: float) -> float | None:
    if duration <= 0:
        return None
    if lang == "en":
        units = len(_ASCII_TOKEN_RE.findall(text))
        ideal_low, ideal_high, min_rate, max_rate = 1.8, 4.2, 0.5, 7.0
    elif lang == "zh":
        units = len(_SPOKEN_CHAR_RE.findall(text))
        ideal_low, ideal_high, min_rate, max_rate = 2.4, 6.0, 0.7, 10.5
    else:
        units = len(_SPOKEN_CHAR_RE.findall(text))
        ideal_low, ideal_high, min_rate, max_rate = 3.0, 7.8, 0.8, 13.0

    rate = units / duration
    if rate < min_rate or rate > max_rate:
        return None
    if ideal_low <= rate <= ideal_high:
        return 25.0
    if rate < ideal_low:
        return 10.0 + 15.0 * ((rate - min_rate) / max(0.01, ideal_low - min_rate))
    return 10.0 + 15.0 * ((max_rate - rate) / max(0.01, max_rate - ideal_high))


def _acoustic_score(acoustics: WavAcoustics) -> float:
    if -26.0 <= acoustics.rms_dbfs <= -12.0:
        loudness = 12.0
    elif acoustics.rms_dbfs < -26.0:
        loudness = max(2.0, 12.0 - (-26.0 - acoustics.rms_dbfs) * 0.7)
    else:
        loudness = max(2.0, 12.0 - (acoustics.rms_dbfs - (-12.0)) * 0.9)

    if 0.48 <= acoustics.voiced_ratio <= 0.88:
        activity = 8.0
    elif acoustics.voiced_ratio < 0.48:
        activity = max(1.0, 8.0 * (acoustics.voiced_ratio / 0.48))
    else:
        activity = max(4.0, 8.0 - (acoustics.voiced_ratio - 0.88) * 20.0)

    if acoustics.clip_ratio == 0.0 and acoustics.peak <= 0.96:
        headroom = 5.0
    else:
        headroom = max(0.0, 5.0 - acoustics.clip_ratio * 250.0 - max(0.0, acoustics.peak - 0.96) * 25.0)

    return loudness + activity + headroom


def score_reference_candidate(
    path: Path,
    prompt_text: str,
    prompt_lang: str,
    *,
    min_seconds: float = REF_MIN_SECONDS,
    max_seconds: float = REF_MAX_SECONDS,
    allow_silent_fallback: bool = False,
) -> ReferenceCandidate | None:
    acoustics = analyze_wav_acoustics(path)
    duration = acoustics.duration_seconds if acoustics is not None else audio_duration_from_span(path)
    if duration is None or duration < min_seconds or duration > max_seconds:
        return None

    cleaned_text = str(prompt_text or "").strip()
    if is_hallucinated_transcript(cleaned_text):
        return None

    lang = normalize_prompt_lang(prompt_lang, cleaned_text)
    rate_pts = _speaking_rate_score(cleaned_text, lang, duration)
    if rate_pts is None:
        if not allow_silent_fallback:
            return None
        rate_pts = 5.0

    dur_pts = _duration_score(duration, min_seconds, max_seconds)
    punct_pts = 7.0 if _TERMINAL_PUNCT_RE.search(cleaned_text) else 2.5

    if acoustics is not None:
        is_bad_acoustics = (
            acoustics.rms_dbfs < -42.0
            or acoustics.clip_ratio > 0.02
            or acoustics.voiced_ratio < 0.20
        )
        if is_bad_acoustics:
            if not allow_silent_fallback:
                return None
            acoust_pts = 1.0
            edge_pts = 1.0
        else:
            acoust_pts = _acoustic_score(acoustics)
            edge_quiet = (
                acoustics.edge_rms_dbfs <= acoustics.rms_dbfs - 8.0
                or acoustics.edge_rms_dbfs <= -35.0
            )
            edge_pts = 8.0 if edge_quiet else 3.0
    else:
        if not allow_silent_fallback:
            return None
        acoust_pts = 2.0
        edge_pts = 2.0

    total = round(dur_pts + rate_pts + acoust_pts + edge_pts + punct_pts, 3)
    return ReferenceCandidate(
        path=path,
        duration_seconds=duration,
        prompt_text=cleaned_text,
        prompt_lang=lang,
        score=total,
        acoustics=acoustics,
    )


def select_best_reference_clip(
    sliced_dirs: Sequence[Path],
    transcripts: Mapping[str, tuple[str, str]],
    *,
    min_seconds: float = REF_MIN_SECONDS,
    max_seconds: float = REF_MAX_SECONDS,
    allow_untranscribed_fallback: bool = False,
    allow_silent_fallback: bool = False,
) -> ReferenceCandidate:
    """Pick the highest-scoring reference audio clip across candidate slicer directories."""
    audio_files: list[Path] = []
    for directory in sliced_dirs:
        if not directory.is_dir():
            continue
        audio_files.extend(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
        )
    audio_files.sort(key=lambda item: item.name)
    if not audio_files:
        raise ValueError("未找到任何切分后的候选音频文件。")

    scored: list[ReferenceCandidate] = []
    untranscribed_fallback: ReferenceCandidate | None = None

    for path in audio_files:
        transcript = transcripts.get(path.name)
        if transcript:
            candidate = score_reference_candidate(
                path,
                transcript[0],
                transcript[1],
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                allow_silent_fallback=allow_silent_fallback,
            )
            if candidate is not None:
                scored.append(candidate)
                continue
        elif allow_untranscribed_fallback and untranscribed_fallback is None:
            acoustics = analyze_wav_acoustics(path)
            duration = (
                acoustics.duration_seconds
                if acoustics is not None
                else audio_duration_from_span(path)
            )
            if duration is not None and min_seconds <= duration <= max_seconds:
                untranscribed_fallback = ReferenceCandidate(
                    path=path,
                    duration_seconds=duration,
                    prompt_text="",
                    prompt_lang="",
                    score=0.0,
                    acoustics=acoustics,
                )

    if scored:
        scored.sort(
            key=lambda item: (
                -item.score,
                abs(item.duration_seconds - 6.0),
                item.path.name,
            )
        )
        return scored[0]

    if untranscribed_fallback is not None:
        return untranscribed_fallback

    raise ValueError(
        f"未找到满足质量要求且时长在 {min_seconds:g}–{max_seconds:g} 秒之间的有效参考语音切片。"
    )


def copy_reference_clip_to_character_speech(
    candidate: ReferenceCandidate,
    *,
    project_root: Path,
    sprite_prefix: str,
) -> Path:
    """Copy the selected reference WAV into `data/speech/<sprite_prefix>/` for permanent storage."""
    prefix = str(sprite_prefix or "").strip()
    if not prefix or "/" in prefix or "\\" in prefix or ".." in prefix:
        raise ValueError(f"无效的人物语音目录前缀：{sprite_prefix!r}")
    if candidate.path.suffix.lower() != ".wav":
        raise ValueError("参考语音切片必须为 WAV 格式。")

    target_dir = project_root.resolve() / "data" / "speech" / prefix
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(candidate.path.read_bytes()).hexdigest()[:10]
    destination = target_dir / f"ref_{digest}.wav"
    if destination.resolve() != candidate.path.resolve():
        shutil.copy2(candidate.path, destination)
    return destination
