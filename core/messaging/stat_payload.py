"""Parse the compact, model-facing ``STAT`` payload format.

Preferred format (one stat per line)::

    heart|HP|72|100
    coins|Gold|320

The fourth field is optional.  Legacy HTML such as ``HP: 72/100<br>Gold:
320`` remains accepted so existing templates and histories keep working.
"""

from __future__ import annotations

import html
import math
import re
from typing import Any

STAT_ICONS = frozenset(
    {
        "clock",
        "coins",
        "gauge",
        "heart",
        "shield",
        "sparkles",
        "star",
        "target",
        "zap",
    }
)

_ICON_ALIASES = {
    "affinity": "sparkles",
    "coin": "coins",
    "defense": "shield",
    "energy": "zap",
    "favour": "sparkles",
    "favor": "sparkles",
    "gold": "coins",
    "health": "heart",
    "hp": "heart",
    "level": "star",
    "life": "heart",
    "love": "sparkles",
    "money": "coins",
    "progress": "target",
    "stamina": "zap",
    "task": "target",
    "time": "clock",
}

_LABEL_ICON_HINTS = (
    (("hp", "health", "life", "生命", "体力", "血量"), "heart"),
    (("shield", "defense", "护盾", "防御"), "shield"),
    (("energy", "stamina", "精力", "能量", "体力值"), "zap"),
    (("affinity", "favor", "favour", "love", "好感", "亲密"), "sparkles"),
    (("gold", "coin", "money", "金币", "金钱"), "coins"),
    (("level", "rank", "等级", "级别"), "star"),
    (("task", "quest", "progress", "任务", "进度"), "target"),
    (("time", "day", "hour", "时间", "天数"), "clock"),
)


def _stat_lines(payload: str) -> list[str]:
    value = re.sub(r"<br\s*/?>", "\n", str(payload or ""), flags=re.IGNORECASE)
    value = re.sub(r"</(?:div|li|p)\s*>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return [line.strip() for line in value.splitlines() if line.strip()]


def _number(value: str) -> int | float | None:
    normalized = str(value or "").strip().replace(",", "")
    if not normalized:
        return None
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _icon(value: str, label: str) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = _ICON_ALIASES.get(normalized, normalized)
    if normalized in STAT_ICONS:
        return normalized
    folded_label = label.casefold()
    for hints, icon in _LABEL_ICON_HINTS:
        if any(hint in folded_label for hint in hints):
            return icon
    return "gauge"


def _legacy_fields(line: str) -> tuple[str, str, str, str] | None:
    match = re.match(
        r"^\s*(?P<label>[^:：|]{1,48})\s*[:：]\s*"
        r"(?P<value>[-+]?\d[\d,]*(?:\.\d+)?)"
        r"(?:\s*/\s*(?P<max>[-+]?\d[\d,]*(?:\.\d+)?))?\s*$",
        line,
    )
    if not match:
        return None
    return "", match.group("label"), match.group("value"), match.group("max") or ""


def _preferred_fields(line: str) -> tuple[str, str, str, str] | None:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) not in {3, 4}:
        return None
    icon, label, value = parts[:3]
    maximum = parts[3] if len(parts) == 4 else ""
    if not maximum and "/" in value:
        value, maximum = [part.strip() for part in value.split("/", 1)]
    return icon, label, value, maximum


def parse_stat_payload(payload: str, *, max_items: int = 8) -> list[dict[str, Any]]:
    """Return normalized stat entries from a model ``STAT`` speech value."""

    stats: list[dict[str, Any]] = []
    for line in _stat_lines(payload):
        fields = _preferred_fields(line) or _legacy_fields(line)
        if not fields:
            continue
        raw_icon, raw_label, raw_value, raw_maximum = fields
        label = raw_label.strip()[:48]
        value = _number(raw_value)
        maximum = _number(raw_maximum)
        if not label or value is None:
            continue
        stat: dict[str, Any] = {
            "icon": _icon(raw_icon, label),
            "label": label,
            "value": value,
        }
        if maximum is not None and maximum > 0:
            stat["max"] = maximum
        stats.append(stat)
        if len(stats) >= max(1, int(max_items)):
            break
    return stats


def format_stats_html(stats: list[dict[str, Any]]) -> str:
    """Render normalized stats for the legacy Qt rich-text value panel."""

    lines: list[str] = []
    for stat in stats:
        label = html.escape(str(stat.get("label") or ""), quote=False)
        value = html.escape(str(stat.get("value") or 0), quote=False)
        maximum = stat.get("max")
        suffix = (
            f" / {html.escape(str(maximum), quote=False)}"
            if maximum is not None
            else ""
        )
        lines.append(f"<span>{label}: {value}{suffix}</span>")
    return "<br>".join(lines)
