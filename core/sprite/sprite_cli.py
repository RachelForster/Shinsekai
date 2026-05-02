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
        "--room_id",
        type=str,
        default="",
        help=tr_i18n("main.arg_room_help"),
    )
    return parser


def parse_sprite_args(tr_i18n: Callable[..., str]) -> Any:
    return build_sprite_arg_parser(tr_i18n).parse_args()
