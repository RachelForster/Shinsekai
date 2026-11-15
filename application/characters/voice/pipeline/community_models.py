"""Non-blocking discovery of community pre-trained GPT-SoVITS character models (Bilibili, ModelScope, Hugging Face)."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import re
from typing import Any

import requests

from application.characters.voice.pipeline.bilibili_search import (
    BILIBILI_SEARCH_URL,
    BILIBILI_SPI_URL,
    DEFAULT_HTTP_UA,
    _strip_html,
)


HUGGINGFACE_MODELS_API_URL = "https://huggingface.co/api/models"
MODELSCOPE_MODELS_API_URL = "https://modelscope.cn/api/v1/dolphin/models"

_BVID_RE = re.compile(r"^BV[0-9A-Za-z]{10}$")
_REPO_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
_PAREN_SUFFIX_RE = re.compile(r"\s*[（(][^（）()]{1,24}[）)]\s*$")
_WHITESPACE_RE = re.compile(r"\s+")

_GSV_INDICATOR_RE = re.compile(
    r"gpt[\s._\-\u2010-\u2015\u2212/]*so[\s._\-\u2010-\u2015\u2212]*vits|(?<![a-z0-9])gsv(?![a-z0-9])",
    re.IGNORECASE,
)
_EXCLUDED_REPO_OWNERS = frozenset(
    {
        "lj1995",
        "rvc-boss",
        "svc-develop-team",
    }
)
_EXCLUDED_REPO_SLUGS = frozenset(
    {
        "gpt-sovits",
        "gpt-sovits-windows-package",
        "gpt-sovits-pretrained",
        "gpt_sovits",
    }
)
_TOKEN_STOPWORDS = frozenset(
    {
        "ai",
        "tts",
        "gsv",
        "gpt",
        "sovits",
        "gpt-sovits",
        "gptsovits",
        "vits",
        "rvc",
        "voice",
        "audio",
        "model",
        "models",
        "speech",
        "character",
        "anime",
        "game",
        "语音",
        "语音合集",
        "全语音",
        "台词",
        "台词合集",
        "对白",
        "原声",
        "干音",
        "模型",
        "整合包",
        "分享",
        "教程",
    }
)
_BILI_STRONG_RELEASE_KEYWORDS = (
    "模型分享",
    "模型发布",
    "模型开源",
    "权重分享",
    "模型公开",
    "音色分享",
    "开源",
    "自取",
    "网盘",
    "夸克",
    "百度网盘",
    "度盘",
    "蓝奏",
    "123盘",
    "下载",
    "ckpt",
    "pth",
    "huggingface",
    "modelscope",
    "魔搭",
    "抱脸",
)
_BILI_WEAK_RELEASE_KEYWORDS = (
    "分享",
    "发布",
    "公开",
    "权重",
    "置顶",
    "评论区",
)
_BILI_NOISE_KEYWORDS = (
    "翻唱",
    "ai翻唱",
    "鬼畜",
    "手书",
    "小剧场",
    "整活",
    "纯享",
    "配音练习",
    "读评论",
    "弱智吧",
    "安装教程",
    "部署教程",
    "保姆级教程",
    "零基础教程",
)


@dataclass(frozen=True, slots=True)
class CommunityVoiceModel:
    """Validated metadata for a public community-shared GPT-SoVITS character model."""

    platform: str
    title: str
    url: str
    author: str = ""
    summary: str = ""
    downloads: int = 0
    likes: int = 0
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "title": self.title,
            "url": self.url,
            "author": self.author,
            "summary": self.summary,
            "downloads": self.downloads,
            "likes": self.likes,
            "score": round(self.score, 2),
        }


def _clean_text(raw: Any, *, max_len: int = 140) -> str:
    cleaned = _WHITESPACE_RE.sub(" ", _strip_html(str(raw or ""))).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[: max_len - 1].rstrip()}…"


def _is_valid_repo_segment(segment: str) -> bool:
    return segment not in {".", ".."} and bool(_REPO_SEGMENT_RE.fullmatch(segment))


def _extract_character_tokens(character_name: str, aliases: Sequence[str] = ()) -> tuple[str, ...]:
    raw_candidates: list[str] = []
    primary = str(character_name or "").strip()
    if primary:
        raw_candidates.append(primary)
        stripped = _PAREN_SUFFIX_RE.sub("", primary).strip()
        if stripped and stripped != primary:
            raw_candidates.append(stripped)
        for sep in ("·", "・"):
            if sep in stripped:
                given = stripped.split(sep, 1)[0].strip()
                if len(given) >= 3:
                    raw_candidates.append(given)

    for alias in aliases:
        cleaned_alias = _PAREN_SUFFIX_RE.sub("", str(alias or "").strip()).strip()
        if cleaned_alias:
            raw_candidates.append(cleaned_alias)

    deduped: list[str] = []
    seen_lower: set[str] = set()
    for item in raw_candidates:
        norm = _WHITESPACE_RE.sub(" ", item).strip()
        lowered = norm.casefold()
        if not norm or lowered in seen_lower or lowered in _TOKEN_STOPWORDS:
            continue
        if norm.isascii() and len(re.sub(r"[^A-Za-z0-9]", "", norm)) < 2:
            continue
        seen_lower.add(lowered)
        deduped.append(norm)
    return tuple(deduped)


def _split_camel_case(text: str) -> str:
    step1 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", step1)


def _contains_character_token(haystack: str, token: str) -> bool:
    if not haystack or not token:
        return False
    if not token.isascii():
        return token.casefold() in haystack.casefold()

    parts = [re.escape(part) for part in re.split(r"[\s._-]+", token.strip()) if part]
    if not parts:
        return False
    pattern = r"[\s._-]*".join(parts)
    normalized_haystack = _split_camel_case(haystack)
    return bool(re.search(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", normalized_haystack, flags=re.IGNORECASE))


def _matched_character_tokens(texts: Sequence[str], tokens: Sequence[str]) -> list[str]:
    combined = " \n ".join(t for t in texts if t)
    return [tok for tok in tokens if _contains_character_token(combined, tok)]


def _has_gsv_indicator(text: str) -> bool:
    return bool(text and _GSV_INDICATOR_RE.search(text))


def _safe_nonneg_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _popularity_bonus(downloads: int, likes: int) -> float:
    bonus = 0.0
    if downloads > 0:
        bonus += min(8.0, math.log10(downloads + 1) * 2.2)
    if likes > 0:
        bonus += min(6.0, math.log10(likes + 1) * 2.5)
    return bonus


def _search_modelscope_models(
    search_terms: Sequence[str],
    char_tokens: Sequence[str],
    *,
    timeout: float,
) -> list[CommunityVoiceModel]:
    if not search_terms or not char_tokens:
        return []
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_HTTP_UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    found: dict[str, CommunityVoiceModel] = {}
    try:
        for term in search_terms[:2]:
            resp = session.put(
                MODELSCOPE_MODELS_API_URL,
                json={
                    "PageSize": 12,
                    "PageNumber": 1,
                    "SortBy": "Default",
                    "Target": "",
                    "SingleCriterion": [],
                    "Name": f"{term} GPT-SoVITS",
                },
                timeout=timeout,
            )
            if not resp.ok:
                continue
            payload = resp.json()
            if not isinstance(payload, dict):
                continue
            models = (((payload.get("Data") or {}).get("Model") or {}).get("Models")) or []
            if not isinstance(models, list):
                continue

            for item in models:
                if not isinstance(item, dict):
                    continue
                owner = str(item.get("Path") or "").strip()
                slug = str(item.get("Name") or "").strip()
                if not _is_valid_repo_segment(owner) or not _is_valid_repo_segment(slug):
                    continue
                if owner.casefold() in _EXCLUDED_REPO_OWNERS or slug.casefold() in _EXCLUDED_REPO_SLUGS:
                    continue

                zh_name = _clean_text(item.get("ChineseName"), max_len=80)
                desc = _clean_text(item.get("Description"), max_len=140)
                raw_tags = item.get("Tags")
                tags_str = ", ".join(str(t) for t in raw_tags[:6] if isinstance(t, str)) if isinstance(raw_tags, list) else ""
                repo_id = f"{owner}/{slug}"
                combined_meta = f"{repo_id} {zh_name} {desc} {tags_str}"

                if not _has_gsv_indicator(combined_meta):
                    continue
                matched = _matched_character_tokens((zh_name, slug, desc), char_tokens)
                if not matched:
                    continue

                score = 56.0  # Direct weight repository bonus
                if _matched_character_tokens((zh_name, slug), char_tokens):
                    score += 22.0
                else:
                    score += 10.0
                if any(kw in combined_meta.casefold() for kw in ("gpt-sovits", "gpt_sovits", "gptsovits")):
                    score += 8.0

                downloads = _safe_nonneg_int(item.get("Downloads"))
                likes = _safe_nonneg_int(item.get("Likes"))
                score += _popularity_bonus(downloads, likes)

                url = f"https://modelscope.cn/models/{owner}/{slug}"
                title = f"{zh_name} ({repo_id})" if zh_name and zh_name.casefold() != slug.casefold() else repo_id
                candidate = CommunityVoiceModel(
                    platform="modelscope",
                    title=title,
                    url=url,
                    author=owner,
                    summary=desc or tags_str,
                    downloads=downloads,
                    likes=likes,
                    score=score,
                )
                prev = found.get(url)
                if prev is None or candidate.score > prev.score:
                    found[url] = candidate

            if found:
                break
        return list(found.values())
    except (requests.RequestException, ValueError):
        return []
    finally:
        session.close()


def _search_huggingface_models(
    ascii_terms: Sequence[str],
    char_tokens: Sequence[str],
    *,
    timeout: float,
) -> list[CommunityVoiceModel]:
    if not ascii_terms or not char_tokens:
        return []
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_HTTP_UA, "Accept": "application/json"})
    found: dict[str, CommunityVoiceModel] = {}
    try:
        for term in ascii_terms[:2]:
            resp = session.get(
                HUGGINGFACE_MODELS_API_URL,
                params={"search": f"{term} GPT-SoVITS", "limit": 12},
                timeout=timeout,
            )
            if not resp.ok:
                continue
            items = resp.json()
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                if bool(item.get("private")) or bool(item.get("disabled")):
                    continue
                repo_id = str(item.get("id") or item.get("modelId") or "").strip()
                if "/" not in repo_id:
                    continue
                owner, slug = repo_id.split("/", 1)
                if not _is_valid_repo_segment(owner) or not _is_valid_repo_segment(slug):
                    continue
                if owner.casefold() in _EXCLUDED_REPO_OWNERS or slug.casefold() in _EXCLUDED_REPO_SLUGS:
                    continue

                raw_tags = item.get("tags")
                tags_list = [str(t) for t in raw_tags if isinstance(t, str)] if isinstance(raw_tags, list) else []
                clean_tags = [
                    t for t in tags_list
                    if not t.startswith(("base_model:", "dataset:", "region:", "license:"))
                ]
                tags_text = ", ".join(clean_tags[:5])
                combined_meta = f"{repo_id} {' '.join(tags_list)}"

                if not _has_gsv_indicator(combined_meta):
                    continue
                if not _matched_character_tokens((slug, " ".join(clean_tags)), char_tokens):
                    continue

                score = 54.0  # Direct weight repository bonus
                if _matched_character_tokens((slug,), char_tokens):
                    score += 22.0
                else:
                    score += 8.0
                if any(kw in slug.casefold() for kw in ("gpt-sovits", "gpt_sovits", "gptsovits")):
                    score += 8.0

                downloads = _safe_nonneg_int(item.get("downloads"))
                likes = _safe_nonneg_int(item.get("likes"))
                score += _popularity_bonus(downloads, likes)

                url = f"https://huggingface.co/{owner}/{slug}"
                candidate = CommunityVoiceModel(
                    platform="huggingface",
                    title=repo_id,
                    url=url,
                    author=owner,
                    summary=_clean_text(tags_text, max_len=120),
                    downloads=downloads,
                    likes=likes,
                    score=score,
                )
                prev = found.get(url)
                if prev is None or candidate.score > prev.score:
                    found[url] = candidate

            if found:
                break
        return list(found.values())
    except (requests.RequestException, ValueError):
        return []
    finally:
        session.close()


def _search_bilibili_models(
    primary_term: str,
    char_tokens: Sequence[str],
    query_hint: str,
    *,
    timeout: float,
) -> list[CommunityVoiceModel]:
    if not primary_term or not char_tokens:
        return []
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_HTTP_UA,
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
        }
    )
    try:
        spi_resp = session.get(BILIBILI_SPI_URL, timeout=timeout)
        if spi_resp.ok:
            spi_data = (spi_resp.json() or {}).get("data") or {}
            if spi_data.get("b_3"):
                session.cookies.set("buvid3", str(spi_data["b_3"]), domain=".bilibili.com")
            if spi_data.get("b_4"):
                session.cookies.set("buvid4", str(spi_data["b_4"]), domain=".bilibili.com")

        resp = session.get(
            BILIBILI_SEARCH_URL,
            params={"search_type": "video", "keyword": f"{primary_term} GPT-SoVITS 模型", "page": 1},
            timeout=timeout,
        )
        if not resp.ok:
            return []
        payload = resp.json()
        if not isinstance(payload, dict) or payload.get("code") != 0:
            return []
        items = ((payload.get("data") or {}).get("result")) or []
        if not isinstance(items, list):
            return []

        results: list[CommunityVoiceModel] = []
        seen_urls: set[str] = set()
        hint_tokens = [
            tok
            for tok in re.split(r"\s+", str(query_hint or "").strip())
            if len(tok) >= 2 and tok.casefold() not in _TOKEN_STOPWORDS
        ]

        for item in items[:15]:
            if not isinstance(item, dict):
                continue
            bvid = str(item.get("bvid") or "").strip()
            if not _BVID_RE.fullmatch(bvid):
                continue
            url = f"https://www.bilibili.com/video/{bvid}"
            if url in seen_urls:
                continue

            title = _clean_text(item.get("title"), max_len=100)
            desc = _clean_text(item.get("description"), max_len=140)
            author = _clean_text(item.get("author"), max_len=48)
            combined = f"{title} {desc}"
            lowered_title = title.casefold()
            lowered_combined = combined.casefold()

            if not title or not _has_gsv_indicator(combined):
                continue
            if not _matched_character_tokens((title, desc), char_tokens):
                continue

            has_strong_release = any(kw in lowered_combined for kw in _BILI_STRONG_RELEASE_KEYWORDS)
            has_weak_release = any(kw in lowered_combined for kw in _BILI_WEAK_RELEASE_KEYWORDS)
            has_noise = any(kw in lowered_title for kw in _BILI_NOISE_KEYWORDS)

            if not has_strong_release and not has_weak_release:
                continue
            if has_noise and not has_strong_release:
                continue

            score = 48.0
            if _matched_character_tokens((title,), char_tokens):
                score += 20.0
            else:
                score += 6.0
            if has_strong_release:
                score += 12.0
            if any(kw in lowered_title for kw in ("gpt-sovits", "gpt_sovits", "gptsovits")):
                score += 6.0
            if has_noise:
                score -= 10.0
            for hint in hint_tokens:
                if hint.casefold() in lowered_combined:
                    score += 3.0

            plays = _safe_nonneg_int(item.get("play"))
            favorites = _safe_nonneg_int(item.get("favorites"))
            score += _popularity_bonus(plays, favorites)

            seen_urls.add(url)
            results.append(
                CommunityVoiceModel(
                    platform="bilibili",
                    title=title,
                    url=url,
                    author=author,
                    summary=desc,
                    downloads=plays,
                    likes=favorites,
                    score=score,
                )
            )
        return results
    except (requests.RequestException, ValueError):
        return []
    finally:
        session.close()


def search_community_gsv_models(
    character_name: str,
    query: str = "",
    *,
    aliases: Sequence[str] = (),
    max_results: int = 5,
    timeout: float = 6.0,
) -> list[dict[str, Any]]:
    """Search Bilibili, ModelScope, and Hugging Face for existing character GPT-SoVITS models.

    Never raises on network, HTTP, or JSON failures so voice preparation stays non-blocking.
    """
    cleaned_name = str(character_name or "").strip()
    if not cleaned_name or max_results <= 0:
        return []

    char_tokens = _extract_character_tokens(cleaned_name, aliases)
    if not char_tokens:
        return []

    ascii_terms = [tok for tok in char_tokens if tok.isascii()]
    modelscope_terms: list[str] = [char_tokens[0]]
    if ascii_terms and ascii_terms[0].casefold() != char_tokens[0].casefold():
        modelscope_terms.append(ascii_terms[0])

    all_candidates: list[CommunityVoiceModel] = []
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="gsv-community") as pool:
        futures = [
            pool.submit(_search_modelscope_models, modelscope_terms, char_tokens, timeout=timeout),
            pool.submit(_search_bilibili_models, char_tokens[0], char_tokens, query, timeout=timeout),
        ]
        if ascii_terms:
            futures.append(
                pool.submit(_search_huggingface_models, ascii_terms, char_tokens, timeout=timeout)
            )
        for fut in futures:
            try:
                all_candidates.extend(fut.result())
            except Exception:
                continue

    deduped_by_url: dict[str, CommunityVoiceModel] = {}
    for cand in all_candidates:
        prev = deduped_by_url.get(cand.url)
        if prev is None or cand.score > prev.score:
            deduped_by_url[cand.url] = cand

    ranked = sorted(deduped_by_url.values(), key=lambda item: item.score, reverse=True)
    return [item.to_dict() for item in ranked[:max_results]]
