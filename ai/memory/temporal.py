"""Zero-latency temporal anchor and relative/explicit date expression parser."""

from __future__ import annotations

import calendar
from datetime import datetime, time as dt_time, timedelta
import re
import time
from typing import Any

_CN_DIGITS: dict[str, int] = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "俩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_ISO_FULL_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2}|19\d{2})\s*[-/年.]\s*(?P<month>1[0-2]|0?[1-9])\s*[-/月.]\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*日?(?!\d)"
)
_ISO_YEAR_MONTH_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2}|19\d{2})\s*[-年/]\s*(?P<month>1[0-2]|0?[1-9])\s*月?(?![\d日号])"
)
_CN_MONTH_DAY_RE = re.compile(
    r"(?<!\d)(?P<month>1[0-2]|0?[1-9])\s*月\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*[日号]"
)
_DAYS_AGO_CN_RE = re.compile(r"(?P<num>\d+|[一二两俩三四五六七八九十]{1,2})\s*天(?:之)?前")
_DAYS_LATER_CN_RE = re.compile(r"(?P<num>\d+|[一二两俩三四五六七八九十]{1,2})\s*天(?:之)?后")
_WEEKS_AGO_CN_RE = re.compile(
    r"(?P<num>\d+|[一二两俩三四五六七八九十]{1,2})\s*个?(?:周|星期|礼拜)(?:之)?前"
)
_MONTHS_AGO_CN_RE = re.compile(
    r"(?P<num>\d+|[一二两俩三四五六七八九十]{1,2})\s*个?月(?:之)?前"
)
_DAYS_AGO_EN_RE = re.compile(r"\b(?P<num>\d+)\s+days?\s+ago\b", re.IGNORECASE)
_WEEKS_AGO_EN_RE = re.compile(r"\b(?P<num>\d+)\s+weeks?\s+ago\b", re.IGNORECASE)
_MONTHS_AGO_EN_RE = re.compile(r"\b(?P<num>\d+)\s+months?\s+ago\b", re.IGNORECASE)


def _parse_small_number(raw: str) -> int | None:
    token = str(raw or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token in _CN_DIGITS:
        return _CN_DIGITS[token]
    if len(token) == 2 and token[0] == "十" and token[1] in _CN_DIGITS:
        return 10 + _CN_DIGITS[token[1]]
    if len(token) == 2 and token[1] == "十" and token[0] in _CN_DIGITS:
        return _CN_DIGITS[token[0]] * 10
    return None


def _day_bounds(dt: datetime) -> tuple[float, float]:
    start = datetime.combine(dt.date(), dt_time.min, tzinfo=dt.tzinfo)
    end = datetime.combine(dt.date(), dt_time(23, 59, 59, 999999), tzinfo=dt.tzinfo)
    return (start.timestamp(), end.timestamp())


def _month_bounds(year: int, month: int, tzinfo: Any = None) -> tuple[float, float]:
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=tzinfo)
    end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=tzinfo)
    return (start.timestamp(), end.timestamp())


def _shift_months(year: int, month: int, delta_months: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta_months
    return (total // 12, (total % 12) + 1)


def parse_iso_or_epoch(value: Any) -> float | None:
    """Parse an epoch timestamp or ISO/date string into epoch seconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        if num <= 0:
            return None
        return num / 1000.0 if num > 1e11 else num

    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        num = float(raw)
        if num > 0:
            return num / 1000.0 if num > 1e11 else num
    except ValueError:
        pass

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed_dt = datetime.fromisoformat(normalized)
        return parsed_dt.timestamp()
    except ValueError:
        pass

    match_full = _ISO_FULL_DATE_RE.search(raw)
    if match_full:
        try:
            dt = datetime(
                int(match_full.group("year")),
                int(match_full.group("month")),
                int(match_full.group("day")),
                12,
                0,
                0,
            )
            return dt.timestamp()
        except ValueError:
            return None
    return None


def parse_query_time_range(
    text: str,
    *,
    now_ts: float | None = None,
) -> tuple[float | None, float | None]:
    """Extract `(event_from, event_to)` epoch bounds from natural-language text."""
    query = str(text or "").strip()
    if not query:
        return (None, None)

    effective_now = float(now_ts) if now_ts is not None and now_ts > 0 else time.time()
    anchor = datetime.fromtimestamp(effective_now)
    lowered = query.casefold()

    # 1. Explicit YYYY-MM-DD / YYYY年M月D日
    m_full = _ISO_FULL_DATE_RE.search(query)
    if m_full:
        try:
            target = datetime(
                int(m_full.group("year")),
                int(m_full.group("month")),
                int(m_full.group("day")),
                tzinfo=anchor.tzinfo,
            )
            return _day_bounds(target)
        except ValueError:
            pass

    # 2. Explicit M月D日 (without year)
    m_md = _CN_MONTH_DAY_RE.search(query)
    if m_md:
        month = int(m_md.group("month"))
        day = int(m_md.group("day"))
        for candidate_year in (anchor.year, anchor.year - 1):
            try:
                candidate = datetime(candidate_year, month, day, tzinfo=anchor.tzinfo)
            except ValueError:
                continue
            if candidate_year == anchor.year and candidate.date() > (anchor + timedelta(days=45)).date():
                try:
                    prev = datetime(anchor.year - 1, month, day, tzinfo=anchor.tzinfo)
                    return _day_bounds(prev)
                except ValueError:
                    pass
            return _day_bounds(candidate)

    # 3. Explicit YYYY-MM / YYYY年M月
    m_ym = _ISO_YEAR_MONTH_RE.search(query)
    if m_ym:
        return _month_bounds(
            int(m_ym.group("year")),
            int(m_ym.group("month")),
            tzinfo=anchor.tzinfo,
        )

    # 4. Specific multi-day relative expressions (checked before single-char substrings)
    if "大前天" in query:
        return _day_bounds(anchor - timedelta(days=3))
    if "前天" in query or "一昨日" in query or "day before yesterday" in lowered:
        return _day_bounds(anchor - timedelta(days=2))
    if "昨天" in query or "昨日" in query or "昨晚" in query or re.search(r"\byesterday\b", lowered):
        return _day_bounds(anchor - timedelta(days=1))
    if "后天" in query or "明後日" in query or "day after tomorrow" in lowered:
        return _day_bounds(anchor + timedelta(days=2))
    if "明天" in query or "明日" in query or "明早" in query or "明晚" in query or re.search(r"\btomorrow\b", lowered):
        return _day_bounds(anchor + timedelta(days=1))
    if "刚才" in query or "刚刚" in query or "さっき" in query or re.search(r"\bjust now\b", lowered):
        return (effective_now - 4 * 3600.0, effective_now)
    if "今天" in query or "今日" in query or "今晚" in query or "今早" in query or re.search(r"\btoday\b|\btonight\b", lowered):
        return _day_bounds(anchor)

    # 5. N days / weeks / months ago or later
    m_days_ago = _DAYS_AGO_CN_RE.search(query) or _DAYS_AGO_EN_RE.search(query)
    if m_days_ago:
        n = _parse_small_number(m_days_ago.group("num"))
        if n is not None and 0 < n <= 3650:
            return _day_bounds(anchor - timedelta(days=n))

    m_days_later = _DAYS_LATER_CN_RE.search(query)
    if m_days_later:
        n = _parse_small_number(m_days_later.group("num"))
        if n is not None and 0 < n <= 3650:
            return _day_bounds(anchor + timedelta(days=n))

    if "前几天" in query or "几天前" in query or "a few days ago" in lowered:
        start_ts, _ = _day_bounds(anchor - timedelta(days=7))
        _, end_ts = _day_bounds(anchor - timedelta(days=1))
        return (start_ts, end_ts)

    if "半个月前" in query:
        start_ts, _ = _day_bounds(anchor - timedelta(days=18))
        _, end_ts = _day_bounds(anchor - timedelta(days=12))
        return (start_ts, end_ts)

    m_weeks_ago = _WEEKS_AGO_CN_RE.search(query) or _WEEKS_AGO_EN_RE.search(query)
    if m_weeks_ago:
        n = _parse_small_number(m_weeks_ago.group("num"))
        if n is not None and 0 < n <= 520:
            center = anchor - timedelta(days=7 * n)
            start_ts, _ = _day_bounds(center - timedelta(days=3))
            _, end_ts = _day_bounds(center + timedelta(days=3))
            return (start_ts, end_ts)

    if any(tok in query for tok in ("上周", "上礼拜", "上星期", "先週")) or re.search(r"\blast week\b", lowered):
        this_monday = anchor - timedelta(days=anchor.weekday())
        last_monday = this_monday - timedelta(days=7)
        last_sunday = this_monday - timedelta(days=1)
        start_ts, _ = _day_bounds(last_monday)
        _, end_ts = _day_bounds(last_sunday)
        return (start_ts, end_ts)

    if any(tok in query for tok in ("这周", "本周", "这礼拜", "这星期", "今週")) or re.search(r"\bthis week\b", lowered):
        this_monday = anchor - timedelta(days=anchor.weekday())
        this_sunday = this_monday + timedelta(days=6)
        start_ts, _ = _day_bounds(this_monday)
        _, end_ts = _day_bounds(this_sunday)
        return (start_ts, end_ts)

    if any(tok in query for tok in ("下周", "下礼拜", "下星期", "来週")) or re.search(r"\bnext week\b", lowered):
        this_monday = anchor - timedelta(days=anchor.weekday())
        next_monday = this_monday + timedelta(days=7)
        next_sunday = next_monday + timedelta(days=6)
        start_ts, _ = _day_bounds(next_monday)
        _, end_ts = _day_bounds(next_sunday)
        return (start_ts, end_ts)

    m_months_ago = _MONTHS_AGO_CN_RE.search(query) or _MONTHS_AGO_EN_RE.search(query)
    if m_months_ago:
        n = _parse_small_number(m_months_ago.group("num"))
        if n is not None and 0 < n <= 120:
            y, m = _shift_months(anchor.year, anchor.month, -n)
            return _month_bounds(y, m, tzinfo=anchor.tzinfo)

    if any(tok in query for tok in ("上个月", "上月", "先月")) or re.search(r"\blast month\b", lowered):
        y, m = _shift_months(anchor.year, anchor.month, -1)
        return _month_bounds(y, m, tzinfo=anchor.tzinfo)

    if any(tok in query for tok in ("下个月", "下月", "来月")) or re.search(r"\bnext month\b", lowered):
        y, m = _shift_months(anchor.year, anchor.month, 1)
        return _month_bounds(y, m, tzinfo=anchor.tzinfo)

    if "去年" in query or "昨年" in query or re.search(r"\blast year\b", lowered):
        prev_y = anchor.year - 1
        start = datetime(prev_y, 1, 1, 0, 0, 0, tzinfo=anchor.tzinfo).timestamp()
        end = datetime(prev_y, 12, 31, 23, 59, 59, 999999, tzinfo=anchor.tzinfo).timestamp()
        return (start, end)

    return (None, None)


def resolve_event_timestamp(
    raw_value: Any,
    *,
    anchor_ts: float | None = None,
    anchor_iso: str = "",
) -> float | None:
    """Resolve an extracted absolute or relative `event_time` value to epoch seconds."""
    direct = parse_iso_or_epoch(raw_value)
    if direct is not None:
        return direct
    if raw_value is None:
        return None
    text = str(raw_value or "").strip()
    if not text:
        return None

    effective_anchor = anchor_ts
    if effective_anchor is None or effective_anchor <= 0:
        effective_anchor = parse_iso_or_epoch(anchor_iso) or time.time()

    start_ts, end_ts = parse_query_time_range(text, now_ts=effective_anchor)
    if start_ts is not None and end_ts is not None:
        return (start_ts + end_ts) * 0.5
    return None


def resolve_valid_until_timestamp(
    raw_value: Any,
    *,
    anchor_ts: float | None = None,
    anchor_iso: str = "",
) -> float | None:
    """Resolve an extracted foresight expiration (`valid_until`) to end-of-period epoch seconds."""
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, (int, float)):
        return parse_iso_or_epoch(raw_value)

    text = str(raw_value or "").strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    try:
        num = float(text)
        if num > 0:
            return num / 1000.0 if num > 1e11 else num
    except ValueError:
        pass

    effective_anchor = anchor_ts
    if effective_anchor is None or effective_anchor <= 0:
        effective_anchor = parse_iso_or_epoch(anchor_iso) or time.time()
    anchor_dt = datetime.fromtimestamp(effective_anchor)

    # Full ISO datetime with explicit clock time (e.g. 2026-11-22T20:00:00+08:00)
    if "T" in text or ":" in text:
        normalized = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            pass

    # Date-only or relative range ("2026-11-22", "明天", "下周", "三天后") -> end of period (23:59:59)
    _start_ts, end_ts = parse_query_time_range(text, now_ts=effective_anchor)
    if end_ts is not None:
        return end_ts

    match_full = _ISO_FULL_DATE_RE.search(text)
    if match_full:
        try:
            target = datetime(
                int(match_full.group("year")),
                int(match_full.group("month")),
                int(match_full.group("day")),
                tzinfo=anchor_dt.tzinfo,
            )
            return _day_bounds(target)[1]
        except ValueError:
            return None
    return None


def format_event_date_tag(
    event_at: float | None,
    *,
    now_ts: float | None = None,
) -> str:
    """Format an optional event timestamp into a compact YYYY-MM-DD tag."""
    del now_ts
    if event_at is None or event_at <= 0:
        return ""
    try:
        return datetime.fromtimestamp(float(event_at)).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


__all__ = [
    "format_event_date_tag",
    "parse_iso_or_epoch",
    "parse_query_time_range",
    "resolve_event_timestamp",
    "resolve_valid_until_timestamp",
]
