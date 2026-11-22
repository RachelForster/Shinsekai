"""Pure Composite prompt sections for Cloud LLM dual-stage Vision Memory summarization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from sdk.lang import normalize_lang

from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection


@dataclass(frozen=True)
class CloudSummaryPromptContext(TemplateContext):
    """Context for Cloud LLM 2-minute slice & rolling overall summarization."""

    batch: tuple[tuple[float, str, str], ...] = ()
    previous_overall_summary: str = ""
    recent_episodes: tuple[tuple[int, str], ...] = ()
    policy_snapshot_json: str = ""
    minute_max_chars: int = 120
    overall_max_chars: int = 180
    active_game: str = ""


def build_cloud_summary_system_section() -> Section[CloudSummaryPromptContext]:
    return Section(
        "perception_cloud_summary_system",
        separator="\n",
        children=(
            I18nSection(
                "intro",
                priority=10,
                key="perception.cloud_summary_system_intro",
            ),
            I18nSection(
                "schema_top",
                priority=20,
                key="perception.cloud_summary_schema_top",
            ),
            I18nSection(
                "schema_overall",
                priority=30,
                key="perception.cloud_summary_schema_overall",
                params=lambda ctx: {"overall_max_chars": int(ctx.overall_max_chars)},
            ),
            I18nSection(
                "schema_bottom",
                priority=40,
                key="perception.cloud_summary_schema_bottom",
            ),
            I18nSection(
                "rule_1",
                priority=50,
                key="perception.cloud_summary_rule_1",
                params=lambda ctx: {"minute_max_chars": int(ctx.minute_max_chars)},
            ),
            I18nSection(
                "rules_rest",
                priority=60,
                key="perception.cloud_summary_rules_rest",
            ),
        ),
    )


class _CloudSummaryUserSection(Section[CloudSummaryPromptContext]):
    def _resolve_children(
        self,
        context: CloudSummaryPromptContext,
    ) -> tuple[Section[CloudSummaryPromptContext], ...]:
        children: list[Section[CloudSummaryPromptContext]] = []
        if context.active_game:
            children.append(
                I18nSection(
                    "active_game",
                    priority=10,
                    key="perception.cloud_summary_user_game",
                    params={"active_game": context.active_game},
                )
            )
        prev_summary = (
            context.previous_overall_summary.strip()
            or context.tr("perception.cloud_summary_user_prev_overall_empty")
        )
        children.append(
            I18nSection(
                "prev_overall",
                priority=20,
                key="perception.cloud_summary_user_prev_overall",
                params={"summary": prev_summary},
            )
        )
        if context.recent_episodes:
            ep_lines = "\n".join(
                context.tr(
                    "perception.cloud_summary_user_episode_item",
                    index=idx,
                    summary=summary,
                )
                for idx, summary in context.recent_episodes[-2:]
            )
            children.append(
                Section(
                    "recent_episodes",
                    priority=30,
                    separator="\n",
                    children=(
                        I18nSection(
                            "episodes_header",
                            priority=10,
                            key="perception.cloud_summary_user_recent_episodes_header",
                        ),
                        TextSection("episodes_body", priority=20, text=ep_lines),
                    ),
                )
            )
        if context.policy_snapshot_json:
            children.append(
                I18nSection(
                    "policy_snapshot",
                    priority=40,
                    key="perception.cloud_summary_user_policy",
                    params={"policy_json": context.policy_snapshot_json},
                )
            )

        visual_tag = context.tr("perception.cloud_summary_visual_tag")
        text_lines = [
            f"[{kind}] {text.strip()}"
            for _ts, kind, text in context.batch
            if kind != "画面" and str(text or "").strip()
        ]
        visual_lines = [
            f"[{visual_tag}] {text.strip()}"
            for _ts, kind, text in context.batch
            if kind == "画面" and str(text or "").strip()
        ]
        subtitles_body = (
            "\n".join(text_lines)[:1600]
            if text_lines
            else context.tr("perception.cloud_summary_user_subtitles_empty")
        )
        visuals_body = (
            "\n".join(visual_lines)[:1400]
            if visual_lines
            else context.tr("perception.cloud_summary_user_visuals_empty")
        )
        children.append(
            Section(
                "subtitles_block",
                priority=50,
                separator="\n",
                children=(
                    I18nSection(
                        "subtitles_header",
                        priority=10,
                        key="perception.cloud_summary_user_subtitles_header",
                    ),
                    TextSection("subtitles_body", priority=20, text=subtitles_body),
                ),
            )
        )
        children.append(
            Section(
                "visuals_block",
                priority=60,
                separator="\n",
                children=(
                    I18nSection(
                        "visuals_header",
                        priority=10,
                        key="perception.cloud_summary_user_visuals_header",
                    ),
                    TextSection("visuals_body", priority=20, text=visuals_body),
                ),
            )
        )
        return tuple(children)


def build_cloud_summary_user_section() -> Section[CloudSummaryPromptContext]:
    return _CloudSummaryUserSection("perception_cloud_summary_user", separator="\n\n")


CLOUD_SUMMARY_SPEC: PromptSpec[CloudSummaryPromptContext, CloudSummaryPromptContext] = (
    PromptSpec(
        id="perception.cloud_summary",
        language_policy=PromptLanguagePolicy.FOLLOW_UI,
        system_builder=build_cloud_summary_system_section,
        user_builder=build_cloud_summary_user_section,
    )
)


def render_cloud_summary_messages(
    batch: Sequence[tuple[float, str, str]],
    *,
    previous_overall_summary: str = "",
    recent_episodes: Sequence[Any] = (),
    policy_snapshot: Mapping[str, Any] | None = None,
    minute_max_chars: int = 120,
    overall_max_chars: int = 180,
    active_game: str = "",
    locale: str | None = None,
) -> list[dict[str, str]]:
    episode_pairs = tuple(
        (int(getattr(ep, "index", 0)), str(getattr(ep, "summary", "") or ""))
        for ep in recent_episodes
    )
    policy_json = (
        json.dumps(dict(policy_snapshot), ensure_ascii=False)
        if policy_snapshot
        else ""
    )
    ctx = CloudSummaryPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        batch=tuple((float(ts), str(kind), str(text)) for ts, kind, text in batch),
        previous_overall_summary=previous_overall_summary,
        recent_episodes=episode_pairs,
        policy_snapshot_json=policy_json,
        minute_max_chars=int(minute_max_chars),
        overall_max_chars=int(overall_max_chars),
        active_game=str(active_game or ""),
    )
    return [
        {"role": "system", "content": CLOUD_SUMMARY_SPEC.render_system(ctx)},
        {"role": "user", "content": CLOUD_SUMMARY_SPEC.render_user(ctx)},
    ]


__all__ = [
    "CLOUD_SUMMARY_SPEC",
    "CloudSummaryPromptContext",
    "build_cloud_summary_system_section",
    "build_cloud_summary_user_section",
    "render_cloud_summary_messages",
]
