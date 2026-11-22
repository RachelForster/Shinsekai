"""Stage P3 tests for perception, vision, and asset generation PromptSpecs and L3 contracts."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from ai.llm.template.generation import (
    BACKGROUND_ANNOTATION_SPEC,
    CHARACTER_ANNOTATION_SPEC,
    MOUTH_BLINK_PROMPT_SPEC,
    MOUTH_SPEECH_PROMPT_SPEC,
    SPRITE_IDLE_ANIMATION_SPEC,
    SPRITE_TAG_INSTRUCTIONS_SPEC,
    SPRITE_TRANSITION_PROMPT_SPEC,
    render_annotation_retry_prompt,
    render_background_annotation_prompt,
    render_background_field_translation_prompts,
    render_character_annotation_prompt,
    render_character_brief_batch_prompts,
    render_character_brief_prompts,
    render_character_field_translation_prompts,
    render_character_setting_prompts,
    render_mouth_speech_prompt,
    render_sprite_idle_animation_prompt,
    render_sprite_plan_prompts,
    render_sprite_tag_instructions,
    render_sprite_transition_prompt,
    render_transition_recommendation_prompts,
    render_vision_describe_prompt,
    resolve_sprite_suffixes,
)
from ai.llm.template.perception import (
    CLOUD_SUMMARY_SPEC,
    PERCEPTION_DECISION_SPEC,
    RP_PERCEPTION_CONTEXT_SPEC,
    PerceptionDecisionPromptContext,
    RpPerceptionContext,
    VOICE_STYLE_SPEC,
    build_perception_translator,
    render_cloud_summary_messages,
    render_perception_decision_prompts,
    render_perception_turn_reply_suffix,
    render_proactive_collapsed_history,
    render_proactive_turn_instruction,
    render_voice_style_messages,
)
from ai.perception.cloud_summary import compose_minute_summary, parse_cloud_summary_response
from application.perception.hooks import PerceptionAutoHooks
from core.chat_history.identity import CHAT_TURN_ID
from core.perception.cache import PERCEPTION_CONTEXT_MARKER, RPInputCache
from core.perception.gatekeeper import PerceptionGatekeeper
from core.perception.models import PerceptionDigestResult
from sdk.lang import SUPPORTED_LANGS


def test_l3_locked_contracts_resist_ui_locale_switches() -> None:
    zh_tag_rules = render_sprite_tag_instructions(locale="zh_CN")
    zh_char_annot = render_character_annotation_prompt(locale="zh_CN")
    for locale in SUPPORTED_LANGS:
        assert SPRITE_TAG_INSTRUCTIONS_SPEC.resolve_locale(locale) == "zh_CN"
        assert CHARACTER_ANNOTATION_SPEC.resolve_locale(locale) == "zh_CN"
        assert PERCEPTION_DECISION_SPEC.resolve_locale(locale) == "zh_CN"
        assert VOICE_STYLE_SPEC.resolve_locale(locale) == "zh_CN"
        assert SPRITE_IDLE_ANIMATION_SPEC.resolve_locale(locale) == "en"
        assert MOUTH_SPEECH_PROMPT_SPEC.resolve_locale(locale) == "en"
        assert MOUTH_BLINK_PROMPT_SPEC.resolve_locale(locale) == "en"
        assert SPRITE_TRANSITION_PROMPT_SPEC.resolve_locale(locale) == "en"

        assert render_sprite_tag_instructions(locale=locale) == zh_tag_rules
        assert render_character_annotation_prompt(locale=locale) == zh_char_annot
        assert "2–3 个简短中文词语" in render_character_annotation_prompt(locale=locale)

        voice_msgs = render_voice_style_messages("拉法尔", "追寻真理", locale=locale)
        assert "角色语气提炼助手" in voice_msgs[0]["content"]

    assert "locked-off static camera" in render_sprite_idle_animation_prompt()
    assert "plain white background" in render_mouth_speech_prompt(include_blink=False)
    assert "natural blink" in render_mouth_speech_prompt(include_blink=True)
    assert "transition directly from the standing pose" in render_sprite_transition_prompt()


def test_perception_decision_sections_render_all_three_locales_when_unlocked() -> None:
    for locale, expected_marker in (
        ("zh_CN", "结合当前画面和可读的字幕"),
        ("en", "Combine the current frame and readable subtitles"),
        ("ja", "現在の映像と読み取れる字幕を踏まえ"),
    ):
        ctx = PerceptionDecisionPromptContext(
            locale=locale,
            shared_screen=True,
            watching_screen=True,
            has_frame=True,
            compared_frames=True,
            scene_anchor="海面上有灯塔",
            screen_text='"{untrusted_ocr}"',
            screen_text_changed=True,
            recent_barks=("刚才那句很有意思。",),
            sprite_choices={1: "微笑", 2: "惊讶"},
        )
        locked_sys, _ = render_perception_decision_prompts(ctx, respect_locked_contract=True)
        assert "和用户一起看共享屏幕" in locked_sys

        unlocked_sys, unlocked_user = render_perception_decision_prompts(
            ctx,
            respect_locked_contract=False,
        )
        assert '"reflex":{"sprite_id":null,"bark":null}' in unlocked_sys
        assert expected_marker in unlocked_user
        assert "{untrusted_ocr}" in unlocked_user


def test_rp_perception_cache_and_hooks_localize_via_translator_injection() -> None:
    now = time.time()
    cache = RPInputCache()
    cache.record_decision(
        PerceptionDigestResult(
            digest="Knight rests beside a bonfire",
            salience=0.90,
            scene="story_media",
            mood="serious",
            game="dark_demo",
            created_at=now - 5.0,
        )
    )
    cache.record_screen_text("The flame is fading.", captured_at=now - 3.0)
    cache.record_highlighted_text("Key lore inscription", captured_at=now - 2.0)

    en_ctx = cache.format_for_rp_context(
        consume=False,
        include_recent_events=True,
        translate=build_perception_translator("en"),
    )
    assert PERCEPTION_CONTEXT_MARKER in en_ctx
    assert "(Active game/source: dark_demo)" in en_ctx
    assert "[Subtitle] The flame is fading." in en_ctx
    assert "[Highlight] Key lore inscription" in en_ctx

    ja_ctx = cache.format_for_rp_context(
        consume=False,
        include_recent_events=True,
        translate=build_perception_translator("ja"),
    )
    assert "（現在のゲーム／ソース：dark_demo）" in ja_ctx
    assert "[ハイライト] Key lore inscription" in ja_ctx

    hooks = PerceptionAutoHooks(
        rp_input_cache=cache,
        gatekeeper=PerceptionGatekeeper(),
        locale="en",
    )
    assert hooks.prepare_turn("proactive-en", "perception") is True
    old_msg = {"role": "user", "source": "perception", "content": "old"}
    cur_msg = {
        "role": "user",
        "source": "perception",
        CHAT_TURN_ID: "proactive-en",
        "content": render_proactive_turn_instruction(locale="en"),
    }
    hooks.before_chat(SimpleNamespace(messages=[old_msg, cur_msg]))  # type: ignore[arg-type]
    assert old_msg["content"] == render_proactive_collapsed_history(locale="en")
    assert cur_msg["content"].endswith(
        "\n\n" + render_perception_turn_reply_suffix(locale="en")
    )
    assert "Delivery Pacing:" in cur_msg["content"]

    spec_rendered = RP_PERCEPTION_CONTEXT_SPEC.render_user(
        RpPerceptionContext(
            locale="en",
            active_game="dark_demo",
            overall_summary="Entered the castle.",
            recent_episodes=((2, "Crossed the bridge."),),
            anchor=(10, True, "Bonfire chamber"),
            subtitles=(("subtitle", "The flame is fading."),),
            delta_mode="fresh",
            fresh_preview="The flame is fading.",
            player_busy=True,
        )
    )
    assert "[Overall Summary] Entered the castle." in spec_rendered
    assert "The player is actively engaged in controls." in spec_rendered


def test_cloud_summary_and_minute_composer_follow_ui_language() -> None:
    batch = [
        (10.0, "画面", "Detective opens the pocket watch"),
        (14.0, "字幕", "It stopped at 9:45!"),
    ]
    assert CLOUD_SUMMARY_SPEC.resolve_locale("en") == "en"
    assert CLOUD_SUMMARY_SPEC.resolve_locale("ja") == "ja"

    en_msgs = render_cloud_summary_messages(batch, active_game="ace_demo", locale="en")
    assert "[Current Slice Subtitle/Text Log]" in en_msgs[1]["content"]
    assert "[Visual] Detective opens the pocket watch" in en_msgs[1]["content"]

    en_parsed = parse_cloud_summary_response(
        json.dumps(
            {
                "subtitle_summary": "Subtitles: The watch stopped at 9:45",
                "visual_summary": "Visuals: Detective shows the cracked watch",
                "turning_point": "none",
                "overall_summary": "Timeline contradiction exposed.",
            }
        ),
        batch=batch,
        locale="en",
    )
    assert en_parsed.minute_summary == (
        "Subtitles: The watch stopped at 9:45. Visuals: Detective shows the cracked watch."
    )
    assert compose_minute_summary("証言の矛盾", "懐中時計を提示", "なし", locale="ja") == (
        "字幕：証言の矛盾。映像：懐中時計を提示。"
    )


@pytest.mark.parametrize(
    ("locale", "vision_marker", "bg_marker", "brief_marker", "plan_marker"),
    [
        ("zh_CN", "另一个大语言模型", "英文（English）标签", "100个字符", "角色立绘动作设计师"),
        ("en", "another language model", "concise English tags", "100 characters", "sprite pose designer"),
        ("ja", "別の言語モデル", "英語（English）のタグ", "100文字以内", "ポーズデザイナー"),
    ],
)
def test_generation_specs_follow_ui_language_while_preserving_untrusted_text(
    locale: str,
    vision_marker: str,
    bg_marker: str,
    brief_marker: str,
    plan_marker: str,
) -> None:
    assert BACKGROUND_ANNOTATION_SPEC.resolve_locale(locale) == locale
    assert vision_marker in render_vision_describe_prompt(locale=locale)
    assert bg_marker in render_background_annotation_prompt(locale=locale)

    retry = render_annotation_retry_prompt("BASE", "{bad_output}", locale=locale)
    assert retry.startswith("BASE\n")
    assert '"{bad_output}"' in retry

    setting_sys, setting_usr = render_character_setting_prompts(
        "Mika",
        "{untrusted_seed}",
        locale=locale,
    )
    assert "Mika" in setting_sys
    assert "{untrusted_seed}" in setting_usr

    brief_sys, brief_usr = render_character_brief_prompts(
        "Mika",
        "Likes {painting} and tea.",
        locale=locale,
    )
    assert brief_marker in brief_sys
    assert "Likes {painting} and tea." in brief_usr

    batch_sys, batch_usr = render_character_brief_batch_prompts(
        [{"name": "Mika", "setting": "{raw_braces}"}],
        locale=locale,
    )
    assert '"briefs"' in batch_sys
    assert "{raw_braces}" in batch_usr

    char_tr_sys, char_tr_usr = render_character_field_translation_prompts(
        ui_lang_code=locale,
        name="Mika",
        emotion_block="1: {calm}",
        character_setting="Quiet",
    )
    assert '"character_setting"' in char_tr_sys
    assert "{calm}" in char_tr_usr

    bg_tr_sys, bg_tr_usr = render_background_field_translation_prompts(
        ui_lang_code=locale,
        bg_name="Classroom",
        bg_info="Sunset",
        bgm_info="Piano",
        bgm_row_tags=["{gentle}"],
    )
    assert '"bgm_row_tags"' in bg_tr_sys
    assert "{gentle}" in bg_tr_usr

    _, full_suffix, _, ref_suffix = resolve_sprite_suffixes()
    plan_sys, plan_usr = render_sprite_plan_prompts(
        name="Mika",
        setting="{quiet_painter}",
        count=2,
        requirements="wave hand",
        has_reference=True,
        prompt_suffix=ref_suffix,
        locale=locale,
    )
    assert plan_marker in plan_sys
    assert ref_suffix in plan_sys
    assert full_suffix not in plan_sys
    assert "{quiet_painter}" in plan_usr

    rec_sys, rec_usr = render_transition_recommendation_prompts(
        name="Mika",
        setting="{setting}",
        sprites=[{"id": 1, "tagging": "开心，微笑"}],
        turns=[{"turn": 0, "text": "{hello}", "needsMapping": True}],
        locale=locale,
    )
    assert '"assignments"' in rec_sys
    assert "{hello}" in rec_usr
