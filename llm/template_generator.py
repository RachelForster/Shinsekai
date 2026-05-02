from typing import Any

from i18n import tr as tr_i18n
from sdk.lang import normalize_lang
from config.character_manager import ConfigManager
from core.messaging.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT
from llm.tools.tool_manager import ToolManager

config_manager = ConfigManager()

# 与配置中的背景名一致，勿翻译（UI 默认选此项；旧名「透明背景」仍识别）
TRANSPARENT_BG = "透明场景"
_TRANSPARENT_ALIAS = "透明背景"


def is_transparent_background(name: str | None) -> bool:
    if name is None:
        return True
    s = str(name).strip()
    if not s:
        return True
    return s in (TRANSPARENT_BG, _TRANSPARENT_ALIAS)


def _T(key: str, **kwargs) -> str:
    return tr_i18n(f"template_gen.{key}", **kwargs)


def _summarize_tool_parameters(parameters: Any) -> str:
    if not parameters or not isinstance(parameters, dict):
        return ""
    props = parameters.get("properties")
    if not isinstance(props, dict) or not props:
        return ""
    raw_req = parameters.get("required")
    required: set[str] = (
        {str(x) for x in raw_req} if isinstance(raw_req, list) else set()
    )
    parts: list[str] = []
    for key in sorted(props.keys()):
        spec = props.get(key)
        if isinstance(spec, dict):
            ptype = str(spec.get("type", "string"))
        else:
            ptype = "string"
        mark = "*" if str(key) in required else ""
        parts.append(f"{key}{mark}: {ptype}")
    summary = ", ".join(parts)
    if len(summary) > 320:
        summary = summary[:317] + "..."
    return summary


def _format_llm_tools_block() -> str:
    definitions = ToolManager().get_definitions()
    if not definitions:
        return ""
    lines: list[str] = [
        _T("tools_header"),
        _T("tools_intro"),
        "",
    ]
    for entry in definitions:
        if not isinstance(entry, dict) or entry.get("type") != "function":
            continue
        fn = entry.get("function")
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        desc = str(fn.get("description") or "").strip()
        if not desc:
            desc = _T("tools_no_desc")
        param_summ = _summarize_tool_parameters(fn.get("parameters"))
        item = _T("tools_item", name=name, description=desc)
        if param_summ:
            item += _T("tools_param_summary", summary=param_summ)
        lines.append(item)
    lines.append("")
    return "\n".join(lines)


def _target_voice_key(code: str | None) -> str:
    """将 api.yaml 中的 voice_language 归一成 template_gen.voice_target_* 文案键。"""
    c = (str(code).strip() if code is not None else "") or "ja"
    low = c.lower()
    if low in ("yue", "yue_hk", "cantonese", "cht", "zh_hk"):
        return "yue"
    n = normalize_lang(c)
    if n == "en":
        return "en"
    if n == "zh_CN":
        return "zh"
    return "ja"


def _target_voice_display_name() -> str:
    try:
        raw = config_manager.config.system_config.voice_language
    except Exception:
        raw = "ja"
    return _T(f"voice_target_{_target_voice_key(raw)}")


def _narr_label() -> str:
    """中文模板文案中展示「旁白」，其它语言仍用 NARR 代号。"""
    return _T("narr_token")


class TemplateGenerator:
    def generate_chat_template(
        self,
        selected_characters,
        bg_name,
        use_effect,
        use_cg,
        use_llm_translation,
        use_cot=False,
        use_choice=True,
        use_narration=True,
        max_speech_chars: int = 0,
        max_dialog_items: int = 0,
    ):
        if not selected_characters:
            return _T("err_no_characters"), ""

        # 人物排序保证生成内容稳定；聊天记录默认文件名由设置页「用户情景」哈希决定。
        selected_characters = sorted(selected_characters)

        sep = _T("name_sep")
        names = sep.join(selected_characters) + sep

        effect_line = _T("json_line_effect") if use_effect else ""
        vlang = _target_voice_display_name()
        trans_line = (
            _T("json_line_trans", target_voice_name=vlang) if use_llm_translation else ""
        )
        template = _T("preamble", names=names) + _T("json_head_top")
        template += _T("json_speech_line", example=_T("json_speech_example"))
        if use_effect:
            template += effect_line
        if use_llm_translation:
            template += trans_line
        template += _T("json_foot")

        template += _T("sprites_header")
        for char_name in selected_characters:
            char_detail = config_manager.get_character_by_name(char_name)
            template += _T("sprites_count", name=char_name, n=len(char_detail.sprites))
            template += f"{char_detail.emotion_tags}\n\n"

        template += _T("profile_header")
        for char_name in selected_characters:
            char_detail = config_manager.get_character_by_name(char_name)
            if char_detail.character_setting:
                template += _T("profile_for", name=char_name)
                character_setting = char_detail.character_setting
                template += f"{character_setting}\n\n"

        if bg_name and not is_transparent_background(bg_name):
            bg = config_manager.get_background_by_name(bg_name)
            if bg and bg.sprites:
                template += _T("scene_block_header")
                template += _T("scene_count", n=len(bg.sprites))
                template += f"{bg.bg_tags}\n\n"

            if bg and bg.bgm_list:
                template += _T("bgm_block_header")
                template += _T("bgm_count", n=len(bg.bgm_list))
                template += f"{bg.bgm_tags}\n\n"

        # 保留字新代号（与 core.messaging.dialog_tokens 及 handlers 一致；旧版中文仍兼容）
        opt_scene = (f", {SCENE}" if bg_name else "")
        opt_bgm = (f", {BGM}" if bg_name else "")
        opt_cg = (f", {CG}" if use_cg else "")
        cot_part = (f"{COT}," if use_cot else "")

        need_real = bool(bg_name) and not is_transparent_background(bg_name)

        _toks = {
            "narr": _narr_label(),
            "choice": CHOICE,
            "stat": STAT,
            "scn": SCENE,
            "bgm_t": BGM,
            "cg": CG,
            "cot": COT,
        }

        fixed_roles_join = "、".join(
            [x for x in (
                _toks["narr"] if use_narration else None,
                _toks["choice"] if use_choice else None,
                _toks["stat"],
            ) if x is not None]
        )
        role_clause = (" " + fixed_roles_join) if fixed_roles_join else ""

        REQUIREMENTS: list[str] = [
            _T("r_format"),
            _T(
                "r_cname",
                names=names,
                cot_part=cot_part,
                fixed_roles=role_clause,
                opt_scene=opt_scene,
                opt_bgm=opt_bgm,
                opt_cg=opt_cg,
            ),
            _T("r_sprite"),
            _T(
                "r_non_sprite",
                fixed_roles_non_sprite=fixed_roles_join,
            ),
        ]
        if need_real:
            REQUIREMENTS += [_T("r_scene", **_toks), _T("r_bgm", **_toks)]

        REQUIREMENTS += [
            _T("r_speech", speech_lang_name=_T("speech_lang_name")),
            _T("r_array"),
        ]
        if max_speech_chars > 0:
            REQUIREMENTS.append(_T("r_speech_max_chars", n=max_speech_chars))
        if max_dialog_items > 0:
            REQUIREMENTS.append(_T("r_dialog_max_items", n=max_dialog_items))
        if use_narration:
            REQUIREMENTS.append(_T("r_narration", **_toks))
        if use_choice:
            REQUIREMENTS += [
                _T("r_choice_pos", **_toks),
                _T("r_choice_format", **_toks),
                _T("r_choice_balance", **_toks),
            ]
        REQUIREMENTS.append(_T("r_stats", **_toks))
        if use_cg:
            REQUIREMENTS.append(_T("r_cg", **_toks))
        if use_llm_translation:
            REQUIREMENTS.append(_T("r_translate", target_voice_name=vlang))
        if use_effect:
            REQUIREMENTS.append(_T("r_effect"))
        if use_cot:
            REQUIREMENTS.insert(0, _T("r_cot", **_toks))

        tools_block = _format_llm_tools_block()
        if tools_block:
            template += tools_block

        template += _T("requirements_header")
        for item in REQUIREMENTS:
            template += f"- {item}\n"
        extra = _T("closing_extra_bgm") if (bg_name and not is_transparent_background(bg_name)) else ""
        template += _T("closing", extra=extra)
        return template, ""
