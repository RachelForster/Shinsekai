"""Playwright-free Bilibili character voice compilation search and video ranking."""

from __future__ import annotations

import html
import re

import requests


BILIBILI_SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
BILIBILI_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"

DEFAULT_HTTP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_POSITIVE_VOICE_KEYWORDS = (
    "语音合集",
    "全语音",
    "台词合集",
    "角色语音",
    "原声",
    "干音",
    "提取",
    "语音",
    "台词",
    "对白",
    "ボイス",
    "セリフ",
    "voice",
)
_NEGATIVE_VOICE_KEYWORDS = (
    "鬼畜",
    "手书",
    "翻唱",
    "二创",
    "配音练习",
    "试配",
    "mad",
    "amv",
    "mmd",
    "ai翻唱",
    "ai语音",
)


def _strip_html(text: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", str(text or ""))).strip()


def _parse_bilibili_duration_seconds(raw: str) -> int:
    parts = [part.strip() for part in str(raw or "").split(":") if part.strip()]
    if not parts or not all(part.isdigit() for part in parts):
        return 0
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def _score_bilibili_video_item(item: dict, query: str) -> float:
    title = _strip_html(str(item.get("title") or ""))
    desc = _strip_html(str(item.get("description") or ""))
    lowered_title = title.casefold()
    lowered_query = query.casefold()
    duration = _parse_bilibili_duration_seconds(str(item.get("duration") or ""))
    if 0 < duration < 10:
        return -100.0

    score = 0.0
    query_tokens = [tok for tok in re.split(r"\s+", lowered_query) if tok]
    for token in query_tokens:
        if token in lowered_title:
            score += 18.0
        elif token in desc.casefold():
            score += 6.0

    for kw in _POSITIVE_VOICE_KEYWORDS:
        if kw in lowered_title:
            score += 12.0
    for kw in _NEGATIVE_VOICE_KEYWORDS:
        if kw in lowered_title and kw not in lowered_query:
            score -= 25.0

    if 20 <= duration <= 1800:
        score += 10.0
    elif duration > 3600:
        score -= 4.0

    play_count = item.get("play")
    if isinstance(play_count, int) and play_count > 1000:
        score += min(8.0, len(str(play_count)))
    return score


def search_bilibili_voice_urls(
    query: str,
    *,
    max_results: int = 1,
    timeout: float = 15.0,
) -> list[str]:
    """Search Bilibili public JSON search endpoint with visitor cookies (no Playwright needed)."""
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        return []
    if not any(kw in cleaned_query.casefold() for kw in ("语音", "台词", "对白", "voice", "ボイス", "セリフ")):
        search_keyword = f"{cleaned_query} 语音合集"
    else:
        search_keyword = cleaned_query

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
        else:
            session.get("https://www.bilibili.com/", timeout=timeout)

        resp = session.get(
            BILIBILI_SEARCH_URL,
            params={"search_type": "video", "keyword": search_keyword, "page": 1},
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

        ranked: list[tuple[float, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            bvid = str(item.get("bvid") or "").strip()
            if not bvid.startswith("BV"):
                continue
            item_score = _score_bilibili_video_item(item, cleaned_query)
            if item_score > -20.0:
                ranked.append((item_score, f"https://www.bilibili.com/video/{bvid}"))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [url for _score, url in ranked[: max(1, max_results)]]
    except (requests.RequestException, ValueError):
        return []
    finally:
        session.close()
