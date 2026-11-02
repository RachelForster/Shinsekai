"""Shared voice-tag grammar for synthesis and presentation."""

import re

VOICE_TAG_PATTERN = re.compile(r"\[([\w-]+)\]")


def strip_voice_tags(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", VOICE_TAG_PATTERN.sub("", text)).strip()
