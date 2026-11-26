"""通用字段校验工具，适用于设置页、表单、对话框。

每个校验函数返回 ``(ok: bool, message: str)``。
* ``ok`` —— True 表示通过
* ``message`` —— 通过时为空，失败时为面向用户的错误提示
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from i18n import tr
from sdk.path_utils import reject_control_chars, safe_existing_path


def _local_input_roots() -> tuple[Path, ...]:
    """Trusted roots for form fields that reference local files.

    Cover the whole local machine like the file picker does (all existing
    drives on Windows, the filesystem anchor elsewhere), otherwise saving a
    form whose paths live outside cwd/temp/home fails with "outside the
    allowed roots".
    """

    roots = [Path.cwd(), Path(tempfile.gettempdir())]
    try:
        roots.append(Path.home())
    except RuntimeError:
        pass
    if os.name == "nt":
        for code in range(ord("A"), ord("Z") + 1):
            drive = Path(f"{chr(code)}:/")
            if drive.exists():
                roots.append(drive)
    else:
        anchor = Path("/")
        if anchor.exists():
            roots.append(anchor)
    return tuple(dict.fromkeys(roots))


# ── 基础校验 ──────────────────────────────────────────────────────────────────

def not_empty(value: Any, label: str = "") -> tuple[bool, str]:
    """值不能为空（None 或去除空白后为空字符串）。"""
    if value is None:
        return False, _msg(tr("validator.not_empty"), label)
    if isinstance(value, str) and not value.strip():
        return False, _msg(tr("validator.not_empty"), label)
    return True, ""


def not_none(value: Any, label: str = "") -> tuple[bool, str]:
    """值不能为 None。"""
    if value is None:
        return False, _msg(tr("validator.not_none"), label)
    return True, ""


# ── 路径校验 ──────────────────────────────────────────────────────────────────

def file_exists(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """文件路径必须存在（跳过空值由 not_empty 负责）。"""
    if not path:
        return True, ""
    try:
        p = safe_existing_path(
            reject_control_chars(str(path), field=label or "path"),
            roots=_local_input_roots(),
            field=label or "path",
        )
    except (OSError, ValueError) as exc:
        return False, str(exc)
    if not p.is_file():
        return False, _msg(tr("validator.file_not_found", path=p), label)
    return True, ""


def dir_exists(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """目录路径必须存在。"""
    if not path:
        return True, ""
    try:
        p = safe_existing_path(
            reject_control_chars(str(path), field=label or "path"),
            roots=_local_input_roots(),
            field=label or "path",
        )
    except (OSError, ValueError) as exc:
        return False, str(exc)
    if not p.is_dir():
        return False, _msg(tr("validator.dir_not_found", path=p), label)
    return True, ""


def path_exists(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """路径必须存在（文件或目录均可）。"""
    if not path:
        return True, ""
    try:
        p = safe_existing_path(
            reject_control_chars(str(path), field=label or "path"),
            roots=_local_input_roots(),
            field=label or "path",
        )
    except (OSError, ValueError) as exc:
        return False, str(exc)
    if not p.exists():
        return False, _msg(tr("validator.path_not_found", path=p), label)
    return True, ""


def path_is_absolute(path: str | Path | None, label: str = "") -> tuple[bool, str]:
    """路径必须是绝对路径。"""
    if not path:
        return True, ""
    try:
        p = Path(reject_control_chars(str(path), field=label or "path"))
    except ValueError as exc:
        return False, str(exc)
    if not p.is_absolute():
        return False, _msg(tr("validator.path_not_absolute"), label)
    return True, ""


# ── 数值校验 ──────────────────────────────────────────────────────────────────

def in_range(value: int | float, low: int | float, high: int | float,
             label: str = "") -> tuple[bool, str]:
    """数值必须在 [low, high] 区间内。"""
    if not (low <= value <= high):
        return False, _msg(tr("validator.out_of_range", low=low, high=high, value=value), label)
    return True, ""


def positive(value: int | float, label: str = "") -> tuple[bool, str]:
    """数值必须 > 0。"""
    if value <= 0:
        return False, _msg(tr("validator.must_be_positive"), label)
    return True, ""


def non_negative(value: int | float, label: str = "") -> tuple[bool, str]:
    """数值必须 ≥ 0。"""
    if value < 0:
        return False, _msg(tr("validator.must_be_non_negative"), label)
    return True, ""


# ── 字符串格式校验 ────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"^https?://\S+$")

def ascii_only(value: str | None, label: str = "") -> tuple[bool, str]:
    """字符串只能包含 ASCII 字符（英文字母、数字、英文标点），空值跳过。"""
    if not value:
        return True, ""
    if not value.isascii():
        return False, _msg(tr("validator.ascii_only"), label)
    return True, ""


def audio_duration_between(path: str | None, lo: float, hi: float,
                          label: str = "") -> tuple[bool, str]:
    """音频时长必须在 [lo, hi] 秒区间内，空值跳过（支持 WAV/MP3/OGG）。"""
    if not path:
        return True, ""
    dur = _audio_duration(path)
    if dur is None:
        return False, _msg(tr("validator.audio_unreadable"), label)
    if lo <= dur <= hi:
        return True, ""
    return False, _msg(tr("validator.audio_duration_range", dur=f"{dur:.1f}", lo=lo, hi=hi), label)


def _audio_duration(path: str) -> float | None:
    """获取音频时长（秒），WAV 用标准库，MP3/OGG 用 pydub。"""
    ext = Path(path).suffix.lower()
    if ext == ".wav":
        try:
            import wave
            with wave.open(path, "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            return None
    else:
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(path)
            return len(audio) / 1000.0
        except Exception:
            return None


def no_quotes(value: str | None, label: str = "") -> tuple[bool, str]:
    """路径不能被双引号包裹（Windows 用户常从资源管理器复制路径带入引号）。"""
    if not value:
        return True, ""
    v = value.strip()
    if v.startswith('"') and v.endswith('"'):
        return False, _msg(tr("validator.no_surrounding_quotes"), label)
    if v.startswith('"') or v.endswith('"'):
        return False, _msg(tr("validator.no_quotes"), label)
    return True, ""


def valid_url(url: str | None, label: str = "") -> tuple[bool, str]:
    """URL 必须以 http:// 或 https:// 开头。"""
    if not url:
        return True, ""
    if not _URL_RE.match(url.strip()):
        return False, _msg(tr("validator.invalid_url"), label)
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
                    title: str | None = None, parent=None) -> bool:
    """Return ``False`` and emit a warning when validation fails.

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
    del parent
    import warnings

    resolved_title = tr("validator.default_title") if title is None else title
    warnings.warn(f"{resolved_title}: {text}", stacklevel=2)
    return False


def validate_or_block(*checks: tuple[bool, str],
                      title: str | None = None, parent=None) -> bool:
    """Return ``False`` and emit a warning for the first failed check.

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
    del parent
    import warnings

    resolved_title = tr("validator.default_title") if title is None else title
    warnings.warn(f"{resolved_title}: {err}", stacklevel=2)
    return False


# ── helpers ───────────────────────────────────────────────────────────────────

def _msg(reason: str, label: str) -> str:
    return f"{label}: {reason}" if label else reason
