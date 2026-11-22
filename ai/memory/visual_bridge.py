"""Multimodal Triple-Layer Visual Memory Bridge (MIRIX + M3-Agent + WorldMM).

Closes both visual amnesia breakpoints in Shinsekai without modifying any SOLID
`Protocol` in `sdk/adapters/memory.py` or bundling heavy CLIP encoders:
1. Chat Image Attachments: Recovers fallback vision descriptions with zero extra
   VLM calls and captions native `local_image` blocks asynchronously on the
   background extraction worker, binding vault-relative `visual_ref` pointers
   (`data/chat_attachments/<uuid>/<name>`) for optional WorldMM pixel re-inspection.
2. Screen / Game Companion Promotion: Extracts salient observations and
   `active_game` entities from `[Shinsekai realtime game perception cache]` so
   shared gaming/watching moments promote into Tier-2 `visual`/`episodic` graph
   memories ONLY when paired with real dialogue (never firing unsolicited LLM
   extraction on silent proactive-only turns).
"""

from __future__ import annotations

import base64
import binascii
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any

from ai.memory.extraction import clean_text, extract_response_text
from ai.memory.metadata_tags import pack_system_tags, sanitize_visual_ref, unpack_system_tags
from ai.vision.message_content import LOCAL_IMAGE_BLOCK_TYPE, normalize_openai_messages
from ai.vision.service import (
    ChatVisionService,
    VisionDescriber,
    configured_vision_available,
    configured_vision_manager,
)
from core.media.chat_attachments import (
    CHAT_ATTACHMENTS_ROOT_ENV,
    CHAT_ATTACHMENT_STAGE_SUBDIR,
)
from core.perception.cache.formatter import PERCEPTION_CONTEXT_MARKER
from sdk.adapters.memory import MemoryDraft

logger = logging.getLogger(__name__)

DEFAULT_AMBIENT_PERCEPTION_TTL_SEC = 600.0
DEFAULT_MAX_AMBIENT_SNAPSHOTS = 4
MEMORY_IMAGE_CAPTION_PROMPT = (
    "请用一到两句紧凑中文准确描述这张图片的核心内容（主体人物/动物/物品、关键外观特征、"
    "场景氛围以及画面中重要的文字或界面信息），用于角色长期记忆归档。"
)

_FALLBACK_DESC_RE = re.compile(
    r"Image attachment\s+(?P<name>[^\n:]+):\s*\n(?P<desc>.+?)(?=\n\n(?:Image attachment|--- BEGIN|\[Shinsekai)|$)",
    re.DOTALL,
)
_GAME_SOURCE_RE = re.compile(r"（当前游戏/来源：([^）\n]+)）")
_PERCEPTION_SKIP_PREFIXES = (
    "以下是近期画面与屏幕台词的观察记录",
    "请根据你看到的内容回复",
    "[系统事件：",
    "- 前情纪要：",
    "- 近期画面动态",
    "- 屏幕台词/文字",
    "- 玩家正在操作",
)


@dataclass(frozen=True, slots=True)
class PendingImageArtifact:
    """Lightweight image metadata captured on `message_added` without blocking chat."""

    name: str
    visual_ref: str
    precomputed_description: str = ""
    media_type: str = "image/png"
    raw_path: str = ""
    base64_data: str = ""


@dataclass(frozen=True, slots=True)
class PerceptionSnapshot:
    """Compact screen/game observation digest captured from Tier-1 `RPInputCache`."""

    summary: str
    active_game: str = ""
    captured_at: float = 0.0


def normalize_attachment_visual_ref(raw_path: str, *, fallback_name: str = "") -> str:
    """Convert an absolute staged attachment path into a safe vault-relative `visual_ref`."""
    raw = str(raw_path or "").strip()
    if raw:
        norm_slashes = raw.replace("\\", "/")
        stage_marker = "/".join(CHAT_ATTACHMENT_STAGE_SUBDIR)  # "data/chat_attachments"
        lower_slashes = norm_slashes.casefold()
        idx = lower_slashes.find(stage_marker.casefold())
        if idx >= 0:
            rel = norm_slashes[idx:]
            safe = sanitize_visual_ref(rel)
            if safe:
                return safe

        env_root = os.environ.get(CHAT_ATTACHMENTS_ROOT_ENV, "").strip()
        if env_root:
            try:
                rel_from_root = Path(raw).resolve(strict=False).relative_to(
                    Path(env_root).expanduser().resolve(strict=False)
                )
                safe = sanitize_visual_ref(rel_from_root.as_posix())
                if safe:
                    return safe
            except (OSError, ValueError):
                pass

        # Accept already-relative safe refs
        safe_direct = sanitize_visual_ref(norm_slashes)
        if safe_direct:
            return safe_direct

    clean_name = sanitize_visual_ref(fallback_name)
    return f"chat_attachments/{clean_name}" if clean_name else ""


def parse_perception_block(text: str) -> PerceptionSnapshot | None:
    """Extract compact visual/subtitle digest and `active_game` from a perception block."""
    raw = str(text or "")
    marker_idx = raw.find(PERCEPTION_CONTEXT_MARKER)
    if marker_idx < 0:
        return None
    section = raw[marker_idx:]
    game_match = _GAME_SOURCE_RE.search(section[:200])
    active_game = clean_text(game_match.group(1), max_chars=80) if game_match else ""

    salient_lines: list[str] = []
    for raw_line in section.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in _PERCEPTION_SKIP_PREFIXES):
            continue
        cleaned = re.sub(r"^[*-]\s*", "", line).strip()
        if cleaned and len(cleaned) >= 3:
            salient_lines.append(cleaned)
        if len(salient_lines) >= 5:
            break

    if not salient_lines:
        return None
    summary = clean_text("；".join(salient_lines), max_chars=360)
    return PerceptionSnapshot(summary=summary, active_game=active_game)


def extract_message_visual_artifacts(
    message: Mapping[str, Any],
) -> tuple[tuple[PendingImageArtifact, ...], PerceptionSnapshot | None]:
    """Non-blocking inspection of raw message content & attachments before `display_content` masks them."""
    raw_content = message.get("content")
    attachments_meta = message.get("attachments")
    attachment_path_by_name: dict[str, str] = {}
    ordered_image_attachments: list[tuple[str, str]] = []
    if isinstance(attachments_meta, Sequence) and not isinstance(attachments_meta, (str, bytes)):
        for item in attachments_meta:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("kind") or "").strip().lower() != "image":
                continue
            name = str(item.get("name") or "").strip()
            path = str(item.get("path") or "").strip()
            if name and path:
                attachment_path_by_name[name.casefold()] = path
                ordered_image_attachments.append((name, path))

    artifacts: list[PendingImageArtifact] = []
    text_chunks: list[str] = []

    if isinstance(raw_content, str):
        text_chunks.append(raw_content)
    elif isinstance(raw_content, Sequence) and not isinstance(raw_content, (str, bytes)):
        for block in raw_content:
            if not isinstance(block, Mapping):
                continue
            btype = str(block.get("type") or "")
            if btype == "text":
                t = str(block.get("text") or "")
                if t:
                    text_chunks.append(t)
            elif btype == LOCAL_IMAGE_BLOCK_TYPE:
                name = str(block.get("name") or "image.png").strip() or "image.png"
                raw_path = (
                    str(block.get("path") or "").strip()
                    or attachment_path_by_name.get(name.casefold(), "")
                )
                vref = normalize_attachment_visual_ref(raw_path, fallback_name=name)
                artifacts.append(
                    PendingImageArtifact(
                        name=name,
                        visual_ref=vref,
                        media_type=str(block.get("media_type") or "image/png"),
                        raw_path=raw_path,
                        base64_data=str(block.get("data") or ""),
                    )
                )

    combined_text = "\n\n".join(text_chunks)
    if not artifacts and combined_text:
        for idx, match in enumerate(_FALLBACK_DESC_RE.finditer(combined_text)):
            name = clean_text(match.group("name"), max_chars=120) or f"image_{idx + 1}.png"
            desc = clean_text(match.group("desc"), max_chars=500)
            if not desc or desc == "[No description returned]":
                continue
            raw_path = attachment_path_by_name.get(name.casefold(), "")
            if not raw_path and idx < len(ordered_image_attachments):
                raw_path = ordered_image_attachments[idx][1]
            vref = normalize_attachment_visual_ref(raw_path, fallback_name=name)
            artifacts.append(
                PendingImageArtifact(
                    name=name,
                    visual_ref=vref,
                    precomputed_description=desc,
                    raw_path=raw_path,
                )
            )

    perception_source = combined_text or str(message.get("_perception_digest") or "")
    perception_snap = parse_perception_block(perception_source)
    return tuple(artifacts), perception_snap


def resolve_vault_attachment_path(
    visual_ref: str,
    *,
    attachments_root: Path | None = None,
) -> Path | None:
    """Resolve `visual_ref` strictly inside the allowed chat attachments directory."""
    safe_ref = sanitize_visual_ref(visual_ref)
    if not safe_ref:
        return None

    base_root = attachments_root
    if base_root is None:
        env_val = os.environ.get(CHAT_ATTACHMENTS_ROOT_ENV, "").strip()
        base_root = Path(env_val).expanduser() if env_val else Path.cwd()
    try:
        resolved_root = base_root.resolve(strict=True)
    except OSError:
        return None

    stage_root = resolved_root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR)
    candidate = (resolved_root / safe_ref).resolve(strict=False)
    allowed_roots = [resolved_root]
    if stage_root.exists():
        allowed_roots = [stage_root.resolve(strict=False)]

    norm_cand = os.path.normcase(str(candidate))
    is_inside = any(
        norm_cand.startswith(
            os.path.normcase(str(r)).rstrip(os.sep) + os.sep
        )
        for r in allowed_roots
    )
    if not is_inside or not candidate.is_file():
        return None
    return candidate


def reinspect_visual_memory(
    visual_ref: str,
    question: str,
    *,
    describer: VisionDescriber | None = None,
    attachments_root: Path | None = None,
) -> dict[str, Any]:
    """WorldMM-style on-demand pixel-level VLM re-inspection of a stored `visual_ref`."""
    target_path = resolve_vault_attachment_path(
        visual_ref,
        attachments_root=attachments_root,
    )
    if target_path is None:
        return {"ok": False, "error": "visual evidence file unavailable", "visualRef": visual_ref}

    q_text = clean_text(question, max_chars=300) or "请描述这张图片里的具体细节。"
    prompt = f"根据以下问题仔细查看原图并准确回答：{q_text}"
    try:
        eff_describer = describer
        if eff_describer is None:
            if not configured_vision_available():
                return {
                    "ok": False,
                    "error": "vision describer unavailable",
                    "visualRef": visual_ref,
                }
            eff_describer = configured_vision_manager()
        answer = clean_text(
            eff_describer.describe(target_path.read_bytes(), prompt),
            max_chars=600,
        )
        return {
            "ok": True,
            "visualRef": sanitize_visual_ref(visual_ref),
            "answer": answer,
        }
    except Exception as exc:
        logger.warning("visual memory re-inspection failed", exc_info=True)
        return {"ok": False, "error": str(exc), "visualRef": visual_ref}


class VisualMemoryBridge:
    """Bridges chat image attachments & screen/game perception into Tier-2 long-term memory."""

    def __init__(
        self,
        llm_adapter: Any,
        *,
        vision_describer_factory: Callable[[], VisionDescriber] | None = None,
        vision_available_probe: Callable[[], bool] | None = None,
        ambient_ttl_seconds: float = DEFAULT_AMBIENT_PERCEPTION_TTL_SEC,
    ) -> None:
        self.llm_adapter = llm_adapter
        self._describer_factory = vision_describer_factory
        self._vision_available = vision_available_probe or (
            configured_vision_available
            if vision_describer_factory is None
            else (lambda: True)
        )
        self.ambient_ttl_seconds = max(10.0, float(ambient_ttl_seconds))
        self._lock = threading.RLock()
        self._ambient_perception: deque[PerceptionSnapshot] = deque(
            maxlen=DEFAULT_MAX_AMBIENT_SNAPSHOTS
        )
        self._pending_turn_perception: PerceptionSnapshot | None = None

    def clear_state(self) -> None:
        """Clear transient perception state on rollback or memory mode switch."""
        with self._lock:
            self._ambient_perception.clear()
            self._pending_turn_perception = None

    def observe_before_chat_turn(
        self,
        *,
        user_text: str,
        source: str,
        now_ts: float,
    ) -> None:
        """Capture `PerceptionAutoHooks`-injected screen context with zero latency on `before_chat`."""
        snap = parse_perception_block(user_text)
        if snap is None:
            return
        stamped = replace(snap, captured_at=float(now_ts))
        with self._lock:
            if source == "perception":
                if (
                    not self._ambient_perception
                    or self._ambient_perception[-1].summary != stamped.summary
                ):
                    self._ambient_perception.append(stamped)
            else:
                self._pending_turn_perception = stamped

    def consume_turn_perception_for_user(
        self,
        *,
        explicit_snapshot: PerceptionSnapshot | None,
        now_ts: float,
    ) -> PerceptionSnapshot | None:
        """Bind active or recent ambient screen perception onto a real user dialogue turn."""
        with self._lock:
            direct = explicit_snapshot or self._pending_turn_perception
            self._pending_turn_perception = None
            if direct is not None:
                # Clear ambient items already subsumed by this direct snapshot
                self._ambient_perception.clear()
                return replace(direct, captured_at=float(now_ts))

            fresh = [
                item
                for item in self._ambient_perception
                if float(now_ts) - item.captured_at <= self.ambient_ttl_seconds
            ]
            self._ambient_perception.clear()
            if not fresh:
                return None
            merged_summary = clean_text(
                "；".join(dict.fromkeys(item.summary for item in fresh if item.summary)),
                max_chars=380,
            )
            active_game = next(
                (item.active_game for item in reversed(fresh) if item.active_game),
                "",
            )
            return PerceptionSnapshot(
                summary=merged_summary,
                active_game=active_game,
                captured_at=float(now_ts),
            )

    def enrich_messages_for_extraction(
        self,
        messages: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        """Run on background worker: caption native images & format perception context.

        Returns `(enriched_messages, ordered_visual_refs, active_games)`.
        """
        enriched: list[dict[str, Any]] = []
        visual_refs: list[str] = []
        active_games: list[str] = []

        for raw_msg in messages:
            msg = dict(raw_msg)
            base_content = str(msg.get("content") or "")
            extra_notes: list[str] = []

            raw_images = msg.pop("_visual_artifacts", None) or ()
            for artifact in raw_images:
                if not isinstance(artifact, PendingImageArtifact):
                    continue
                if artifact.visual_ref and artifact.visual_ref not in visual_refs:
                    visual_refs.append(artifact.visual_ref)
                caption = artifact.precomputed_description or self._caption_native_artifact(
                    artifact
                )
                ref_note = f" (ref: {artifact.visual_ref})" if artifact.visual_ref else ""
                if caption:
                    extra_notes.append(
                        f"[用户发送图片 {artifact.name}{ref_note} 画面内容：{caption}]"
                    )
                else:
                    extra_notes.append(f"[用户发送图片 {artifact.name}{ref_note}]")

            perc_snap = msg.pop("_perception_snapshot", None)
            if isinstance(perc_snap, PerceptionSnapshot) and perc_snap.summary:
                game_label = (
                    f"（游戏/来源：{perc_snap.active_game}）"
                    if perc_snap.active_game
                    else ""
                )
                if perc_snap.active_game and perc_snap.active_game not in active_games:
                    active_games.append(perc_snap.active_game)
                extra_notes.append(
                    f"[共同观看的屏幕/游戏画面记录{game_label}：{perc_snap.summary}]"
                )

            if extra_notes:
                msg["content"] = "\n".join([base_content, *extra_notes]).strip()
            enriched.append(msg)

        return enriched, visual_refs, active_games

    def postprocess_visual_drafts(
        self,
        drafts: Sequence[MemoryDraft],
        *,
        visual_refs: Sequence[str],
        active_games: Sequence[str],
    ) -> list[MemoryDraft]:
        """Attach `visual_ref` vault pointers and `active_game` entity anchors to extracted drafts."""
        if not drafts:
            return []
        primary_ref = visual_refs[0] if visual_refs else ""
        games = [g for g in active_games if g]
        if not primary_ref and not games:
            return list(drafts)

        has_explicit_visual = any(
            str(d.kind or "").strip().lower() == "visual" for d in drafts
        )
        out: list[MemoryDraft] = []
        attached_ref = False

        for draft in drafts:
            kind_norm = str(draft.kind or "episodic").strip().lower()
            meta = unpack_system_tags(draft.topic_tags)
            eff_ref = meta.visual_ref
            eff_kind = draft.kind

            if primary_ref and not eff_ref:
                if kind_norm == "visual":
                    eff_ref = primary_ref
                    attached_ref = True
                elif not has_explicit_visual and not attached_ref and kind_norm == "episodic":
                    # When the window had an uploaded image and the LLM emitted `episodic`,
                    # bind the visual vault ref and tag it `visual` so visual recall & vault work.
                    eff_ref = primary_ref
                    eff_kind = "visual"
                    attached_ref = True

            eff_entities = list(draft.entities)
            if games and kind_norm in {"visual", "episodic", "relational"}:
                existing_lower = {e.casefold() for e in eff_entities}
                for game in games:
                    if game.casefold() not in existing_lower and len(eff_entities) < 10:
                        eff_entities.append(game)
                        existing_lower.add(game.casefold())

            packed_tags = (
                pack_system_tags(
                    meta.public_tags,
                    valid_until=meta.valid_until,
                    supersedes_ids=meta.supersedes_ids,
                    visual_ref=eff_ref,
                    consolidated_seq=meta.consolidated_seq,
                )
                if eff_ref != meta.visual_ref
                else draft.topic_tags
            )
            out.append(
                replace(
                    draft,
                    kind=eff_kind,
                    topic_tags=packed_tags,
                    entities=tuple(eff_entities),
                )
            )
        return out

    def _caption_native_artifact(self, artifact: PendingImageArtifact) -> str:
        raw_bytes = self._load_image_bytes(artifact)
        # 1. Explicit or configured VisionDescriber
        if raw_bytes is not None:
            try:
                if self._describer_factory is not None and self._vision_available():
                    describer = self._describer_factory()
                    desc = clean_text(
                        describer.describe(raw_bytes, MEMORY_IMAGE_CAPTION_PROMPT),
                        max_chars=450,
                    )
                    if desc:
                        return desc
            except Exception:
                logger.debug("custom vision describer failed on memory artifact", exc_info=True)

        # 2. Native multimodal `llm_adapter` (zero extra model config required!)
        if ChatVisionService.supports_native_images(self.llm_adapter):
            b64 = artifact.base64_data
            if not b64 and raw_bytes is not None:
                b64 = base64.b64encode(raw_bytes).decode("ascii")
            if b64:
                try:
                    multimodal_msgs = normalize_openai_messages(
                        [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": MEMORY_IMAGE_CAPTION_PROMPT},
                                    {
                                        "type": LOCAL_IMAGE_BLOCK_TYPE,
                                        "media_type": artifact.media_type,
                                        "name": artifact.name,
                                        "path": artifact.raw_path,
                                        "data": b64,
                                    },
                                ],
                            }
                        ],
                        supports_native_vision=True,
                    )
                    resp = self.llm_adapter.chat(
                        multimodal_msgs,
                        stream=False,
                        response_format={"type": "text"},
                    )
                    desc = clean_text(extract_response_text(resp), max_chars=450)
                    if desc:
                        return desc
                except Exception:
                    logger.debug("native multimodal captioning failed on memory artifact", exc_info=True)

        # 3. Configured fallback vision service (if available in runtime)
        if raw_bytes is not None and self._describer_factory is None:
            try:
                if self._vision_available():
                    describer = configured_vision_manager()
                    desc = clean_text(
                        describer.describe(raw_bytes, MEMORY_IMAGE_CAPTION_PROMPT),
                        max_chars=450,
                    )
                    if desc:
                        return desc
            except Exception:
                logger.debug("configured fallback vision captioning skipped", exc_info=True)

        return ""

    @staticmethod
    def _load_image_bytes(artifact: PendingImageArtifact) -> bytes | None:
        if artifact.base64_data:
            try:
                return base64.b64decode(artifact.base64_data, validate=True)
            except (binascii.Error, ValueError):
                pass
        if artifact.raw_path:
            try:
                p = Path(artifact.raw_path)
                if p.is_file():
                    return p.read_bytes()
            except OSError:
                pass
        return None


__all__ = [
    "DEFAULT_AMBIENT_PERCEPTION_TTL_SEC",
    "MEMORY_IMAGE_CAPTION_PROMPT",
    "PendingImageArtifact",
    "PerceptionSnapshot",
    "VisualMemoryBridge",
    "extract_message_visual_artifacts",
    "normalize_attachment_visual_ref",
    "parse_perception_block",
    "reinspect_visual_memory",
    "resolve_vault_attachment_path",
]
