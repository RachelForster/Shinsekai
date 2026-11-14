"""Automated character voice preparation pipeline (source acquisition, UVR5, ASR, reference selection, training)."""

from application.characters.voice.pipeline.bilibili_search import search_bilibili_voice_urls
from application.characters.voice.pipeline.prepare_voice import run_character_voice_prepare
from application.characters.voice.pipeline.reference_selection import (
    ReferenceCandidate,
    copy_reference_clip_to_character_speech,
    is_hallucinated_transcript,
    load_asr_transcripts,
    score_reference_candidate,
    select_best_reference_clip,
)
from application.characters.voice.pipeline.source_acquisition import (
    AcquiredVoiceSources,
    acquire_voice_sources,
)
from application.characters.voice.pipeline.wav_acoustics import (
    WavAcoustics,
    analyze_wav_acoustics,
)
from application.characters.voice.pipeline.yt_dlp_extractor import ensure_yt_dlp_binary

__all__ = [
    "AcquiredVoiceSources",
    "ReferenceCandidate",
    "WavAcoustics",
    "acquire_voice_sources",
    "analyze_wav_acoustics",
    "copy_reference_clip_to_character_speech",
    "ensure_yt_dlp_binary",
    "is_hallucinated_transcript",
    "load_asr_transcripts",
    "run_character_voice_prepare",
    "score_reference_candidate",
    "search_bilibili_voice_urls",
    "select_best_reference_clip",
]
