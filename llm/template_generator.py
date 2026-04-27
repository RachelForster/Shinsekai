from i18n import normalize_lang, tr as tr_i18n
from config.character_manager import ConfigManager
from core.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT

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
    ):
        if not selected_characters:
            return _T("err_no_characters"), ""

        # 让同样的人物生成同样的模板，就会有一样的 md5 了，进而会有同样的聊天历史文件。
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

        # 保留字新代号（与 core.dialog_tokens 及 handlers 一致；旧版中文仍兼容）
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
        REQUIREMENTS: list[str] = [
            _T("r_format"),
            _T(
                "r_cname",
                names=names,
                cot_part=cot_part,
                opt_scene=opt_scene,
                opt_bgm=opt_bgm,
                opt_cg=opt_cg,
                **_toks,
            ),
            _T("r_sprite"),
            _T("r_non_sprite", **_toks),
        ]
        if need_real:
            REQUIREMENTS += [_T("r_scene", **_toks), _T("r_bgm", **_toks)]

        REQUIREMENTS += [
            _T("r_speech", speech_lang_name=_T("speech_lang_name")),
            _T("r_array"),
            _T("r_narration", **_toks),
            _T("r_choice_pos", **_toks),
            _T("r_choice_format", **_toks),
            _T("r_choice_balance", **_toks),
            _T("r_stats", **_toks),
        ]
        if use_cg:
            REQUIREMENTS.append(_T("r_cg", **_toks))
        if use_llm_translation:
            REQUIREMENTS.append(_T("r_translate", target_voice_name=vlang))
        if use_effect:
            REQUIREMENTS.append(_T("r_effect"))
        if use_cot:
            REQUIREMENTS.insert(0, _T("r_cot", **_toks))

        template += _T("requirements_header")
        for item in REQUIREMENTS:
            template += f"- {item}\n"
        extra = _T("closing_extra_bgm") if (bg_name and not is_transparent_background(bg_name)) else ""
        template += _T("closing", extra=extra)
        return template, ""
