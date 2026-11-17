"""Heuristic + tag/filename-prefix smart outfit grouping for character sprites."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Any

from config.character_assets import get_character_assets, get_character_avatar_type
from config.schema import DEFAULT_SPRITE_GROUP
from config.sprite_files import sprite_field
from config.sprite_groups import (
    normalize_sprite_group,
    normalize_sprite_group_list,
    raw_sprite_group,
    sprite_group_of,
)
from sdk.asset_tags import tag_contents

_RESERVED_SUBDIRS = frozenset(
    {"avatars", "avatar-voices", "transitions", "mouth-sync"}
)

# Ordered from more specific outfits to general casual wear.
_OUTFIT_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "泳装",
        (
            "泳装",
            "泳衣",
            "比基尼",
            "死库水",
            "水着",
            "ビキニ",
            "スク水",
            "swimsuit",
            "swimwear",
            "bikini",
            "swim",
        ),
    ),
    (
        "睡衣",
        (
            "睡衣",
            "睡裙",
            "家居服",
            "パジャマ",
            "ネグリジェ",
            "部屋着",
            "pajama",
            "pajamas",
            "pyjama",
            "nightgown",
            "sleepwear",
            "homewear",
        ),
    ),
    (
        "校服",
        (
            "校服",
            "制服",
            "水手服",
            "学生服",
            "セーラー",
            "school_uniform",
            "school-uniform",
            "seifuku",
            "uniform",
            "sailor",
            "school",
        ),
    ),
    (
        "礼服",
        (
            "晚礼服",
            "礼服",
            "婚纱",
            "洋装",
            "ドレス",
            "ウェディング",
            "gown",
            "wedding",
            "formal",
            "dress",
        ),
    ),
    (
        "运动服",
        (
            "运动服",
            "体操服",
            "运动装",
            "训练服",
            "ジャージ",
            "ブルマ",
            "sportswear",
            "tracksuit",
            "athletic",
            "gym",
            "sport",
        ),
    ),
    (
        "女仆装",
        (
            "女仆装",
            "女仆",
            "メイド",
            "maid",
        ),
    ),
    (
        "和服",
        (
            "和服",
            "浴衣",
            "巫女服",
            "巫女",
            "着物",
            "ゆかた",
            "kimono",
            "yukata",
            "miko",
        ),
    ),
    (
        "工作服",
        (
            "工作服",
            "白大褂",
            "职业装",
            "护士服",
            "战斗服",
            "铠甲",
            "西装",
            "スーツ",
            "白衣",
            "アーマー",
            "labcoat",
            "armor",
            "battle",
            "nurse",
            "suit",
        ),
    ),
    (
        "冬装",
        (
            "冬装",
            "羽绒服",
            "大衣",
            "毛衣",
            "コート",
            "セーター",
            "冬服",
            "winter",
            "coat",
            "sweater",
        ),
    ),
    (
        "夏装",
        (
            "夏装",
            "连衣裙",
            "夏服",
            "ワンピース",
            "summer",
            "sundress",
        ),
    ),
    (
        "私服",
        (
            "私服",
            "常服",
            "便服",
            "日常服",
            "casual",
            "streetwear",
            "everyday",
        ),
    ),
)

_EMOTION_NOISE_TOKENS = frozenset(
    {
        "normal",
        "default",
        "idle",
        "smile",
        "happy",
        "joy",
        "laugh",
        "grin",
        "sad",
        "cry",
        "tears",
        "angry",
        "mad",
        "rage",
        "shy",
        "blush",
        "embarrassed",
        "surprise",
        "surprised",
        "shock",
        "serious",
        "think",
        "thinking",
        "wink",
        "sleepy",
        "tired",
        "confused",
        "smug",
        "fear",
        "scared",
        "neutral",
        "face",
        "expr",
        "expression",
        "sprite",
        "stand",
        "pose",
        "微笑",
        "开心",
        "高兴",
        "大笑",
        "难过",
        "伤心",
        "哭泣",
        "流泪",
        "生气",
        "愤怒",
        "害羞",
        "脸红",
        "惊讶",
        "吃惊",
        "思考",
        "严肃",
        "得意",
        "困惑",
        "疑惑",
        "害怕",
        "普通",
        "默认",
        "平静",
        "待机",
    }
)


def _match_keyword_group(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    tokens = set(re.split(r"[^0-9a-zA-Z\u4e00-\u9fff\u3040-\u30ff]+", lowered))
    for group_name, keywords in _OUTFIT_KEYWORD_RULES:
        for kw in keywords:
            kw_low = kw.lower()
            if re.fullmatch(r"[a-z0-9_-]+", kw_low):
                if kw_low in tokens or f"_{kw_low}_" in f"_{lowered}_":
                    return group_name
            elif kw_low in lowered:
                return group_name
    return None


def _extract_subfolder_group(sprite_path: str, sprite_prefix: str) -> str | None:
    if not sprite_path:
        return None
    parts = [p for p in Path(sprite_path.replace("\\", "/")).parts if p]
    if len(parts) < 2:
        return None
    parent = parts[-2].strip()
    if not parent or parent.lower() in _RESERVED_SUBDIRS:
        return None
    if sprite_prefix and parent.lower() == sprite_prefix.strip().lower():
        return None
    if parent.lower() in {"sprite", "sprites", "images", "data"}:
        return None
    matched = _match_keyword_group(parent)
    return matched or parent


def _extract_stem_prefix_candidate(
    sprite_path: str,
    character_name: str,
    sprite_prefix: str,
) -> str | None:
    if not sprite_path:
        return None
    stem = Path(sprite_path.replace("\\", "/")).stem.strip()
    if not stem:
        return None
    raw_tokens = [
        tok.strip()
        for tok in re.split(r"[\s_\-\.]+", stem)
        if tok.strip()
    ]
    ignore = {
        str(character_name or "").strip().lower(),
        str(sprite_prefix or "").strip().lower(),
    }
    filtered: list[str] = []
    for tok in raw_tokens:
        low = tok.lower()
        if low in ignore:
            continue
        if low in _EMOTION_NOISE_TOKENS:
            break
        if re.fullmatch(r"\d+", tok):
            # Keep leading costume numeric slot like "costume01" or "01_smile" only if followed by emotion
            if not filtered and len(raw_tokens) >= 2 and any(
                t.lower() in _EMOTION_NOISE_TOKENS for t in raw_tokens[1:]
            ):
                filtered.append(f"服装{int(tok)}")
            break
        m = re.fullmatch(r"([a-zA-Z\u4e00-\u9fff\u3040-\u30ff]+?)(\d+)", tok)
        if m and m.group(1).lower() in {"outfit", "costume", "dress", "cloth", "form", "ver", "style", "服装", "衣装", "造型"}:
            filtered.append(f"服装{int(m.group(2))}")
            break
        filtered.append(tok)
        if len(filtered) >= 2:
            break

    if not filtered:
        return None
    candidate = "_".join(filtered)
    if candidate.lower() in _EMOTION_NOISE_TOKENS or len(candidate) > 24:
        return None
    return _match_keyword_group(candidate) or candidate


def analyze_character_sprite_groups(
    character: Any,
    *,
    avatar_type: str | None = None,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    """Infer outfit groups for ``character`` from tags, subfolders, and stem prefixes."""
    resolved_avatar = (
        get_character_avatar_type(character)
        if avatar_type is None
        else str(avatar_type or "").strip().lower() or "static"
    )
    assets = get_character_assets(character, resolved_avatar)
    sprites = list(assets.sprites or [])
    tags = tag_contents(assets.emotion_tags or "", len(sprites))
    char_name = str(getattr(character, "name", "") if not isinstance(character, dict) else character.get("name", ""))
    sprite_prefix = str(
        getattr(character, "sprite_prefix", "")
        if not isinstance(character, dict)
        else character.get("sprite_prefix", "")
    )

    proposed: dict[int, str] = {}
    unresolved_stem_candidates: dict[int, str] = {}

    for idx, sprite in enumerate(sprites):
        existing_explicit = raw_sprite_group(sprite)
        if existing_explicit and not overwrite_existing:
            proposed[idx] = existing_explicit
            continue

        sprite_path = str(sprite_field(sprite, "path", "") or "")
        tag_text = tags[idx] if idx < len(tags) else ""

        # 1. Explicit outfit keyword in emotion tag
        matched = _match_keyword_group(tag_text)
        if matched:
            proposed[idx] = matched
            continue

        # 2. Subfolder name under character sprite root
        subfolder = _extract_subfolder_group(sprite_path, sprite_prefix)
        if subfolder:
            proposed[idx] = normalize_sprite_group(subfolder)
            continue

        # 3. Explicit outfit keyword in filename stem
        stem = Path(sprite_path.replace("\\", "/")).stem if sprite_path else ""
        matched_stem = _match_keyword_group(stem)
        if matched_stem:
            proposed[idx] = matched_stem
            continue

        # 4. Candidate stem prefix for multi-cluster check
        prefix_candidate = _extract_stem_prefix_candidate(sprite_path, char_name, sprite_prefix)
        if prefix_candidate:
            unresolved_stem_candidates[idx] = prefix_candidate

    if unresolved_stem_candidates:
        cluster_members: dict[str, list[int]] = defaultdict(list)
        for idx, cand in unresolved_stem_candidates.items():
            cluster_members[cand].append(idx)
        viable_clusters = {
            cand: members
            for cand, members in cluster_members.items()
            if len(members) >= 2
        }
        # Activate stem-prefix clusters if there are >= 2 distinct clusters OR
        # at least one keyword/subfolder group already exists alongside a multi-file stem cluster.
        if len(viable_clusters) >= 2 or (viable_clusters and bool(proposed)):
            for cand, members in viable_clusters.items():
                norm_cand = normalize_sprite_group(cand)
                for idx in members:
                    proposed[idx] = norm_cand

    final_assignments: dict[int, str] = {}
    changed_count = 0
    grouped_indices: dict[str, list[int]] = defaultdict(list)

    for idx, sprite in enumerate(sprites):
        target_group = normalize_sprite_group(proposed.get(idx, DEFAULT_SPRITE_GROUP))
        current_group = sprite_group_of(sprite)
        final_assignments[idx] = target_group
        grouped_indices[target_group].append(idx)
        if target_group != current_group:
            changed_count += 1

    existing_order = (
        getattr(character, "sprite_groups", None)
        if not isinstance(character, dict)
        else character.get("sprite_groups")
    )
    ordered_group_names = normalize_sprite_group_list(
        [DEFAULT_SPRITE_GROUP, *(existing_order or []), *grouped_indices.keys()]
    )
    groups_summary = [
        {
            "group": group_name,
            "count": len(grouped_indices.get(group_name, ())),
            "spriteIndices": list(grouped_indices.get(group_name, ())),
        }
        for group_name in ordered_group_names
        if grouped_indices.get(group_name)
    ]

    return {
        "characterName": char_name,
        "avatarType": resolved_avatar,
        "groups": groups_summary,
        "spriteGroups": [
            g["group"] for g in groups_summary if g["group"] != DEFAULT_SPRITE_GROUP
        ],
        "assignments": {str(idx): grp for idx, grp in final_assignments.items()},
        "changedCount": changed_count,
    }
