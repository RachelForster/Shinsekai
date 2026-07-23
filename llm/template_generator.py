import json
import logging
from dataclasses import dataclass
from typing import Any

from i18n import tr as tr_i18n
from sdk.lang import normalize_lang
from config.config_manager import ConfigManager, character_name_key
from core.messaging.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT
from llm.tools.tool_manager import ToolManager
from sdk.tool_registry import apply_registered_tools
from sdk.types import (
    FieldPatch,
    OutputContractPatch,
    OutputFieldSpec,
    RequirementPatch,
    RequirementSpec,
)

# Ensure @tool-decorated functions are registered before template generation
import llm.tools.character_tools  # noqa: F401
import llm.tools.memory_tools    # noqa: F401
import llm.tools.tool_search      # noqa: F401
import llm.tools.file_tools       # noqa: F401
import llm.tools.chat_ui_tools    # noqa: F401

config_manager = ConfigManager()
DEFAULT_DIALOG_CONTRACT_ID = "default.dialog.v1"
logger = logging.getLogger(__name__)

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


def no_valid_characters_message() -> str:
    return _T("err_no_characters")


class NoValidCharactersError(ValueError):
    """Raised when template generation has no resolvable character."""

    error_code = "no_valid_characters"

    def __init__(self) -> None:
        super().__init__(no_valid_characters_message())


def resolve_chat_template_characters(
    selected_characters: Any,
    manager: Any = None,
) -> list[tuple[str, Any]]:
    """Resolve, canonicalize, and deterministically order a character selection."""
    if manager is None:
        manager = config_manager
    requested_names: list[str] = []
    requested_name_keys: set[str] = set()
    for item in selected_characters or []:
        requested_name = str(item).strip()
        if not requested_name:
            continue
        requested_key = character_name_key(requested_name)
        if requested_key in requested_name_keys:
            continue
        requested_name_keys.add(requested_key)
        requested_names.append(requested_name)
    requested_names.sort(key=lambda name: (character_name_key(name), name))

    resolved_characters: list[tuple[str, Any]] = []
    missing_characters: list[str] = []
    resolved_name_keys: set[str] = set()
    for requested_name in requested_names:
        character = manager.get_character_by_name(requested_name)
        if character is None:
            missing_characters.append(requested_name)
            continue
        canonical_name = str(getattr(character, "name", "") or requested_name).strip()
        canonical_key = character_name_key(canonical_name)
        if canonical_key in resolved_name_keys:
            continue
        resolved_name_keys.add(canonical_key)
        resolved_characters.append((canonical_name, character))

    if missing_characters:
        logger.warning(
            "Skipping missing characters during template generation: %s",
            ", ".join(missing_characters),
            extra={
                "event": "template.characters.missing",
                "missing_characters": missing_characters,
            },
        )
    return resolved_characters


def json_format_reminder() -> str:
    """Return the localized reminder that must close every runtime system prompt."""
    return _T("closing_json_reminder").strip()


def _json_string_content(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


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
    """Only include default-group tools in the system prompt.
    Use search_tools to discover tools from other groups on demand."""
    apply_registered_tools(ToolManager())
    definitions = ToolManager().get_definitions(groups="default")
    if not definitions:
        return ""
    tm = ToolManager()
    other_groups = [g for g in tm.get_groups() if g != "default"]
    other_hint = ""
    if other_groups:
        other_hint = _T("tools_other_groups", groups=", ".join(other_groups))
    lines: list[str] = [
        _T("tools_header"),
        _T("tools_intro"),
        other_hint,
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


@dataclass(frozen=True)
class _FieldSpec:
    key: str
    type: str
    description: str
    required: bool = False
    aliases: tuple[str, ...] = ()


def _apply_field_patch(field: _FieldSpec, patch: FieldPatch) -> _FieldSpec:
    desc = field.description
    if patch.description:
        desc = patch.description
    if patch.enum:
        enum_text = ", ".join(str(x) for x in patch.enum)
        desc = f"{desc} Allowed values: {enum_text}."
    return _FieldSpec(
        key=field.key,
        type=patch.type or field.type,
        description=desc,
        required=field.required if patch.required is None else bool(patch.required),
        aliases=field.aliases,
    )


def _apply_requirement_patch(
    requirement: RequirementSpec,
    patch: RequirementPatch,
) -> RequirementSpec:
    if patch.mode == "remove":
        return RequirementSpec(
            id=requirement.id,
            text=requirement.text,
            order=requirement.order,
            enabled=False,
        )
    if patch.mode == "replace":
        return RequirementSpec(
            id=requirement.id,
            text=patch.text,
            order=requirement.order,
            enabled=requirement.enabled,
        )
    if patch.mode == "prepend":
        return RequirementSpec(
            id=requirement.id,
            text=f"{patch.text} {requirement.text}".strip(),
            order=requirement.order,
            enabled=requirement.enabled,
        )
    if patch.mode == "append":
        return RequirementSpec(
            id=requirement.id,
            text=f"{requirement.text} {patch.text}".strip(),
            order=requirement.order,
            enabled=requirement.enabled,
        )
    logger.warning(
        "Unknown RequirementPatch.mode %r for requirement %s; leaving requirement unchanged",
        patch.mode,
        requirement.id,
    )
    return requirement


def _render_field_notes(fields: dict[str, _FieldSpec]) -> str:
    if not fields:
        return ""
    lines = ["\nOutput field contract:\n"]
    for field in fields.values():
        required = "required" if field.required else "optional"
        aliases = ""
        if field.aliases:
            aliases = f" Aliases: {', '.join(field.aliases)}."
        lines.append(f"- {field.key} ({field.type}, {required}): {field.description}{aliases}\n")
    return "".join(lines)



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


def _ui_voice_same_lang() -> bool:
    """UI 语言和语音目标语言相同时返回 True（无需翻译）。"""
    try:
        ui = str(config_manager.config.system_config.ui_language or "")
        voice = str(config_manager.config.system_config.voice_language or "ja")
    except Exception:
        return False
    # 比较语种前缀：zh_CN vs zh → 都是中文
    ui_main = ui.split("_")[0].lower()
    voice_main = _target_voice_key(voice)
    return ui_main == voice_main


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
    def __init__(
        self,
        output_contract_patches: list[OutputContractPatch] | None = None,
    ) -> None:
        self._output_contract_patches = output_contract_patches

    def _get_output_contract_patches(self) -> list[OutputContractPatch]:
        if self._output_contract_patches is not None:
            return list(self._output_contract_patches)
        try:
            from core.plugins.plugin_host import get_plugin_output_contract_patches

            return get_plugin_output_contract_patches(DEFAULT_DIALOG_CONTRACT_ID)
        except Exception:
            return []

    def resolve_chat_template_characters(
        self,
        selected_characters: Any,
    ) -> list[tuple[str, Any]]:
        return resolve_chat_template_characters(selected_characters)

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
        use_stat=True,
        max_speech_chars: int = 0,
        max_dialog_items: int = 0,
    ):
        if not selected_characters:
            raise NoValidCharactersError()

        # Resolve the persisted/UI selection once. A restored template session can
        # contain characters that were deleted or renamed after the session was
        # saved; those stale entries must not make template generation crash.
        resolved_characters = self.resolve_chat_template_characters(selected_characters)
        if not resolved_characters:
            raise NoValidCharactersError()

        # 人物排序保证生成内容稳定；聊天记录默认文件名由设置页「用户情景」哈希决定。
        selected_characters = [name for name, _character in resolved_characters]

        sep = _T("name_sep")
        names = sep.join(selected_characters)

        effect_line = _T("json_line_effect") if use_effect else ""
        vlang = _target_voice_display_name()
        if use_llm_translation and _ui_voice_same_lang():
            use_llm_translation = False
        trans_line = (
            _T("json_line_trans", target_voice_name=_json_string_content(vlang))
            if use_llm_translation
            else ""
        )
        fields: dict[str, _FieldSpec] = {
            "character_name": _FieldSpec(
                key="character_name",
                type="string",
                description=_T(
                    "r_cname",
                    names=names,
                    cot_part="",
                    fixed_roles="",
                    opt_scene="",
                    opt_bgm="",
                    opt_cg="",
                ),
                required=True,
            ),
            "sprite": _FieldSpec(
                key="sprite",
                type="string",
                description=_T("r_sprite"),
                required=True,
            ),
            "speech": _FieldSpec(
                key="speech",
                type="string",
                description=_T("r_speech", speech_lang_name=_T("speech_lang_name")),
                required=True,
            ),
        }
        if use_effect:
            fields["effect"] = _FieldSpec(
                key="effect",
                type="string",
                description=_T("r_effect"),
                required=False,
            )
        if use_llm_translation:
            fields["translate"] = _FieldSpec(
                key="translate",
                type="string",
                description=_T("r_translate", target_voice_name=vlang),
                required=False,
            )

        contract_patches = self._get_output_contract_patches()
        for patch in sorted(contract_patches, key=lambda p: p.priority):
            for key in patch.remove_fields:
                if key not in {"character_name", "speech", "sprite"}:
                    fields.pop(key, None)
            for key, field_patch in patch.field_patches.items():
                existing = fields.get(key)
                if existing is not None:
                    fields[key] = _apply_field_patch(existing, field_patch)
            for field in patch.add_fields:
                fields[field.key] = _FieldSpec(
                    key=field.key,
                    type=field.type,
                    description=field.description,
                    required=field.required,
                    aliases=field.aliases,
                )

        template = _T("preamble", names=names) + _T("json_head_top")
        template += _T(
            "json_speech_line",
            example=_json_string_content(_T("json_speech_example")),
        )
        if use_effect:
            template += effect_line
        if use_llm_translation:
            template += trans_line
        template += _T("json_foot")
        template += _render_field_notes(fields)

        template += _T("sprites_header")
        for char_name, char_detail in resolved_characters:
            sprites = getattr(char_detail, "sprites", None) or []
            template += _T("sprites_count", name=char_name, n=len(sprites))
            template += f"{getattr(char_detail, 'emotion_tags', '') or ''}\n\n"

        template += _T("profile_header")
        for char_name, char_detail in resolved_characters:
            character_setting = str(getattr(char_detail, "character_setting", "") or "")
            if character_setting:
                template += _T("profile_for", name=char_name)
                template += f"{character_setting}\n\n"

        has_real_background = bool(bg_name) and not is_transparent_background(bg_name)

        if has_real_background:
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
        opt_scene = (f", {SCENE}" if has_real_background else "")
        opt_bgm = (f", {BGM}" if has_real_background else "")
        opt_cg = (f", {CG}" if use_cg else "")
        cot_part = (f"{COT}," if use_cot else "")

        need_real = has_real_background

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
                _toks["stat"] if use_stat else None,
            ) if x is not None]
        )
        role_clause = (" " + fixed_roles_join) if fixed_roles_join else ""

        requirements: list[RequirementSpec] = [
            RequirementSpec("r_format", _T("r_format"), 10),
            RequirementSpec("r_user_display_name_tool", _T("r_user_display_name_tool"), 15),
            RequirementSpec(
                "r_cname",
                _T(
                "r_cname",
                names=names,
                cot_part=cot_part,
                fixed_roles=role_clause,
                opt_scene=opt_scene,
                opt_bgm=opt_bgm,
                opt_cg=opt_cg,
                ),
                20,
            ),
            RequirementSpec("r_sprite", _T("r_sprite"), 30),
            RequirementSpec(
                "r_non_sprite",
                _T(
                "r_non_sprite",
                fixed_roles_non_sprite=fixed_roles_join,
                ),
                40,
            ),
        ]
        if need_real:
            requirements += [
                RequirementSpec("r_scene", _T("r_scene", **_toks), 50),
                RequirementSpec("r_bgm", _T("r_bgm", **_toks), 60),
            ]

        requirements += [
            RequirementSpec(
                "r_speech",
                _T("r_speech", speech_lang_name=_T("speech_lang_name")),
                70,
            ),
            RequirementSpec("r_array", _T("r_array"), 80),
        ]
        if max_speech_chars > 0:
            requirements.append(
                RequirementSpec(
                    "r_speech_max_chars",
                    _T("r_speech_max_chars", n=max_speech_chars),
                    90,
                )
            )
        if max_dialog_items > 0:
            requirements.append(
                RequirementSpec(
                    "r_dialog_max_items",
                    _T("r_dialog_max_items", n=max_dialog_items),
                    95,
                )
            )
        if use_narration:
            requirements.append(RequirementSpec("r_narration", _T("r_narration", **_toks), 100))
        if use_choice:
            requirements += [
                RequirementSpec("r_choice_pos", _T("r_choice_pos", **_toks), 110),
                RequirementSpec("r_choice_format", _T("r_choice_format", **_toks), 120),
                RequirementSpec("r_choice_balance", _T("r_choice_balance", **_toks), 130),
            ]
        if use_stat:
            requirements.append(RequirementSpec("r_stats", _T("r_stats", **_toks), 140))
        if use_cg:
            requirements.append(RequirementSpec("r_cg", _T("r_cg", **_toks), 150))
        if use_llm_translation:
            requirements.append(
                RequirementSpec("r_translate", _T("r_translate", target_voice_name=vlang), 160)
            )
        if use_effect:
            requirements.append(RequirementSpec("r_effect", _T("r_effect"), 170))
        if use_cot:
            requirements.insert(0, RequirementSpec("r_cot", _T("r_cot", **_toks), 5))

        requirement_by_id = {item.id: item for item in requirements}
        for patch in sorted(contract_patches, key=lambda p: p.priority):
            for req_id, req_patch in patch.requirement_patches.items():
                if req_id in requirement_by_id:
                    requirement_by_id[req_id] = _apply_requirement_patch(
                        requirement_by_id[req_id], req_patch
                    )
            for req in patch.add_requirements:
                requirement_by_id[req.id] = req
        requirements = sorted(
            (item for item in requirement_by_id.values() if item.enabled),
            key=lambda item: item.order,
        )

        tools_block = _format_llm_tools_block()
        if tools_block:
            template += tools_block

        template += _T("requirements_header")
        for item in requirements:
            template += f"- {item.text}\n"
        extra = _T("closing_extra_bgm") if (bg_name and not is_transparent_background(bg_name)) else ""
        template += _T("closing", extra=extra)
        template += f"{json_format_reminder()}\n"
        return template, ""
