"""Dialog requirements, identified by the existing SDK patch IDs."""

from core.messaging.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT
from sdk.types import RequirementSpec

from ..core import Section, TextSection
from .context import DialogTemplateContext
from .patches import apply_requirement_patches


def build_requirements(context: DialogTemplateContext) -> list[RequirementSpec]:
    _T = context.translate
    names = context.names
    vlang = context.target_voice_name
    has_real_background = context.has_real_background
    use_effect = context.use_effect
    use_cg = context.use_cg
    use_llm_translation = context.use_llm_translation
    use_cot = context.use_cot
    use_choice = context.use_choice
    use_narration = context.use_narration
    use_stat = context.use_stat
    max_speech_chars = context.max_speech_chars
    max_dialog_items = context.max_dialog_items
    # 保留字新代号（与 core.messaging.dialog_tokens 及 handlers 一致；旧版中文仍兼容）
    opt_scene = f", {SCENE}" if has_real_background else ""
    opt_bgm = f", {BGM}" if has_real_background else ""
    opt_cg = f", {CG}" if use_cg else ""
    cot_part = f"{COT}," if use_cot else ""

    need_real = has_real_background

    _toks = {
        "narr": _T("narr_token"),
        "choice": CHOICE,
        "stat": STAT,
        "scn": SCENE,
        "bgm_t": BGM,
        "cg": CG,
        "cot": COT,
    }

    fixed_roles_join = "、".join(
        [
            x
            for x in (
                _toks["narr"] if use_narration else None,
                _toks["choice"] if use_choice else None,
                _toks["stat"] if use_stat else None,
            )
            if x is not None
        ]
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
        requirements.append(
            RequirementSpec("r_narration", _T("r_narration", **_toks), 100)
        )
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
            RequirementSpec(
                "r_translate", _T("r_translate", target_voice_name=vlang), 160
            )
        )
    if use_effect:
        requirements.append(RequirementSpec("r_effect", _T("r_effect"), 170))
    if use_cot:
        requirements.insert(0, RequirementSpec("r_cot", _T("r_cot", **_toks), 5))
    return apply_requirement_patches(requirements, context.output_contract_patches)


class RequirementsSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        tree = TextSection(
            self.id,
            text=context.translate("requirements_header"),
            children=tuple(
                TextSection(item.id, priority=item.order, text=f"- {item.text}\n")
                for item in build_requirements(context)
            ),
        )
        return tree.render(context)
