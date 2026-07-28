"""Command-line argument parsing for the desktop chat entry (main)."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from typing import Any


CHAT_LAUNCH_CONFIG_ENV = "SHINSEKAI_CHAT_LAUNCH_CONFIG"
_MAX_LAUNCH_CONFIG_CHARS = 64 * 1024


def build_sprite_arg_parser(tr_i18n: Callable[..., str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=tr_i18n("main.arg_desc"))
    parser.add_argument(
        "--template",
        "-t",
        type=str,
        help=tr_i18n("main.arg_t_help"),
        default="komaeda_sprite",
    )
    parser.add_argument("--init_sprite_path", "-isp", type=str, default="")
    parser.add_argument("--history", "--his", type=str, default="")
    parser.add_argument("--tts", type=str, default="")
    parser.add_argument("--llm", type=str, default="deepseek")
    parser.add_argument("--bg", type=str, default="")
    parser.add_argument("--effect_names", type=str, default="")
    parser.add_argument(
        "--characters",
        type=str,
        default="",
        help="JSON array or comma-separated character names selected for this chat.",
    )
    parser.add_argument("--t2i", type=str, default="ComfyUI")
    parser.add_argument(
        "--workflow",
        type=str,
        default="",
        help="Path to the workflow YAML to run. Defaults to the built-in desktop workflow.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Run without the desktop window. "
            "Defaults to assets/system/workflow/headless.yaml "
            "(LLM→TTS→headless sink; no pygame audio). "
            "Override with --workflow to supply a custom workflow."
        ),
    )
    parser.add_argument(
        "--room_id",
        type=str,
        default="",
        help=tr_i18n("main.arg_room_help"),
    )
    parser.add_argument(
        "--stream-endpoint",
        type=str,
        default="",
        help="Connect the chat worker to a bridge WebSocket endpoint instead of opening the desktop chat window.",
    )
    parser.add_argument(
        "--init-stream-endpoint",
        type=str,
        default="",
        help="Report chat initialization progress to a bridge WebSocket while preserving the selected UI runtime.",
    )
    parser.add_argument(
        "--mirror-stream-endpoint",
        type=str,
        default="",
        help="Mirror desktop chat UI updates to a bridge WebSocket endpoint while keeping the native Qt chat window.",
    )
    return parser


def load_sprite_launch_config() -> dict[str, Any]:
    """Load bridge-provided argument defaults without placing them in subprocess argv."""

    raw = os.environ.pop(CHAT_LAUNCH_CONFIG_ENV, "").strip()
    if not raw:
        return {}
    if len(raw) > _MAX_LAUNCH_CONFIG_CHARS:
        raise ValueError("chat launch config is too large")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("chat launch config must be a JSON object")

    parser = build_sprite_arg_parser(lambda key: key)
    allowed = {action.dest for action in parser._actions if action.dest != "help"}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"unsupported chat launch config keys: {sorted(unknown)!r}")

    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if key == "headless":
            if not isinstance(value, bool):
                raise ValueError("chat launch config headless must be boolean")
            normalized[key] = value
            continue
        if not isinstance(value, str):
            raise ValueError(f"chat launch config {key} must be a string")
        normalized[key] = value
    return normalized


def parse_sprite_args(
    tr_i18n: Callable[..., str],
    *,
    defaults: dict[str, Any] | None = None,
) -> Any:
    parser = build_sprite_arg_parser(tr_i18n)
    if defaults:
        parser.set_defaults(**defaults)
    return parser.parse_args()
