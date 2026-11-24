"""Cloud LLM dual-stage Vision Memory summarizer and adaptive policy guide."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import logging
import re
import threading
from typing import Any

from ai.llm.template.integrations.localization import LocaleInput, resolve_dynamic_locale
from ai.llm.template.perception import render_cloud_summary_messages
from ai.perception.parser import sanitize_episode_summary
from core.perception.cache.episodes import (
    build_fallback_episode_summary,
    merge_fallback_overall_summary,
)
from core.perception.models import VisionEpisode, normalize_scene_mood
from sdk.lang import normalize_lang

logger = logging.getLogger(__name__)

CloudTextCompletionFn = Callable[[list[dict[str, str]]], str]

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

_SLOT_PREFIX_PATTERNS: dict[str, re.Pattern[str]] = {
    "subtitle": re.compile(
        r"^(?:字幕内容|屏幕文字|屏幕台词|字幕|台词|文字|subtitles?|screen\s*text|テキスト)\s*[：:]\s*",
        re.IGNORECASE,
    ),
    "visual": re.compile(
        r"^(?:画面内容|画面动态|画面表现|画面|映像|visuals?)\s*[：:]\s*",
        re.IGNORECASE,
    ),
    "turning_point": re.compile(
        r"^(?:关键转折|剧情转折|胜负转折|转折|反转|転機|転換点|turning\s*point)\s*[：:]\s*",
        re.IGNORECASE,
    ),
}

_EMPTY_SLOT_TOKENS: frozenset[str] = frozenset(
    {
        "",
        "无",
        "暂无",
        "没有",
        "空",
        "无内容",
        "なし",
        "特になし",
        "特に転機なし",
        "none",
        "no turning point",
        "null",
        "nil",
        "n/a",
        "na",
        "false",
        "-",
        "—",
        "——",
    }
)

_EMPTY_SLOT_SENTENCE_RE = re.compile(
    r"^(?:本段|当前|目前|暂时|此处|画面中|屏幕中)?(?:均|并|尚)?(?:无|没有|暂无|未见|未出现|未发生|不存在)"
    r"(?:出现|发生)?(?:明显|显著|重大|关键|实质|特殊|任何|新的)?(?:的)?(?:屏幕|剧情)?"
    r"(?:字幕内容|字幕|台词|文字|对话|画面内容|画面变化|画面动作|画面|关键转折|剧情转折|转折点|转折|反转|结果)$",
    re.IGNORECASE,
)


def _clean_summary_slot(raw: Any, *, slot: str, slot_max_chars: int) -> str:
    text = sanitize_episode_summary(str(raw or ""))
    text = text.strip(" \"'“”‘’。！!？?；;，,")
    prefix_re = _SLOT_PREFIX_PATTERNS.get(slot)
    if prefix_re is not None:
        text = prefix_re.sub("", text).strip(" \"'“”‘’。！!？?；;，,")
    lowered = text.casefold().strip()
    if not lowered or lowered in _EMPTY_SLOT_TOKENS:
        return ""
    if len(text) <= 20 and _EMPTY_SLOT_SENTENCE_RE.match(text):
        return ""
    text = re.sub(r"\s*[。；;！!]+\s*", "，", text).strip(" ，,。；;！!？?")
    if len(text) > slot_max_chars:
        clipped = text[:slot_max_chars]
        last_sep = max(clipped.rfind("，"), clipped.rfind(","), clipped.rfind("、"))
        if last_sep >= slot_max_chars // 2:
            clipped = clipped[:last_sep]
        text = clipped.rstrip(" ，,、：:")
    return text


def compose_minute_summary(
    subtitle_summary: Any = "",
    visual_summary: Any = "",
    turning_point: Any = "",
    *,
    max_chars: int = 120,
    locale: str | None = None,
) -> str:
    """Assemble the 2-to-3 sentence episodic summary in strict order: 字幕 -> 画面 -> 转折(optional)."""
    lang = normalize_lang(locale) if locale else "zh_CN"
    limit = max(40, int(max_chars))
    sub = _clean_summary_slot(subtitle_summary, slot="subtitle", slot_max_chars=42)
    vis = _clean_summary_slot(visual_summary, slot="visual", slot_max_chars=40)
    turn = _clean_summary_slot(turning_point, slot="turning_point", slot_max_chars=36)

    if lang == "en":
        labels = ("Subtitles", "Visuals", "Turning point")
        colon, end_punct, joiner = ": ", ". ", ""
    elif lang == "ja":
        labels = ("字幕", "映像", "転機")
        colon, end_punct, joiner = "：", "。", ""
    else:
        labels = ("字幕", "画面", "转折")
        colon, end_punct, joiner = "：", "。", ""

    sentences: list[str] = []
    for label, val in zip(labels, (sub, vis, turn), strict=True):
        if val:
            sentences.append(f"{label}{colon}{val}{end_punct}".strip() if lang == "en" else f"{label}{colon}{val}{end_punct}")

    if not sentences:
        return ""

    joined = (" ".join(sentences) if lang == "en" else joiner.join(sentences))
    if len(joined) <= limit:
        return joined

    per_slot = max(12, (limit - 4 * len(sentences)) // len(sentences))
    tightened: list[str] = []
    for label, val in zip(labels, (sub, vis, turn), strict=True):
        if not val:
            continue
        short_val = _clean_summary_slot(val, slot="", slot_max_chars=per_slot)
        if short_val:
            tightened.append(
                f"{label}: {short_val}." if lang == "en" else f"{label}{colon}{short_val}{end_punct}"
            )
    result = " ".join(tightened) if lang == "en" else joiner.join(tightened)
    if len(result) <= limit:
        return result
    tail = "." if lang == "en" else "。"
    return result[: limit - 1].rstrip(" ，,、：:。；;.") + tail


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
    minute_max_chars: int = 120,
    overall_max_chars: int = 180,
    active_game: str = "",
    locale: LocaleInput = None,
) -> list[dict[str, str]]:
    """Build stateless messages asking the Cloud LLM for dual summaries + adaptive guidance."""
    resolved_locale = resolve_dynamic_locale(locale) if locale is not None else "zh_CN"
    return render_cloud_summary_messages(
        batch,
        previous_overall_summary=previous_overall_summary,
        recent_episodes=recent_episodes,
        policy_snapshot=policy_snapshot,
        minute_max_chars=minute_max_chars,
        overall_max_chars=overall_max_chars,
        active_game=active_game,
        locale=resolved_locale,
    )


def parse_cloud_summary_response(
    raw_text: str,
    *,
    batch: Sequence[tuple[float, str, str]],
    previous_overall_summary: str = "",
    minute_max_chars: int = 120,
    overall_max_chars: int = 180,
    default_mood: str = "unclear",
    locale: str | None = None,
) -> CloudSummaryResult:
    """Parse Cloud LLM JSON output with deterministic fallback on malformed responses."""
    items = list(batch)
    has_text_items = (
        any(kind != "画面" and str(text or "").strip() for _ts, kind, text in items)
        if items
        else True
    )
    has_visual_items = (
        any(kind == "画面" and str(text or "").strip() for _ts, kind, text in items)
        if items
        else True
    )
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
        has_structured_slots = any(
            key in parsed for key in ("subtitle_summary", "visual_summary", "turning_point")
        )
        if has_structured_slots:
            minute = compose_minute_summary(
                parsed.get("subtitle_summary", "") if has_text_items else "",
                parsed.get("visual_summary", "") if has_visual_items else "",
                parsed.get("turning_point", ""),
                max_chars=minute_max_chars,
                locale=locale,
            )
        else:
            minute = ""
        if not minute and parsed.get("minute_summary"):
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
    locale: LocaleInput = None,
) -> CloudSummaryResult:
    """Run Cloud LLM dual-stage summarization on a prepared `RPInputCache` job."""
    batch = list(job.get("batch") or ())
    prev_overall = str(job.get("previous_overall_summary") or "")
    recent_episodes = tuple(job.get("recent_episodes") or ())
    policy_snapshot = job.get("policy_snapshot")
    minute_max_chars = int(job.get("minute_max_chars") or 120)
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
        resolved_locale = (
            resolve_dynamic_locale(locale) if locale is not None else "zh_CN"
        )
        messages = build_cloud_summary_messages(
            batch,
            previous_overall_summary=prev_overall,
            recent_episodes=recent_episodes,
            policy_snapshot=policy_snapshot if isinstance(policy_snapshot, Mapping) else None,
            minute_max_chars=minute_max_chars,
            overall_max_chars=overall_max_chars,
            active_game=active_game,
            locale=resolved_locale,
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
                    locale=resolved_locale,
                )
        except Exception:
            logger.debug("cloud vision memory summarization failed; falling back", exc_info=True)

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
    "compose_minute_summary",
    "create_cloud_text_completer",
    "extract_cloud_response_text",
    "parse_cloud_summary_response",
    "summarize_vision_window",
]
