"""Cloud LLM dual-stage Vision Memory summarizer and adaptive policy guide."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import logging
import re
import threading
from typing import Any

from ai.perception.parser import sanitize_episode_summary
from core.perception.cache.episodes import (
    build_fallback_episode_summary,
    merge_fallback_overall_summary,
)
from core.perception.models import VisionEpisode, normalize_scene_mood

logger = logging.getLogger(__name__)

CloudTextCompletionFn = Callable[[list[dict[str, str]]], str]

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CloudSummaryResult:
    """Parsed dual-stage summary + optional adaptive guidance returned by the Cloud LLM."""

    minute_summary: str
    overall_summary: str
    mood: str = "unclear"
    guidance: dict[str, Any] = field(default_factory=dict)


def extract_cloud_response_text(adapter: Any, response: Any) -> str:
    """Extract plain text from any `LLMAdapter.chat(..., stream=False)` response object."""
    if response is None:
        return ""
    decode = getattr(adapter, "decode_response", None)
    if callable(decode):
        try:
            decoded_content = decode(response).content
            if isinstance(decoded_content, str) and decoded_content.strip():
                return decoded_content.strip()
        except Exception:
            pass
    try:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            return str(getattr(message, "content", "") or "").strip()
        if hasattr(response, "text"):
            return str(response.text or "").strip()
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list) and content:
                return str(getattr(content[0], "text", "") or content[0]).strip()
    except Exception:
        logger.debug("failed to extract cloud summary response content", exc_info=True)
    return str(response or "").strip()


def _resolve_llm_factory_kwargs(source: Any) -> dict[str, Any] | None:
    if callable(source):
        raw = source()
        return dict(raw) if isinstance(raw, Mapping) else None
    get_llm_cfg = getattr(source, "get_llm_api_config", None)
    if not callable(get_llm_cfg):
        return None
    provider, model, base_url, api_key = get_llm_cfg()
    if not provider or not model or (not api_key and provider != "Ollama"):
        return None
    base_kwargs: dict[str, Any] = {
        "llm_provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }
    merge_fn = getattr(source, "merged_llm_factory_kwargs", None)
    kwargs = dict(merge_fn(provider, base_kwargs)) if callable(merge_fn) else base_kwargs
    kwargs["thinking_enabled"] = False
    return kwargs


def create_cloud_text_completer(
    config_or_supplier: Any,
) -> CloudTextCompletionFn:
    """Create a thread-safe out-of-band Cloud LLM text completer using a dedicated adapter instance."""
    lock = threading.Lock()
    cached_sig: tuple[Any, ...] | None = None
    cached_adapter: Any | None = None

    def complete(messages: list[dict[str, str]]) -> str:
        nonlocal cached_sig, cached_adapter
        kwargs = _resolve_llm_factory_kwargs(config_or_supplier)
        if not kwargs:
            return ""
        sig = (
            kwargs.get("llm_provider"),
            kwargs.get("model"),
            kwargs.get("base_url"),
            kwargs.get("api_key"),
        )
        with lock:
            if cached_adapter is None or cached_sig != sig:
                from ai.llm.adapter_factory import LLMAdapterFactory

                cached_adapter = LLMAdapterFactory.create_adapter(**dict(kwargs))
                cached_sig = sig
            adapter = cached_adapter
        response = adapter.chat(
            messages,
            stream=False,
            response_format={"type": "text"},
        )
        return extract_cloud_response_text(adapter, response)

    return complete


def build_cloud_summary_messages(
    batch: Sequence[tuple[float, str, str]],
    *,
    previous_overall_summary: str = "",
    recent_episodes: Sequence[VisionEpisode] = (),
    policy_snapshot: Mapping[str, Any] | None = None,
    minute_max_chars: int = 90,
    overall_max_chars: int = 180,
    active_game: str = "",
) -> list[dict[str, str]]:
    """Build stateless messages asking the Cloud LLM for dual summaries + adaptive guidance."""
    system_prompt = (
        "你是实时陪看/陪玩系统的云端视觉记忆整理与感知策略助手。\n"
        "请根据「既有总体纪要」与「最近约2分钟按时间排列的画面及OCR字幕」，输出一个严格的JSON对象：\n"
        "{\n"
        f'  "minute_summary": "{minute_max_chars}字以内，客观浓缩本段2分钟关键画面动作与OCR台词事实，禁止加入情绪基调判断、主观感叹或脑补",\n'
        f'  "overall_summary": "{overall_max_chars}字以内，在既有总体纪要基础上融合本段主线事实进展，保留核心人物/线索/胜负转折，禁止附带情绪基调标签",\n'
        '  "mood": "calm|serious|sad|tense|joyful|hyped|unclear",\n'
        '  "guidance": {\n'
        '    "scene_pace": "auto|dialogue_heavy|action_heavy|quiet",\n'
        '    "visual_beats_subtitle_heavy": 2,\n'
        '    "visual_beats_visual_heavy": 5,\n'
        '    "notable_salience_floor": 0.85,\n'
        '    "focus_hint": "给本地视觉模型的简短观察侧重提示（28字以内，无需调整填\\"\\"）"\n'
        "  }\n"
        "}\n"
        "规则：\n"
        "1. 只依据提供的观察记录整理，OCR谐音错字可结合上下文轻微修正，但禁止编造未出现的信息。\n"
        "2. guidance用于主动自适应指导后续参数：台词密集的文戏/科普/访谈设 scene_pace=\"dialogue_heavy\"、visual_beats_subtitle_heavy=1~2；"
        "少台词的探索/战斗设 scene_pace=\"action_heavy\"、visual_beats_visual_heavy=5~6；若琐碎波动过多可上调 notable_salience_floor（0.85~0.92）。无需调整时 guidance 可填 {}。\n"
        "3. 只输出一行合法JSON对象，不要包含Markdown代码块。"
    )

    user_sections: list[str] = []
    if active_game:
        user_sections.append(f"[当前游戏/来源] {active_game}")
    user_sections.append(
        f"[既有总体纪要] {previous_overall_summary.strip() or '（暂无，这是首段记录）'}"
    )
    if recent_episodes:
        ep_lines = [f"- 第{ep.index}段：{ep.summary}" for ep in recent_episodes[-2:]]
        user_sections.append("[最近分段纪要]\n" + "\n".join(ep_lines))
    if policy_snapshot:
        user_sections.append(
            "[当前策略参数] " + json.dumps(dict(policy_snapshot), ensure_ascii=False)
        )
    obs_lines = [f"[{kind}] {text.strip()}" for _ts, kind, text in batch if str(text or "").strip()]
    user_sections.append("[本段按时间排序的观察记录]\n" + "\n".join(obs_lines)[:2800])

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_sections)},
    ]


def parse_cloud_summary_response(
    raw_text: str,
    *,
    batch: Sequence[tuple[float, str, str]],
    previous_overall_summary: str = "",
    minute_max_chars: int = 90,
    overall_max_chars: int = 180,
    default_mood: str = "unclear",
) -> CloudSummaryResult:
    """Parse Cloud LLM JSON output with deterministic fallback on malformed responses."""
    items = list(batch)
    cleaned = _CODE_FENCE_RE.sub("", str(raw_text or "").strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    candidate = cleaned[start : end + 1] if (start != -1 and end > start) else ""

    parsed: dict[str, Any] | None = None
    if candidate:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                parsed = obj
        except json.JSONDecodeError:
            parsed = None

    if parsed is not None:
        minute = sanitize_episode_summary(str(parsed.get("minute_summary") or ""))[:minute_max_chars]
        overall = sanitize_episode_summary(str(parsed.get("overall_summary") or ""))[:overall_max_chars]
        mood = normalize_scene_mood(parsed.get("mood")) or normalize_scene_mood(default_mood) or "unclear"
        raw_guidance = parsed.get("guidance")
        guidance = dict(raw_guidance) if isinstance(raw_guidance, Mapping) else {}
    else:
        minute = sanitize_episode_summary(cleaned)[:minute_max_chars] if cleaned and "{" not in cleaned else ""
        overall = ""
        mood = normalize_scene_mood(default_mood) or "unclear"
        guidance = {}

    if not minute:
        minute = build_fallback_episode_summary(items, max_chars=minute_max_chars)
    if not overall:
        overall = merge_fallback_overall_summary(
            previous_overall_summary,
            minute,
            max_chars=overall_max_chars,
        )

    return CloudSummaryResult(
        minute_summary=minute,
        overall_summary=overall,
        mood=mood,
        guidance=guidance,
    )


def summarize_vision_window(
    job: Mapping[str, Any],
    *,
    cloud_complete: CloudTextCompletionFn | None = None,
    fallback_summarizer: Callable[[Sequence[tuple[float, str, str]]], str] | None = None,
) -> CloudSummaryResult:
    """Run Cloud LLM dual-stage summarization on a prepared `RPInputCache` job."""
    batch = list(job.get("batch") or ())
    prev_overall = str(job.get("previous_overall_summary") or "")
    recent_episodes = tuple(job.get("recent_episodes") or ())
    policy_snapshot = job.get("policy_snapshot")
    minute_max_chars = int(job.get("minute_max_chars") or 90)
    overall_max_chars = int(job.get("overall_max_chars") or 180)
    active_game = str(job.get("active_game") or "")
    current_mood = str(job.get("current_mood") or "unclear")

    if not batch:
        return CloudSummaryResult(
            minute_summary="",
            overall_summary=prev_overall,
            mood=current_mood,
        )

    if callable(cloud_complete):
        messages = build_cloud_summary_messages(
            batch,
            previous_overall_summary=prev_overall,
            recent_episodes=recent_episodes,
            policy_snapshot=policy_snapshot if isinstance(policy_snapshot, Mapping) else None,
            minute_max_chars=minute_max_chars,
            overall_max_chars=overall_max_chars,
            active_game=active_game,
        )
        try:
            raw = cloud_complete(messages)
            if str(raw or "").strip():
                return parse_cloud_summary_response(
                    raw,
                    batch=batch,
                    previous_overall_summary=prev_overall,
                    minute_max_chars=minute_max_chars,
                    overall_max_chars=overall_max_chars,
                    default_mood=current_mood,
                )
        except Exception:
            logger.debug("cloud vision memory summarization failed; falling back", exc_info=True)

    minute = ""
    if callable(fallback_summarizer):
        try:
            minute = sanitize_episode_summary(fallback_summarizer(batch))[:minute_max_chars]
        except Exception:
            minute = ""
    if not minute:
        minute = build_fallback_episode_summary(batch, max_chars=minute_max_chars)
    overall = merge_fallback_overall_summary(
        prev_overall,
        minute,
        max_chars=overall_max_chars,
    )
    return CloudSummaryResult(
        minute_summary=minute,
        overall_summary=overall,
        mood=normalize_scene_mood(current_mood) or "unclear",
    )


__all__ = [
    "CloudSummaryResult",
    "CloudTextCompletionFn",
    "build_cloud_summary_messages",
    "create_cloud_text_completer",
    "extract_cloud_response_text",
    "parse_cloud_summary_response",
    "summarize_vision_window",
]
