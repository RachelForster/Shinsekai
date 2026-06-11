"""Command-line argument parsing for the desktop chat entry (main)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any


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
        "--mirror-stream-endpoint",
        type=str,
        default="",
        help="Mirror desktop chat UI updates to a bridge WebSocket endpoint while keeping the native Qt chat window.",
    )
    return parser


def parse_sprite_args(tr_i18n: Callable[..., str]) -> Any:
    return build_sprite_arg_parser(tr_i18n).parse_args()
