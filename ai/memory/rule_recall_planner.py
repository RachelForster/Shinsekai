"""Zero-latency rule-based RecallPlanner (<1ms, zero LLM roundtrips)."""

from __future__ import annotations

import re

from ai.memory.temporal import parse_query_time_range
from core.chat_history.text import strip_local_time_prefix
from sdk.adapters.memory import RecallPlan, TurnRecallInput

DEFAULT_WAKEUP_GAP_SECONDS = 4.0 * 3600.0
DEFAULT_SHORT_UTTERANCE_CHARS = 12
DEFAULT_MAX_CLAUSES = 4
DEFAULT_PLAN_LIMIT = 6

_PUNCT_STRIP_RE = re.compile(r"^[\s,，.。!！?？;；:：、~～…\-—()（）\[\]【】\"'“”‘’]+|[\s,，.。!！?？;；:：、~～…\-—()（）\[\]【】\"'“”‘’]+$")
_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")

_PURE_FILLERS: frozenset[str] = frozenset(
    {
        "嗯",
        "嗯嗯",
        "哦",
        "哦哦",
        "噢",
        "好",
        "好的",
        "好呀",
        "好吧",
        "行",
        "行吧",
        "哈哈",
        "哈哈哈",
        "嘿嘿",
        "呵呵",
        "唔",
        "啊",
        "呀",
        "草",
        "www",
        "ok",
        "okay",
        "k",
        "yes",
        "yeah",
        "yep",
        "lol",
        "うん",
        "はい",
        "ああ",
        "なるほど",
        "へえ",
    }
)

_ANAPHORA_CUES: tuple[str, ...] = (
    "那件事",
    "那个",
    "这件事",
    "这个",
    "那次",
    "上次",
    "之前",
    "刚才",
    "后来",
    "继续",
    "他",
    "她",
    "它",
    "他们",
    "她们",
    "あれ",
    "それ",
    "さっき",
    "あの件",
    "例の",
)
_ANAPHORA_EN_RE = re.compile(
    r"\b(?:that|it|this|him|her|them|earlier|last time|about that)\b",
    re.IGNORECASE,
)

_PERCEPTION_MARKER = "[Shinsekai realtime game perception cache]"
_PERCEPTION_BOILERPLATE_PREFIXES: tuple[str, ...] = (
    "[系统事件：",
    "以下是近期画面与屏幕台词的观察记录",
    "请根据你看到的内容回复",
    "- 前情纪要：",
    "- 近期画面动态",
    "- 屏幕台词/文字",
    "- 玩家正在操作",
    "- 提示：",
    "- 本轮新增动态：",
    "- 本次触发焦点：",
    "- 表达节奏：",
    "- [画面背景·",
)


def _extract_perception_clauses(raw_text: str, *, max_clauses: int) -> list[str]:
    text = str(raw_text or "").strip()
    if not text:
        return []
    if _PERCEPTION_MARKER in text:
        _, _, text = text.partition(_PERCEPTION_MARKER)
        # Drop optional `（当前游戏/来源：...）` header line while keeping game name if useful
        lines = text.splitlines()
        cleaned_lines: list[str] = []
        for idx, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue
            if idx == 0 and line.startswith("（") and line.endswith("）"):
                continue
            if any(line.startswith(prefix) for prefix in _PERCEPTION_BOILERPLATE_PREFIXES):
                continue
            line = re.sub(r"^[-*•\s]+", "", line)
            line = re.sub(r"^\[[^\]]{1,24}\]\s*", "", line).strip()
            if line:
                cleaned_lines.append(line)
        return cleaned_lines[-max_clauses:]

    # Custom/direct perception prompt without standard cache header
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not any(line.strip().startswith(p) for p in _PERCEPTION_BOILERPLATE_PREFIXES)
    ]
    return lines[-max_clauses:]


def _split_clauses(text: str, *, max_clauses: int) -> list[str]:
    parts = [seg.strip() for seg in _CLAUSE_SPLIT_RE.split(text) if seg.strip()]
    if not parts:
        return [text.strip()] if text.strip() else []
    merged: list[str] = []
    for part in parts:
        if merged and len(part) < 4:
            merged[-1] = f"{merged[-1]}，{part}"
        else:
            merged.append(part)
    if len(merged) <= max_clauses:
        return merged
    # Keep first clauses and merge remaining tail into final slot so no topic is lost
    head = merged[: max_clauses - 1]
    tail = "；".join(merged[max_clauses - 1 :])[:240]
    return [*head, tail]


def _needs_context_stitching(text: str, *, short_threshold: int) -> bool:
    if len(text) < short_threshold:
        return True
    if any(cue in text for cue in _ANAPHORA_CUES):
        return True
    return bool(_ANAPHORA_EN_RE.search(text))


class RuleRecallPlanner:
    """Deterministic zero-latency planner decomposing turns into hybrid recall plans."""

    def __init__(
        self,
        *,
        wakeup_gap_seconds: float = DEFAULT_WAKEUP_GAP_SECONDS,
        short_utterance_chars: int = DEFAULT_SHORT_UTTERANCE_CHARS,
        max_clauses: int = DEFAULT_MAX_CLAUSES,
        default_limit: int = DEFAULT_PLAN_LIMIT,
    ) -> None:
        self.wakeup_gap_seconds = max(60.0, float(wakeup_gap_seconds))
        self.short_utterance_chars = max(1, int(short_utterance_chars))
        self.max_clauses = max(1, int(max_clauses))
        self.default_limit = max(1, int(default_limit))

    def plan(self, turn_input: TurnRecallInput) -> RecallPlan:
        source = str(turn_input.source or "user").strip().lower()
        raw_user = strip_local_time_prefix(str(turn_input.user_text or "")).strip()

        if source != "perception" and source != "user" and source in {"chunk_feed", "compact_summary"}:
            return RecallPlan(should_recall=False)

        if source == "perception":
            obs_clauses = _extract_perception_clauses(
                raw_user,
                max_clauses=min(3, self.max_clauses),
            )
            if not obs_clauses:
                return RecallPlan(should_recall=False)
            prev_tail = strip_local_time_prefix(
                str(turn_input.previous_assistant_text or "")
            ).strip()[-100:]
            if prev_tail and len(obs_clauses) < self.max_clauses:
                obs_clauses.append(prev_tail)
            kw = " ".join(obs_clauses)[:280]
            return RecallPlan(
                should_recall=True,
                is_session_wakeup=False,
                query_clauses=tuple(obs_clauses),
                keyword_query=kw,
                limit=min(4, self.default_limit),
            )

        is_wakeup = float(turn_input.seconds_since_last_turn or 0.0) >= self.wakeup_gap_seconds
        if not raw_user:
            if is_wakeup:
                return RecallPlan(
                    should_recall=True,
                    is_session_wakeup=True,
                    query_clauses=("近期约定 承诺 待办 重要近况",),
                    keyword_query="约定 承诺 待办",
                    limit=self.default_limit,
                )
            return RecallPlan(should_recall=False)

        event_from, event_to = parse_query_time_range(
            raw_user,
            now_ts=turn_input.now_ts if turn_input.now_ts > 0 else None,
        )

        normalized_token = _PUNCT_STRIP_RE.sub("", raw_user).casefold()
        if (
            not is_wakeup
            and event_from is None
            and event_to is None
            and (not normalized_token or normalized_token in _PURE_FILLERS)
        ):
            return RecallPlan(should_recall=False)

        clauses = _split_clauses(raw_user, max_clauses=self.max_clauses)
        prev_assist = strip_local_time_prefix(
            str(turn_input.previous_assistant_text or "")
        ).strip()
        stitched_clause = ""
        if prev_assist and _needs_context_stitching(
            raw_user,
            short_threshold=self.short_utterance_chars,
        ):
            assist_tail = prev_assist[-140:].strip()
            if assist_tail:
                stitched_clause = f"{assist_tail} {raw_user}".strip()

        if stitched_clause and stitched_clause not in clauses:
            if len(clauses) >= self.max_clauses:
                clauses = [*clauses[: self.max_clauses - 1], stitched_clause]
            else:
                clauses.append(stitched_clause)

        if is_wakeup and len(clauses) < self.max_clauses:
            wakeup_clause = "近期约定 承诺 计划 未完成的事"
            if wakeup_clause not in clauses:
                clauses.append(wakeup_clause)

        keyword_source = stitched_clause if stitched_clause else " ".join(clauses)
        return RecallPlan(
            should_recall=True,
            is_session_wakeup=is_wakeup,
            query_clauses=tuple(clauses),
            keyword_query=keyword_source[:300],
            event_from=event_from,
            event_to=event_to,
            limit=self.default_limit,
        )


__all__ = [
    "DEFAULT_MAX_CLAUSES",
    "DEFAULT_PLAN_LIMIT",
    "DEFAULT_SHORT_UTTERANCE_CHARS",
    "DEFAULT_WAKEUP_GAP_SECONDS",
    "RuleRecallPlanner",
]
