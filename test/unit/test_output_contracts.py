from __future__ import annotations

from types import SimpleNamespace

from llm.template_generator import DEFAULT_DIALOG_CONTRACT_ID, TemplateGenerator
from sdk.register import PluginCapabilityRegistry
from sdk.types import (
    ChatOutputContract,
    FieldPatch,
    OutputContractPatch,
    OutputFieldSpec,
    RequirementPatch,
    RequirementSpec,
    WorkflowContribution,
)
from core.messaging.stream_parser import LlmResponseStreamParser


def test_register_dag_yaml_is_workflow_contribution() -> None:
    registry = PluginCapabilityRegistry()

    registry.register_dag_yaml("plugins/demo/workflow.yaml")

    workflows = registry.workflow_contributions
    assert len(workflows) == 1
    assert workflows[0].yaml_path == "plugins/demo/workflow.yaml"
    assert workflows[0].name == "workflow"
    assert registry.dag_yaml_paths == ["plugins/demo/workflow.yaml"]


def test_register_workflow_with_output_contract() -> None:
    registry = PluginCapabilityRegistry()
    contribution = WorkflowContribution(
        id="demo.workflow",
        name="Demo Workflow",
        yaml_path="plugins/demo/workflow.yaml",
        output_contract=ChatOutputContract(
            id="demo.output.v1",
            json_schema={"type": "object"},
            target_export="llm.output",
        ),
    )

    registry.register_workflow(contribution)

    assert registry.workflow_contributions == [contribution]
    assert registry.dag_yaml_paths == ["plugins/demo/workflow.yaml"]


def test_template_generator_applies_speech_contract_patch(monkeypatch) -> None:
    character = SimpleNamespace(
        sprites=[object()],
        emotion_tags="happy: 01",
        character_setting="A test character.",
    )

    monkeypatch.setattr(
        "llm.template_generator.config_manager",
        SimpleNamespace(get_character_by_name=lambda name: character),
    )

    patch = OutputContractPatch(
        id="demo.emotion-tags",
        target_contract=DEFAULT_DIALOG_CONTRACT_ID,
        field_patches={
            "speech": FieldPatch(
                description="Speech may include parenthesized vocal tags.",
            )
        },
        requirement_patches={
            "r_speech": RequirementPatch(
                mode="append",
                text="Allow concise parenthesized tags such as (cough), (laugh), or (sigh).",
            )
        },
        add_requirements=(
            RequirementSpec(
                id="demo_emotion_tag_balance",
                text="Do not overuse parenthesized vocal tags.",
                order=71,
            ),
        ),
    )

    template, warning = TemplateGenerator(output_contract_patches=[patch]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name=None,
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
    )

    assert warning == ""
    assert "Speech may include parenthesized vocal tags." in template
    assert "Allow concise parenthesized tags such as (cough), (laugh), or (sigh)." in template
    assert "Do not overuse parenthesized vocal tags." in template


def test_template_generator_renders_added_field_aliases(monkeypatch) -> None:
    character = SimpleNamespace(
        sprites=[object()],
        emotion_tags="happy: 01",
        character_setting="A test character.",
    )

    monkeypatch.setattr(
        "llm.template_generator.config_manager",
        SimpleNamespace(get_character_by_name=lambda name: character),
    )

    patch = OutputContractPatch(
        id="demo.camera",
        target_contract=DEFAULT_DIALOG_CONTRACT_ID,
        add_fields=(
            OutputFieldSpec(
                key="camera",
                type="string",
                description="Camera framing for this line.",
                aliases=("shot", "framing"),
            ),
        ),
    )

    template, warning = TemplateGenerator(output_contract_patches=[patch]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name=None,
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
    )

    assert warning == ""
    assert "camera (string, optional): Camera framing for this line. Aliases: shot, framing." in template


def test_template_generator_omits_scene_and_bgm_for_transparent_background(monkeypatch) -> None:
    character = SimpleNamespace(
        sprites=[object()],
        emotion_tags="happy: 01",
        character_setting="A test character.",
    )
    background = SimpleNamespace(
        sprites=[{"path": "room.png"}],
        bg_tags="scene 1: room",
        bgm_list=["room.mp3"],
        bgm_tags="music 1: room theme",
    )

    monkeypatch.setattr(
        "llm.template_generator.config_manager",
        SimpleNamespace(
            get_background_by_name=lambda name: background,
            get_character_by_name=lambda name: character,
        ),
    )

    transparent_template, transparent_warning = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="透明场景",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
    )
    real_background_template, real_background_warning = TemplateGenerator(
        output_contract_patches=[]
    ).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
    )

    assert transparent_warning == ""
    assert real_background_warning == ""
    assert "template_gen.r_scene" not in transparent_template
    assert "template_gen.r_bgm" not in transparent_template
    assert "template_gen.scene_block_header" not in transparent_template
    assert "template_gen.bgm_block_header" not in transparent_template
    assert "template_gen.r_scene" in real_background_template
    assert "template_gen.r_bgm" in real_background_template
    assert "template_gen.scene_block_header" in real_background_template
    assert "template_gen.bgm_block_header" in real_background_template


def test_template_generator_warns_for_unknown_requirement_patch_mode(monkeypatch, caplog) -> None:
    character = SimpleNamespace(
        sprites=[object()],
        emotion_tags="happy: 01",
        character_setting="A test character.",
    )

    monkeypatch.setattr(
        "llm.template_generator.config_manager",
        SimpleNamespace(get_character_by_name=lambda name: character),
    )

    patch = OutputContractPatch(
        id="demo.bad-mode",
        target_contract=DEFAULT_DIALOG_CONTRACT_ID,
        requirement_patches={
            "r_speech": RequirementPatch(mode="unknown", text="Ignored at runtime."),
        },
    )

    TemplateGenerator(output_contract_patches=[patch]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name=None,
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
    )

    assert "Unknown RequirementPatch.mode" in caplog.text


def test_llm_dialog_message_preserves_contract_extra_fields() -> None:
    msg = next(
        LlmResponseStreamParser().feed(
            '{"character_name": "Alice", "speech": "Hi", "sprite": "01", "camera": "close_up"}'
        )
    )

    assert msg.name == "Alice"
    assert msg.model_extra == {"camera": "close_up"}
