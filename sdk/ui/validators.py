"""通用字段校验工具，适用于设置页、表单、对话框。

每个校验函数返回 ``(ok: bool, message: str)``。
* ``ok`` —— True 表示通过
* ``message`` —— 通过时为空，失败时为面向用户的错误提示
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ── 基础校验 ──────────────────────────────────────────────────────────────────

def not_empty(value: Any, label: str = "") -> tuple[bool, str]:
    """值不能为空（None 或去除空白后为空字符串）。"""
    if value is None:
        return False, _msg("不能为空", label)
    if isinstance(value, str) and not value.strip():
        return False, _msg("不能为空", label)
    return True, ""


def not_none(value: Any, label: str = "") -> tuple[bool, str]:
    """值不能为 None。"""
    if value is None:
        return False, _msg("不能为 None", label)
    return True, ""


# ── 路径校验 ──────────────────────────────────────────────────────────────────

def file_exists(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """文件路径必须存在（跳过空值由 not_empty 负责）。"""
    if not path:
        return True, ""
    p = Path(path)
    if not p.is_file():
        return False, _msg(f"文件不存在: {p}", label)
    return True, ""


def dir_exists(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """目录路径必须存在。"""
    if not path:
        return True, ""
    p = Path(path)
    if not p.is_dir():
        return False, _msg(f"目录不存在: {p}", label)
    return True, ""


def path_exists(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """路径必须存在（文件或目录均可）。"""
    if not path:
        return True, ""
    p = Path(path)
    if not p.exists():
        return False, _msg(f"路径不存在: {p}", label)
    return True, ""


def path_is_absolute(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """路径必须是绝对路径。"""
    if not path:
        return True, ""
    if not Path(path).is_absolute():
        return False, _msg("必须填写绝对路径", label)
    return True, ""


# ── 数值校验 ──────────────────────────────────────────────────────────────────

def in_range(value: int | float, low: int | float, high: int | float,
             label: str = "") -> tuple[bool, str]:
    """数值必须在 [low, high] 区间内。"""
    if not (low <= value <= high):
        return False, _msg(f"必须介于 {low}–{high}，当前为 {value}", label)
    return True, ""


def positive(value: int | float, label: str = "") -> tuple[bool, str]:
    """数值必须 > 0。"""
    if value <= 0:
        return False, _msg("必须大于 0", label)
    return True, ""


def non_negative(value: int | float, label: str = "") -> tuple[bool, str]:
    """数值必须 ≥ 0。"""
    if value < 0:
        return False, _msg("不能为负数", label)
    return True, ""


# ── 字符串格式校验 ────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"^https?://\S+$")

def ascii_only(value: str | None, label: str = "") -> tuple[bool, str]:
    """字符串只能包含 ASCII 字符（英文字母、数字、英文标点），空值跳过。"""
    if not value:
        return True, ""
    if not value.isascii():
        return False, _msg("只能包含英文字母、数字和英文标点，不能有中文等字符", label)
    return True, ""


def audio_duration_between(path: str | None, lo: float, hi: float,
                          label: str = "") -> tuple[bool, str]:
    """音频时长必须在 [lo, hi] 秒区间内，空值跳过（使用标准库 wave，仅支持 WAV）。"""
    if not path:
        return True, ""
    try:
        import wave
        with wave.open(path, "rb") as wf:
            dur = wf.getnframes() / wf.getframerate()
        if lo <= dur <= hi:
            return True, ""
        return False, _msg(f"音频时长 {dur:.1f}s，需要 {lo}–{hi}s", label)
    except Exception as e:
        return False, _msg(f"无法读取音频: {e}", label)


def no_quotes(value: str | None, label: str = "") -> tuple[bool, str]:
    """路径不能被双引号包裹（Windows 用户常从资源管理器复制路径带入引号）。"""
    if not value:
        return True, ""
    v = value.strip()
    if v.startswith('"') and v.endswith('"'):
        return False, _msg("请不要用双引号包裹路径，去掉两边的 \" 即可", label)
    if v.startswith('"') or v.endswith('"'):
        return False, _msg("路径前后有不该出现的双引号，请删掉", label)
    return True, ""


def valid_url(url: str | None, label: str = "") -> tuple[bool, str]:
    """URL 必须以 http:// 或 https:// 开头。"""
    if not url:
        return True, ""
    if not _URL_RE.match(url.strip()):
        return False, _msg("必须以 http:// 或 https:// 开头", label)
    return True, ""


# ── 批量校验 ──────────────────────────────────────────────────────────────────

def check_all(*checks: tuple[bool, str]) -> tuple[bool, list[str]]:
    """依次执行多组校验，收集所有失败消息。

    Usage::

        ok, errors = check_all(
            not_empty(name, "名称"),
            file_exists(sovits_path, "SoVITS 模型"),
            in_range(speed, 0.1, 5.0, "语速"),
        )
        if not ok:
            show_error("\\n".join(errors))
    """
    msgs = [m for ok, m in checks if not ok]
    return (len(msgs) == 0, msgs)


def first_error(*checks: tuple[bool, str]) -> tuple[bool, str]:
    """依次执行校验，返回第一个失败结果（短路）。

    Usage::

        ok, err = first_error(
            not_empty(name, "名称"),
            file_exists(path, "路径"),
        )
    """
    for ok, msg in checks:
        if not ok:
            return False, msg
    return True, ""


# ── 弹窗提示 ──────────────────────────────────────────────────────────────────

def warn_if_invalid(checks_or_ok, errors=None, *,
                    title: str = "提示", parent=None) -> bool:
    """校验失败时弹窗警告。

    两种用法::

        # 方式1：直接传 check_all / first_error 的结果
        ok, errors = check_all(not_empty(x, "名称"))
        warn_if_invalid(ok, errors)

        # 方式2：内联校验
        if not warn_if_invalid(*check_all(
            not_empty(name, "名称"),
            file_exists(path, "路径"),
        )):
            return  # 校验失败，阻断后续流程

    返回 True 表示校验通过。
    """
    if errors is None:
        ok, msgs = checks_or_ok
    else:
        ok, msgs = checks_or_ok, errors or []
    if ok:
        return True
    if isinstance(msgs, str):
        msgs = [msgs]
    text = "\n".join(msgs)
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(parent, title, text)
    return False


def validate_or_block(*checks: tuple[bool, str],
                      title: str = "提示", parent=None) -> bool:
    """依次校验，遇到第一个失败就弹窗并返回 False。

    适合放在保存按钮逻辑开头::

        if not validate_or_block(
            not_empty(name, "名称"),
            in_range(speed, 0.1, 5.0, "语速"),
        ):
            return  # 阻断保存
    """
    ok, err = first_error(*checks)
    if ok:
        return True
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(parent, title, err)
    return False


# ── helpers ───────────────────────────────────────────────────────────────────

def _msg(reason: str, label: str) -> str:
    return f"{label}: {reason}" if label else reason
