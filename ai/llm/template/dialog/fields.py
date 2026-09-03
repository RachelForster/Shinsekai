"""Base output fields and the patch-compatible field contract section."""

from sdk.types import OutputFieldSpec

from ..core import Section
from .context import DialogTemplateContext
from .patches import apply_field_patches


def build_fields(context: DialogTemplateContext) -> dict[str, OutputFieldSpec]:
    _T = context.translate
    names = context.names
    vlang = context.target_voice_name
    use_effect = context.use_effect
    use_llm_translation = context.use_llm_translation
    fields: dict[str, OutputFieldSpec] = {
        "character_name": OutputFieldSpec(
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
        "sprite": OutputFieldSpec(
            key="sprite",
            type="string",
            description=_T("r_sprite"),
            required=True,
        ),
        "speech": OutputFieldSpec(
            key="speech",
            type="string",
            description=_T("r_speech", speech_lang_name=_T("speech_lang_name")),
            required=True,
        ),
    }
    if use_effect:
        fields["effect"] = OutputFieldSpec(
            key="effect",
            type="string",
            description=_T("r_effect"),
            required=False,
        )
    if use_llm_translation:
        fields["translate"] = OutputFieldSpec(
            key="translate",
            type="string",
            description=_T("r_translate", target_voice_name=vlang),
            required=False,
        )
    return apply_field_patches(fields, context.output_contract_patches)


def _render_field_notes(fields: dict[str, OutputFieldSpec]) -> str:
    if not fields:
        return ""
    lines = ["\nOutput field contract:\n"]
    for field in fields.values():
        required = "required" if field.required else "optional"
        aliases = ""
        if field.aliases:
            aliases = f" Aliases: {', '.join(field.aliases)}."
        lines.append(
            f"- {field.key} ({field.type}, {required}): {field.description}{aliases}\n"
        )
    return "".join(lines)


class FieldContractSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        return _render_field_notes(build_fields(context))
