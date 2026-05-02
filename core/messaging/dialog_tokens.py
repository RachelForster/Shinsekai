"""
LLM JSON 中 character_name 的固定保留字（新代号 + 旧版中文同义）。

- 新代号用于模板提示；老存档与旧提示仍用中文保留字，handlers 同时识别。
- TTS 路径里需与 OpenCC 结果比较时用 match_*_tts(cc, name)。
"""

from __future__ import annotations

from typing import Callable, cast
# --- 新代号（与 template_generator 一致） ---
COT = "COT"
NARR = "NARR"
CHOICE = "CHOICE"
STAT = "STAT"
SCENE = "SCENE"
BGM = "bgm"
CG = "CG"

# --- 兼容旧版/中文 ---
COT_ALIASES: frozenset[str] = frozenset({COT, "思维链"})
NARR_ALIASES: frozenset[str] = frozenset({NARR, "旁白"})
CHOICE_ALIASES: frozenset[str] = frozenset({CHOICE, "选项"})
STAT_ALIASES: frozenset[str] = frozenset({STAT, "数值"})
SCENE_ALIASES: frozenset[str] = frozenset({SCENE, "场景"})
BGM_ALIASES: frozenset[str] = frozenset({BGM, "bgm"})  # 仅小写
CG_ALIASES: frozenset[str] = frozenset({CG, "cg"})  # 允许小写

SYSTEM_DIALOG_TTS_ALIASES: frozenset[str] = (
    NARR_ALIASES | CHOICE_ALIASES | STAT_ALIASES | SCENE_ALIASES
)

# 已由专用 UI 处理、或 COT 需忽略，不应进 SystemMisc（旁白 NARR 不在此列）
SYSTEM_UI_SKIP: frozenset[str] = (
    CHOICE_ALIASES
    | STAT_ALIASES
    | SCENE_ALIASES
    | BGM_ALIASES
    | CG_ALIASES
    | COT_ALIASES
)


def _as_convert(cc) -> Callable[[str], str]:
    """TTS 侧传入的 `cc` 为 OpenCC 实例（.convert）或 callable。"""
    if hasattr(cc, "convert") and callable(getattr(cc, "convert")):
        return cast(Callable[[str], str], cc.convert)
    if callable(cc):
        return cast(Callable[[str], str], cc)
    raise TypeError(f"expected OpenCC or callable, got {type(cc)!r}")


def normalize_character_name(name: str | None) -> str:
    """Strip；将常见英文简写/大小写统一为 COT、NARR、CHOICE 等，便于与模板一致。中文名原样。"""
    s = (name or "").strip()
    if not s:
        return s
    low = s.casefold()
    ascii_to: dict[str, str] = {
        "choice": CHOICE,
        "narr": NARR,
        "stat": STAT,
        "scene": SCENE,
        "cot": COT,
        "bgm": BGM,
        "cg": CG,
    }
    if low in ascii_to:
        return ascii_to[low]
    return s


def _cc_match(cc, name: str, aliases: frozenset[str]) -> bool:
    cfn = _as_convert(cc)
    s = normalize_character_name(name)
    t = cfn(s)
    for a in aliases:
        if cfn(a) == t:
            return True
    return False


def match_cot_tts(cc, name: str) -> bool:
    return _cc_match(cc, name, COT_ALIASES)


def match_cot_name(name: str) -> bool:
    """UI 侧：是否与 COT / 思维链 等思维链角色匹配（无 OpenCC 时再比一次原始串）。"""
    t = normalize_character_name(name)
    if t in COT_ALIASES:
        return True
    return (name or "").strip() in COT_ALIASES


def match_system_dialog_tts(cc, name: str) -> bool:
    cfn = _as_convert(cc)
    s = normalize_character_name(name)
    t = cfn(s)
    for a in SYSTEM_DIALOG_TTS_ALIASES:
        if cfn(a) == t:
            return True
    return False


def match_bgm_name(name: str) -> bool:
    return normalize_character_name(name) in BGM_ALIASES


def match_cg_name(name: str) -> bool:
    return normalize_character_name(name) in CG_ALIASES


def match_choice_name(name: str) -> bool:
    return normalize_character_name(name) in CHOICE_ALIASES


def match_stat_name(name: str) -> bool:
    return normalize_character_name(name) in STAT_ALIASES


def match_scene_name(name: str) -> bool:
    return normalize_character_name(name) in SCENE_ALIASES


def is_option_history_name(name: str) -> bool:
    """与 history 里「名：内容」的「名」比较（与 dialog.option_badge 展示一致）。"""
    t = normalize_character_name(name)
    if t in CHOICE_ALIASES:
        return True
    if (name or "").strip() in ("Options", "选项"):
        return True
    return False


def is_option_history_plain(plain: str) -> bool:
    if not plain:
        return False
    s = plain.strip()
    return s.startswith(
        (
            "选项：",
            "选项:",
            "CHOICE：",
            "CHOICE:",
            "Options：",
            "Options:",
        )
    )
