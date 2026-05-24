"""API 设定标签页（PySide6）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from asr.asr_adapter import normalize_asr_provider_storage_key
from asr.asr_manager import ASRAdapterFactory
from i18n import init_i18n, tr as tr_i18n
from sdk.lang import normalize_lang
from llm.constants import LLM_BASE_URLS
from llm.llm_manager import LLMAdapterFactory
from t2i.t2i_manager import T2IAdapterFactory
from tts.tts_manager import TTSAdapterFactory
from ui.settings_ui.widgets.adapter_extra_form import (
    build_schema_widgets,
    read_schema_values,
)
from ui.settings_ui.services.chat_template_handlers import launch_chat_resume_last
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import (
    feedback_result,
    message_fail,
    message_info,
    toast_success,
)
from ui.settings_ui.tts.tts_bundle_download_dialog import TtsBundleDownloadDialog


_ASR_WHISPER_MODEL_PRESETS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v1",
    "large-v2",
    "large-v3",
    "distil-large-v2",
    "distil-large-v3",
)
_TTS_LABEL_PREFS: tuple[tuple[str, str], ...] = (
    ("genie-tts", "Genie TTS"),
    ("gpt-sovits", "GPT SoVITS"),
    ("index-tts", "IndexTTS"),
    ("cosyvoice", "CosyVoice"),
)
_PREFERRED_T2I_KEYS_LOWER: tuple[str, ...] = ("comfyui", "stable diffusion")
_MODEL_REQUEST_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 Shinsekai/1.0"
)
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_LLM_CAPABILITY_CACHE_PATH = Path("data/config/llm_model_capabilities.json")
_LLM_CAPABILITY_CACHE_VERSION = 2
_LLM_CAPABILITY_FETCH_TIMEOUT_SEC = 10.0
_OPENROUTER_CACHE_TTL_SEC = 24 * 60 * 60
_PROBE_STABLE_CACHE_TTL_SEC = 7 * 24 * 60 * 60
_PROBE_NO_ACCESS_CACHE_TTL_SEC = 60 * 60
_TRANSPARENT_PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
_OPENROUTER_PROVIDER_HINTS: dict[str, tuple[str, ...]] = {
    "chatgpt": ("openai",),
    "openai": ("openai",),
    "deepseek": ("deepseek",),
    "gemini": ("google",),
    "claude": ("anthropic",),
    "豆包": ("bytedance",),
    "通义千问": ("qwen", "alibaba"),
    "qwen": ("qwen",),
}
_TEXT_ONLY_PROBE_MARKERS = (
    "image_url",
    "image input",
    "image content",
    "vision",
    "multimodal",
    "multi-modal",
    "content must be a string",
    "expected a string",
    "got an array",
    "unsupported content",
    "invalid content type",
)
_NO_ACCESS_PROBE_MARKERS = (
    "auth_unavailable",
    "no auth available",
    "do not have access",
    "does not have access",
    "not available for your account",
    "account is not authorized",
    "permission denied",
    "insufficient permissions",
    "not supported when using",
)
_IMAGE_ONLY_PROBE_MARKERS = (
    "only supported on /v1/images/",
    "only supported on /images/",
    "only supports /v1/images/",
    "only supports /images/",
    "images/generations",
    "images/edits",
)
_IMAGE_ONLY_MODEL_ID_MARKERS = (
    "dall-e",
    "dalle",
    "flux",
    "gpt-image",
    "imagen",
    "imagegeneration@",
    "imagetext@",
    "midjourney",
    "qwen-image",
    "sdxl",
    "stable-diffusion",
)
_IMAGE_ONLY_MODEL_ID_PATTERNS = (
    "-image-preview",
    "-preview-image-generation",
    "-image-generation",
    "_image_preview",
    "_image_generation",
)
_UNCERTAIN_PROBE_STATUS = frozenset(
    {"unknown", "network", "unsupported_probe", "timeout"}
)
_LLM_CAPABILITY_ROLE = Qt.ItemDataRole.UserRole + 1
_COMBO_POPUP_HOVER_DELEGATE_ATTR = "_pydracula_combo_popup_hover_delegate"
_LLM_CAPABILITY_BADGE_BG_ALPHA = 188
_LLM_CAPABILITY_BADGE_BORDER_ALPHA = 225
_LLM_CAPABILITY_BADGE_COLORS: dict[str, tuple[str, str, str]] = {
    "text": ("#3b6ea8", "#8be9fd", "#f8f8f2"),
    "vision": ("#bd93f9", "#d6b8ff", "#241633"),
    "file": ("#8be9fd", "#a7f0ff", "#12323a"),
    "audio": ("#ff79c6", "#ffa3d8", "#3d1730"),
    "video": ("#ffb86c", "#ffd39b", "#3a260e"),
    "image_out": ("#50fa7b", "#8aff9f", "#103218"),
    "unknown": ("#44475a", "#6272a4", "#f8f8f2"),
    "no_access": ("#ff5555", "#ff8a8a", "#3a1010"),
    "not_found": ("#6272a4", "#7b8fc0", "#f8f8f2"),
}
_LLM_CAPABILITY_TAG_DISPLAY: dict[str, bool] = {
    "text": True,
    "vision": False,
    "file": False,
    "audio": False,
    "video": False,
    "image_out": False,
    "no_access": False,
    "not_found": False,
    "unknown": True,
}
_LLM_MODEL_FETCH_MODE_QSS = """
QComboBox::drop-down {
    width: 0px;
    border: none;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
"""
_LLM_MODEL_FETCH_BUTTON_QSS = """
QPushButton#llmModelInlineFetchButton {
    background-color: rgba(98, 114, 164, 190);
    border: 1px solid rgba(189, 147, 249, 190);
    border-radius: 5px;
    color: rgb(248, 248, 242);
    font-weight: 600;
    padding: 2px 8px;
}
QPushButton#llmModelInlineFetchButton:hover {
    background-color: rgba(117, 134, 185, 210);
}
QPushButton#llmModelInlineFetchButton:pressed {
    background-color: rgba(80, 92, 132, 220);
}
QPushButton#llmModelInlineFetchButton:disabled {
    background-color: rgba(64, 71, 88, 150);
    border-color: rgba(98, 114, 164, 150);
    color: rgba(221, 221, 221, 170);
}
"""


@dataclass(frozen=True)
class _LLMModelsRequestSpec:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class _LLMModelCapability:
    tags: tuple[str, ...]
    source: str = ""
    status: str = ""
    detail: str = ""


@dataclass(frozen=True)
class _LLMModelOption:
    model_id: str
    capability: _LLMModelCapability | None = None


@dataclass(frozen=True)
class _OpenRouterModelCapabilityEntry:
    model_id: str
    keys: frozenset[str]
    capability: _LLMModelCapability


@dataclass
class _LLMCapabilityCache:
    openrouter_entries: list[_OpenRouterModelCapabilityEntry]
    openrouter_fetched_at: float
    probe: dict[str, tuple[_LLMModelCapability, float]]


class _LLMModelFetchError(RuntimeError):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


def _llm_model_request_common_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": _MODEL_REQUEST_USER_AGENT,
    }


def _badge_qcolor(hex_color: str, alpha: int) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def _llm_capability_label_for_tag(tag: str) -> str:
    key = f"api.capability.{tag}"
    label = tr_i18n(key)
    return label if label != key else tr_i18n("api.capability.unknown")


def _llm_capability_tag_visible(tag: str) -> bool:
    return _LLM_CAPABILITY_TAG_DISPLAY.get(tag, True)


def _llm_capability_tags(
    cap: _LLMModelCapability | None, *, visible_only: bool = True
) -> tuple[str, ...]:
    if cap is None:
        return ()
    return tuple(
        tag
        for tag in cap.tags
        if tag and (not visible_only or _llm_capability_tag_visible(tag))
    )


def _ordered_unique_tags(tags: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for tag in tags:
        tag = str(tag or "").strip()
        if tag and tag not in out:
            out.append(tag)
    return tuple(out)


def _ensure_text_tag_for_multimodal_chat(tags: tuple[str, ...]) -> tuple[str, ...]:
    if "text" in tags or "image_out" in tags:
        return tags
    if any(tag in tags for tag in ("vision", "file", "audio", "video")):
        return ("text", *tags)
    return tags


class _LLMModelCapabilityDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)
        model_text = item_option.text
        cap = index.data(_LLM_CAPABILITY_ROLE)
        tags = _llm_capability_tags(
            cap if isinstance(cap, _LLMModelCapability) else None
        )
        labels = [_llm_capability_label_for_tag(tag) for tag in tags]
        item_option.text = ""

        if item_option.state & (
            QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected
        ):
            item_option.state |= QStyle.StateFlag.State_Selected
            item_option.palette.setColor(
                QPalette.ColorRole.Highlight, QColor(64, 71, 88)
            )
            item_option.palette.setColor(
                QPalette.ColorRole.HighlightedText, QColor(221, 221, 221)
            )

        widget = item_option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, item_option, painter, widget
        )
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, item_option, widget
        )

        painter.save()
        fm = item_option.fontMetrics
        selected = bool(item_option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(
            item_option.palette.color(
                QPalette.ColorRole.HighlightedText
                if selected
                else QPalette.ColorRole.Text
            )
        )

        badge_specs: list[tuple[str, str, int]] = []
        for tag, label in zip(tags, labels, strict=True):
            badge_specs.append((tag, label, fm.horizontalAdvance(label) + 18))
        badge_gap = 6
        badge_total = sum(spec[2] for spec in badge_specs)
        if badge_specs:
            badge_total += badge_gap * (len(badge_specs) - 1)

        text_gap = 12 if badge_specs else 0
        model_rect = QRect(text_rect)
        model_rect.setWidth(max(0, text_rect.width() - badge_total - text_gap))
        painter.drawText(
            model_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(model_text, Qt.TextElideMode.ElideRight, model_rect.width()),
        )

        if badge_specs:
            badge_h = min(20, max(16, text_rect.height() - 4))
            x = text_rect.right() - badge_total + 1
            y = text_rect.y() + max(0, (text_rect.height() - badge_h) // 2)
            for tag, label, width in badge_specs:
                bg, border, fg = _LLM_CAPABILITY_BADGE_COLORS.get(
                    tag, _LLM_CAPABILITY_BADGE_COLORS["unknown"]
                )
                rect = QRect(x, y, width, badge_h)
                painter.setPen(
                    _badge_qcolor(border, _LLM_CAPABILITY_BADGE_BORDER_ALPHA)
                )
                painter.setBrush(_badge_qcolor(bg, _LLM_CAPABILITY_BADGE_BG_ALPHA))
                painter.drawRoundedRect(rect, 5, 5)
                painter.setPen(QColor(fg))
                painter.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )
                x += width + badge_gap
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 30))


class _LLMModelLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._capability_tags: tuple[str, ...] = ()
        self._action_reserved_width = 0
        self._base_text_margins = self.textMargins()

    def set_capability_tags(self, tags: tuple[str, ...]) -> None:
        self._capability_tags = tuple(tag for tag in tags if tag)
        self._sync_text_margins()
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_text_margins()

    def set_action_reserved_width(self, width: int) -> None:
        clean_width = max(0, int(width))
        if self._action_reserved_width == clean_width:
            return
        self._action_reserved_width = clean_width
        self._sync_text_margins()
        self.update()

    def _badge_specs(self) -> list[tuple[str, str, int]]:
        fm = self.fontMetrics()
        specs: list[tuple[str, str, int]] = []
        for tag in self._capability_tags:
            label = _llm_capability_label_for_tag(tag)
            specs.append((tag, label, fm.horizontalAdvance(label) + 18))
        return specs

    def _badge_total_width(self) -> int:
        specs = self._badge_specs()
        if not specs:
            return 0
        return sum(spec[2] for spec in specs) + 6 * (len(specs) - 1)

    def _sync_text_margins(self) -> None:
        base = self._base_text_margins
        right = base.right()
        badge_width = self._badge_total_width()
        if badge_width:
            right += badge_width + 14
        if self._action_reserved_width:
            right += self._action_reserved_width + 10
        self.setTextMargins(base.left(), base.top(), right, base.bottom())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        specs = self._badge_specs()
        if not specs:
            return

        badge_gap = 6
        badge_total = sum(spec[2] for spec in specs) + badge_gap * (len(specs) - 1)
        badge_h = min(20, max(16, self.height() - 8))
        action_gap = (
            self._action_reserved_width + 10 if self._action_reserved_width else 0
        )
        x = self.width() - badge_total - action_gap - 8
        y = max(0, (self.height() - badge_h) // 2)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for tag, label, width in specs:
            bg, border, fg = _LLM_CAPABILITY_BADGE_COLORS.get(
                tag, _LLM_CAPABILITY_BADGE_COLORS["unknown"]
            )
            rect = QRect(x, y, width, badge_h)
            painter.setPen(_badge_qcolor(border, _LLM_CAPABILITY_BADGE_BORDER_ALPHA))
            painter.setBrush(_badge_qcolor(bg, _LLM_CAPABILITY_BADGE_BG_ALPHA))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor(fg))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
            x += width + badge_gap


def _llm_model_provider_kind(provider: str, base_url: str) -> str:
    low_provider = (provider or "").strip().lower()
    low_base = (base_url or "").strip().lower()
    if "gemini" in low_provider or "generativelanguage.googleapis.com" in low_base:
        return "gemini"
    if "deepseek" in low_provider or "api.deepseek.com" in low_base:
        return "deepseek"
    if (
        low_provider == "claude"
        or "claude" in low_provider
        or "anthropic.com" in low_base
    ):
        return "anthropic"
    if (
        "dashscope.aliyuncs.com" in low_base
        or "通义" in low_provider
        or "qwen" in low_provider
        or "dashscope" in low_provider
    ):
        return "dashscope"
    return "openai_compatible"


def _base_url_required(base_url: str) -> str:
    base = (base_url or "").strip()
    if not base:
        raise ValueError(tr_i18n("api.msg.model_fetch_missing"))
    return base


def _openai_compatible_models_endpoint_url(base_url: str) -> str:
    base = _base_url_required(base_url)
    if base.rstrip("/").lower().endswith("/models"):
        return base.rstrip("/")
    return f"{base.rstrip('/')}/models"


def _gemini_models_endpoint_url(base_url: str, api_key: str) -> str:
    base = _base_url_required(base_url).rstrip("/")
    low_base = base.lower()
    if "generativelanguage.googleapis.com" not in low_base:
        return _openai_compatible_models_endpoint_url(base)
    marker = "/openai"
    marker_ix = low_base.rfind(marker)
    if marker_ix >= 0:
        base = base[:marker_ix]
    if not base.lower().endswith("/v1beta"):
        base = "https://generativelanguage.googleapis.com/v1beta"
    query = urllib.parse.urlencode({"key": (api_key or "").strip()})
    return f"{base.rstrip('/')}/models?{query}"


def _deepseek_models_endpoint_url(base_url: str) -> str:
    base = _base_url_required(base_url).rstrip("/")
    if "api.deepseek.com" in base.lower() and base.lower().endswith("/v1"):
        base = base[:-3]
    return _openai_compatible_models_endpoint_url(base)


def _dashscope_models_endpoint_url(base_url: str) -> str:
    base = _base_url_required(base_url).rstrip("/")
    low_base = base.lower()
    query = urllib.parse.urlencode(
        {
            "page_no": 1,
            "page_size": 100,
            "version": "v1.0",
            "model_source": "base",
        }
    )
    if low_base.endswith("/compatible-mode/v1"):
        base = base[: -len("/compatible-mode/v1")] + "/api/v1"
    if low_base.endswith("/api/v1") or base.lower().endswith("/api/v1"):
        return f"{base}/deployments/models?{query}"
    return _openai_compatible_models_endpoint_url(base)


def _llm_models_endpoint_url(
    base_url: str, provider: str = "", api_key: str = ""
) -> str:
    kind = _llm_model_provider_kind(provider, base_url)
    if kind == "gemini":
        return _gemini_models_endpoint_url(base_url, api_key)
    if kind == "deepseek":
        return _deepseek_models_endpoint_url(base_url)
    if kind == "dashscope":
        return _dashscope_models_endpoint_url(base_url)
    return _openai_compatible_models_endpoint_url(base_url)


def _llm_models_request_headers(
    provider: str, base_url: str, api_key: str
) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        raise ValueError(tr_i18n("api.msg.model_fetch_missing"))
    headers = _llm_model_request_common_headers()
    kind = _llm_model_provider_kind(provider, base_url)
    if (
        kind == "gemini"
        and "generativelanguage.googleapis.com" in (base_url or "").lower()
    ):
        return headers
    if kind == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        headers["Content-Type"] = "application/json"
    else:
        headers["Authorization"] = f"Bearer {key}"
        if kind == "dashscope":
            headers["Content-Type"] = "application/json"
    return headers


def _iter_llm_model_items(payload: object):
    if isinstance(payload, list):
        yield from payload
        return
    if not isinstance(payload, dict):
        return
    for key in ("data", "models", "items", "deployments"):
        raw_items = payload.get(key)
        if isinstance(raw_items, list):
            yield from raw_items
        elif isinstance(raw_items, dict):
            yield from _iter_llm_model_items(raw_items)
    for key in ("output", "result"):
        raw_group = payload.get(key)
        if isinstance(raw_group, (dict, list)):
            yield from _iter_llm_model_items(raw_group)


def _llm_model_item_supports_chat(item: dict) -> bool:
    actions = item.get("supportedGenerationMethods") or item.get("supportedActions")
    if isinstance(actions, list):
        normalized = {str(action).strip().lower() for action in actions}
        return bool({"generatecontent", "chat.completions", "chat"} & normalized)

    endpoints = item.get("supported_endpoint_types") or item.get(
        "supportedEndpointTypes"
    )
    if isinstance(endpoints, list):
        normalized = {str(endpoint).strip().lower() for endpoint in endpoints}
        if any("chat" in endpoint or endpoint == "responses" for endpoint in normalized):
            return True
        if any("image" in endpoint for endpoint in normalized):
            return False
    return True


def _llm_model_id_is_image_only(model_id: str) -> bool:
    low = (model_id or "").strip().removeprefix("models/").lower()
    if any(marker in low for marker in _IMAGE_ONLY_MODEL_ID_MARKERS):
        return True
    if any(pattern in low for pattern in _IMAGE_ONLY_MODEL_ID_PATTERNS):
        return True
    parts = [part for part in low.replace("_", "-").replace(".", "-").split("-") if part]
    return "image" in parts and (
        "generation" in parts or "preview" in parts or low.startswith("gemini-")
    )


def _llm_capability_is_image_only(cap: _LLMModelCapability | None) -> bool:
    if cap is None:
        return False
    tags = set(_llm_capability_tags(cap, visible_only=False))
    return cap.status == "image_only" or tags == {"image_out"}


def _llm_model_id_from_item(item: object) -> str:
    if isinstance(item, str):
        model_id = item.strip()
        return "" if _llm_model_id_is_image_only(model_id) else model_id
    if not isinstance(item, dict):
        return ""
    if not _llm_model_item_supports_chat(item):
        return ""
    for key in (
        "id",
        "model",
        "model_id",
        "modelId",
        "model_name",
        "modelName",
        "name",
        "deployed_model",
        "base_model",
    ):
        model_id = str(item.get(key) or "").strip()
        if model_id:
            if model_id.startswith("models/"):
                model_id = model_id.split("/", 1)[1].strip()
            return "" if _llm_model_id_is_image_only(model_id) else model_id
    return ""


def _extract_llm_model_ids(payload: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in _iter_llm_model_items(payload):
        model_id = _llm_model_id_from_item(item)
        if model_id and model_id not in seen:
            seen.add(model_id)
            out.append(model_id)
    return out


def _llm_models_request_spec(
    provider: str, base_url: str, api_key: str
) -> _LLMModelsRequestSpec:
    return _LLMModelsRequestSpec(
        url=_llm_models_endpoint_url(base_url, provider, api_key),
        headers=_llm_models_request_headers(provider, base_url, api_key),
    )


def _summarize_http_error(e: urllib.error.HTTPError, detail: str) -> str:
    reason = str(e.reason or "").strip()
    if detail:
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            error_obj = payload.get("error")
            if isinstance(error_obj, dict):
                error_message = error_obj.get("message")
                error_type = error_obj.get("type")
                error_code = error_obj.get("code")
            else:
                error_message = error_obj
                error_type = None
                error_code = None
            title = str(payload.get("title") or payload.get("error_name") or "").strip()
            code = str(
                payload.get("error_code") or payload.get("code") or error_code or ""
            ).strip()
            name = str(payload.get("error_name") or error_type or "").strip()
            message = str(
                payload.get("message") or payload.get("detail") or error_message or ""
            ).strip()
            bits = [bit for bit in (title, name, code, message) if bit]
            if bits:
                return f"HTTP {e.code}: {'; '.join(bits)}"
    return f"HTTP {e.code}: {reason or detail or 'request failed'}"


def _fetch_llm_model_ids(
    provider: str,
    base_url: str,
    api_key: str,
    *,
    timeout_sec: float = 20.0,
) -> list[str]:
    spec = _llm_models_request_spec(provider, base_url, api_key)
    req = urllib.request.Request(
        spec.url,
        headers=spec.headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace").strip()
        raise _LLMModelFetchError(_summarize_http_error(e, detail), detail) from e
    except urllib.error.URLError as e:
        raise _LLMModelFetchError(str(e.reason or e)) from e
    except json.JSONDecodeError as e:
        raise _LLMModelFetchError(f"Invalid JSON response: {e}") from e
    return _extract_llm_model_ids(payload)


def _modalities_to_set(raw: object) -> set[str]:
    if isinstance(raw, list):
        return {str(v).strip().lower() for v in raw if str(v).strip()}
    if isinstance(raw, str) and raw.strip():
        return {
            part.strip().lower()
            for part in raw.replace("+", ",").replace("->", ",").split(",")
            if part.strip()
        }
    return set()


def _capability_from_modalities(
    input_modalities: object, output_modalities: object, *, source: str
) -> _LLMModelCapability | None:
    inputs = _modalities_to_set(input_modalities)
    outputs = _modalities_to_set(output_modalities)
    tags: list[str] = []
    if "text" in outputs:
        tags.append("text")
    if "image" in inputs:
        tags.append("vision")
    if "file" in inputs:
        tags.append("file")
    if "audio" in inputs:
        tags.append("audio")
    if "video" in inputs:
        tags.append("video")
    if "image" in outputs:
        tags.append("image_out")
    if not tags and "text" in inputs:
        tags.append("text")
    if not tags:
        return None
    clean_tags = _ensure_text_tag_for_multimodal_chat(_ordered_unique_tags(tags))
    return _LLMModelCapability(clean_tags, source=source, status="ok")


def _model_match_key(value: str) -> str:
    return str(value or "").strip().removeprefix("models/").lower()


def _model_match_key_variants(model_id: str) -> set[str]:
    key = _model_match_key(model_id)
    variants = {key} if key else set()
    if "/" in key:
        variants.add(key.rsplit("/", 1)[-1])
    for item in list(variants):
        if ":" in item:
            variants.add(item.split(":", 1)[0])
    return {v for v in variants if v}


def _openrouter_entry_from_item(
    item: object,
) -> _OpenRouterModelCapabilityEntry | None:
    if not isinstance(item, dict):
        return None
    model_id = str(item.get("id") or item.get("canonical_slug") or "").strip()
    if not model_id:
        return None
    arch = item.get("architecture")
    arch = arch if isinstance(arch, dict) else {}
    input_modalities = arch.get("input_modalities")
    output_modalities = arch.get("output_modalities")
    if input_modalities is None and output_modalities is None:
        modality = str(arch.get("modality") or "")
        if "->" in modality:
            input_modalities, output_modalities = modality.split("->", 1)
    cap = _capability_from_modalities(
        input_modalities,
        output_modalities,
        source="openrouter",
    )
    if cap is None:
        return None
    keys: set[str] = set()
    for key in ("id", "canonical_slug"):
        val = str(item.get(key) or "").strip()
        if val:
            keys.update(_model_match_key_variants(val))
    return _OpenRouterModelCapabilityEntry(
        model_id=model_id, keys=frozenset(keys), capability=cap
    )


def _fetch_openrouter_capability_entries(
    *, timeout_sec: float = 4.0
) -> list[_OpenRouterModelCapabilityEntry]:
    req = urllib.request.Request(
        _OPENROUTER_MODELS_URL,
        headers=_llm_model_request_common_headers(),
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
        json.JSONDecodeError,
    ):
        return []
    raw_items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []
    out: list[_OpenRouterModelCapabilityEntry] = []
    for item in raw_items:
        entry = _openrouter_entry_from_item(item)
        if entry is not None:
            out.append(entry)
    return out


def _unique_capability(
    entries: list[_OpenRouterModelCapabilityEntry],
) -> _LLMModelCapability | None:
    by_model: dict[str, _LLMModelCapability] = {}
    for entry in entries:
        by_model[entry.model_id] = entry.capability
    if len(by_model) != 1:
        return None
    return next(iter(by_model.values()))


def _provider_openrouter_hints(provider: str) -> tuple[str, ...]:
    low = (provider or "").strip().lower()
    if low in _OPENROUTER_PROVIDER_HINTS:
        return _OPENROUTER_PROVIDER_HINTS[low]
    for key, hints in _OPENROUTER_PROVIDER_HINTS.items():
        if key in low:
            return hints
    return ()


def _match_openrouter_capability(
    model_id: str,
    provider: str,
    entries: list[_OpenRouterModelCapabilityEntry],
) -> _LLMModelCapability | None:
    variants = _model_match_key_variants(model_id)
    if not variants:
        return None

    exact = [entry for entry in entries if variants & entry.keys]
    cap = _unique_capability(exact)
    if cap is not None:
        return cap

    hinted: list[_OpenRouterModelCapabilityEntry] = []
    for hint in _provider_openrouter_hints(provider):
        hint = hint.strip().lower()
        hinted.extend(
            entry
            for entry in entries
            if any(f"{hint}/{variant}" in entry.keys for variant in variants)
        )
    cap = _unique_capability(hinted)
    if cap is not None:
        return cap

    suffix_matches = [
        entry
        for entry in entries
        if any(
            _model_match_key(entry.model_id).endswith(f"/{variant}")
            or _model_match_key(entry.model_id).endswith(f"/{variant}:free")
            for variant in variants
        )
    ]
    return _unique_capability(suffix_matches)


def _api_key_fingerprint(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return "no-key"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _llm_probe_cache_key(
    provider: str, base_url: str, api_key: str, model_id: str
) -> str:
    probe_url = _chat_completions_probe_url(provider, base_url)
    return "|".join(
        (
            (provider or "").strip().lower(),
            (base_url or "").strip().rstrip("/").lower(),
            probe_url.strip().rstrip("/").lower(),
            _api_key_fingerprint(api_key),
            (model_id or "").strip().lower(),
        )
    )


def _capability_from_cache_value(
    value: object, *, default_source: str = "cache"
) -> tuple[_LLMModelCapability | None, float]:
    if not isinstance(value, dict):
        return None, 0.0
    tags = value.get("tags")
    if not isinstance(tags, list):
        return None, 0.0
    clean_tags = tuple(str(tag).strip() for tag in tags if str(tag).strip())
    if not clean_tags:
        return None, 0.0

    source = str(value.get("source") or default_source)
    status = str(value.get("status") or "")
    detail = str(value.get("detail") or "")
    if source == "probe" and status == "unknown":
        low_detail = detail.lower()
        if any(marker in low_detail for marker in _NO_ACCESS_PROBE_MARKERS):
            clean_tags = ("no_access",)
            status = "no_access"
        elif any(marker in low_detail for marker in _IMAGE_ONLY_PROBE_MARKERS):
            clean_tags = ("image_out",)
            status = "image_only"
    clean_tags = _ensure_text_tag_for_multimodal_chat(clean_tags)
    try:
        updated_at = float(value.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        updated_at = 0.0
    return (
        _LLMModelCapability(
            clean_tags,
            source=source,
            status=status,
            detail=detail,
        ),
        updated_at,
    )


def _openrouter_entries_from_cache(
    payload: object,
) -> tuple[list[_OpenRouterModelCapabilityEntry], float]:
    if not isinstance(payload, dict):
        return [], 0.0
    try:
        fetched_at = float(payload.get("fetched_at") or 0.0)
    except (TypeError, ValueError):
        fetched_at = 0.0
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return [], fetched_at

    entries: list[_OpenRouterModelCapabilityEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("model_id") or "").strip()
        raw_keys = item.get("keys")
        keys = (
            frozenset(str(key).strip() for key in raw_keys if str(key).strip())
            if isinstance(raw_keys, list)
            else frozenset()
        )
        cap, _updated_at = _capability_from_cache_value(
            item, default_source="openrouter"
        )
        if model_id and keys and cap is not None:
            entries.append(
                _OpenRouterModelCapabilityEntry(
                    model_id=model_id,
                    keys=keys,
                    capability=_LLMModelCapability(
                        cap.tags,
                        source="openrouter",
                        status=cap.status or "ok",
                        detail=cap.detail,
                    ),
                )
            )
    return entries, fetched_at


def _serialize_openrouter_entry(entry: _OpenRouterModelCapabilityEntry) -> dict:
    return {
        "model_id": entry.model_id,
        "keys": sorted(entry.keys),
        "tags": list(entry.capability.tags),
        "source": "openrouter",
        "status": entry.capability.status or "ok",
        "detail": entry.capability.detail,
    }


def _serialize_capability(cap: _LLMModelCapability, updated_at: float) -> dict:
    return {
        "tags": list(cap.tags),
        "source": cap.source,
        "status": cap.status,
        "detail": cap.detail,
        "updated_at": updated_at,
    }


def _read_llm_capability_cache() -> _LLMCapabilityCache:
    if not _LLM_CAPABILITY_CACHE_PATH.is_file():
        return _LLMCapabilityCache([], 0.0, {})
    try:
        raw = json.loads(_LLM_CAPABILITY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _LLMCapabilityCache([], 0.0, {})
    if not isinstance(raw, dict):
        return _LLMCapabilityCache([], 0.0, {})

    openrouter_entries, openrouter_fetched_at = _openrouter_entries_from_cache(
        raw.get("openrouter")
    )

    probe: dict[str, tuple[_LLMModelCapability, float]] = {}
    probe_payload = raw.get("probe")
    probe_entries = (
        probe_payload.get("entries") if isinstance(probe_payload, dict) else None
    )
    if isinstance(probe_entries, dict):
        for key, value in probe_entries.items():
            if not isinstance(key, str):
                continue
            cap, updated_at = _capability_from_cache_value(
                value, default_source="probe"
            )
            if cap is not None:
                probe[key] = (cap, updated_at)

    return _LLMCapabilityCache(openrouter_entries, openrouter_fetched_at, probe)


def _write_llm_capability_cache(cache: _LLMCapabilityCache) -> None:
    try:
        _LLM_CAPABILITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _LLM_CAPABILITY_CACHE_VERSION,
            "openrouter": {
                "fetched_at": cache.openrouter_fetched_at,
                "entries": [
                    _serialize_openrouter_entry(entry)
                    for entry in cache.openrouter_entries
                ],
            },
            "probe": {
                "entries": {
                    key: _serialize_capability(cap, updated_at)
                    for key, (cap, updated_at) in sorted(cache.probe.items())
                }
            },
        }
        _LLM_CAPABILITY_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def _probe_cache_ttl(cap: _LLMModelCapability) -> float:
    if cap.status == "no_access":
        return _PROBE_NO_ACCESS_CACHE_TTL_SEC
    return _PROBE_STABLE_CACHE_TTL_SEC


def _probe_cache_entry_valid(
    entry: tuple[_LLMModelCapability, float] | None, *, now: float
) -> _LLMModelCapability | None:
    if entry is None:
        return None
    cap, updated_at = entry
    if cap.status in _UNCERTAIN_PROBE_STATUS:
        return None
    if updated_at <= 0:
        return None
    if now - updated_at > _probe_cache_ttl(cap):
        return None
    return cap


def _should_cache_probe_capability(cap: _LLMModelCapability) -> bool:
    return cap.status not in _UNCERTAIN_PROBE_STATUS


def _unknown_llm_model_capability(status: str = "unknown") -> _LLMModelCapability:
    return _LLMModelCapability(("unknown",), source=status, status=status)


def _refresh_openrouter_cache_if_needed(
    cache: _LLMCapabilityCache, *, now: float
) -> bool:
    if (
        cache.openrouter_entries
        and now - cache.openrouter_fetched_at <= _OPENROUTER_CACHE_TTL_SEC
    ):
        return False
    entries = _fetch_openrouter_capability_entries()
    if not entries:
        return False
    cache.openrouter_entries = entries
    cache.openrouter_fetched_at = now
    return True


def _lookup_probe_cache(
    cache: _LLMCapabilityCache,
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str,
    *,
    now: float,
) -> _LLMModelCapability | None:
    cap = _probe_cache_entry_valid(
        cache.probe.get(_llm_probe_cache_key(provider, base_url, api_key, model_id)),
        now=now,
    )
    if cap is not None:
        return cap
    return None


def _store_probe_cache(
    cache: _LLMCapabilityCache,
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str,
    cap: _LLMModelCapability,
    *,
    now: float,
) -> None:
    if not _should_cache_probe_capability(cap):
        return
    cache.probe[_llm_probe_cache_key(provider, base_url, api_key, model_id)] = (
        cap,
        now,
    )


def _chat_completions_probe_url(provider: str, base_url: str) -> str:
    base = _base_url_required(base_url).rstrip("/")
    low = base.lower()
    if low.endswith("/models"):
        base = base[: -len("/models")]
        low = base.lower()
    kind = _llm_model_provider_kind(provider, base)
    if kind == "dashscope" and "dashscope.aliyuncs.com" in low:
        if low.endswith("/api/v1/deployments"):
            base = base[: -len("/api/v1/deployments")] + "/compatible-mode/v1"
            low = base.lower()
        elif low.endswith("/api/v1/chat/completions"):
            base = base[: -len("/api/v1/chat/completions")] + "/compatible-mode/v1"
            low = base.lower()
        elif low.endswith("/api/v1"):
            base = base[: -len("/api/v1")] + "/compatible-mode/v1"
            low = base.lower()
    elif kind == "gemini" and "generativelanguage.googleapis.com" in low:
        if low.endswith("/v1beta") or low.endswith("/v1"):
            base = f"{base}/openai"
            low = base.lower()
    if low.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _llm_probe_headers(provider: str, base_url: str, api_key: str) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        raise ValueError(tr_i18n("api.msg.model_fetch_missing"))
    headers = _llm_model_request_common_headers()
    headers["Content-Type"] = "application/json"
    kind = _llm_model_provider_kind(provider, base_url)
    if kind == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _probe_payload(model_id: str, *, token_field: str) -> bytes:
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                "data:image/png;base64,"
                                f"{_TRANSPARENT_PNG_1X1_B64}"
                            )
                        },
                    },
                ],
            }
        ],
        token_field: 1,
    }
    return json.dumps(payload).encode("utf-8")


def _probe_error_suggests_token_field_retry(detail: str) -> bool:
    low = (detail or "").lower()
    return "max_tokens" in low and "max_completion_tokens" in low


def _classify_probe_http_error(
    status_code: int, detail: str
) -> _LLMModelCapability:
    low = (detail or "").lower()
    if status_code in (401, 403) or any(
        marker in low for marker in _NO_ACCESS_PROBE_MARKERS
    ):
        return _LLMModelCapability(
            ("no_access",), source="probe", status="no_access", detail=detail
        )
    if any(marker in low for marker in _IMAGE_ONLY_PROBE_MARKERS):
        return _LLMModelCapability(
            ("image_out",), source="probe", status="image_only", detail=detail
        )
    if status_code == 404:
        return _LLMModelCapability(
            ("not_found",), source="probe", status="not_found", detail=detail
        )
    if status_code in (400, 422) and any(
        marker in low for marker in _TEXT_ONLY_PROBE_MARKERS
    ):
        return _LLMModelCapability(
            ("text",), source="probe", status="text_only", detail=detail
        )
    return _LLMModelCapability(
        ("unknown",), source="probe", status="unknown", detail=detail
    )


def _probe_llm_model_capability(
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str,
    *,
    timeout_sec: float = 12.0,
    deadline_monotonic: float | None = None,
) -> _LLMModelCapability:
    if _llm_model_provider_kind(provider, base_url) == "anthropic":
        return _unknown_llm_model_capability("unsupported_probe")
    url = _chat_completions_probe_url(provider, base_url)
    headers = _llm_probe_headers(provider, base_url, api_key)

    for token_field in ("max_tokens", "max_completion_tokens"):
        request_timeout = timeout_sec
        if deadline_monotonic is not None:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                return _unknown_llm_model_capability("timeout")
            request_timeout = min(timeout_sec, max(0.1, remaining))
        req = urllib.request.Request(
            url,
            data=_probe_payload(model_id, token_field=token_field),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                resp.read(1024)
            return _LLMModelCapability(
                ("text", "vision"), source="probe", status="ok"
            )
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace").strip()
            if token_field == "max_tokens" and _probe_error_suggests_token_field_retry(
                detail
            ):
                continue
            return _classify_probe_http_error(int(e.code), detail)
        except urllib.error.URLError as e:
            return _LLMModelCapability(
                ("unknown",),
                source="probe",
                status="network",
                detail=str(e.reason or e),
            )
        except OSError as e:
            return _LLMModelCapability(
                ("unknown",), source="probe", status="network", detail=str(e)
            )
    return _unknown_llm_model_capability()


def _fetch_llm_model_options(
    provider: str,
    base_url: str,
    api_key: str,
    *,
    detect_capability: bool = False,
) -> list[_LLMModelOption]:
    models = _fetch_llm_model_ids(provider, base_url, api_key)
    if not detect_capability:
        return [_LLMModelOption(model_id) for model_id in models]

    now = time.time()
    capability_deadline = time.monotonic() + _LLM_CAPABILITY_FETCH_TIMEOUT_SEC
    cache = _read_llm_capability_cache()
    cache_changed = _refresh_openrouter_cache_if_needed(cache, now=now)
    out: list[_LLMModelOption] = []
    for model_id in models:
        cap = _match_openrouter_capability(
            model_id, provider, cache.openrouter_entries
        )
        if cap is None:
            cap = _lookup_probe_cache(
                cache,
                provider,
                base_url,
                api_key,
                model_id,
                now=now,
            )
        if cap is None:
            remaining = capability_deadline - time.monotonic()
            if remaining <= 0:
                cap = _unknown_llm_model_capability("timeout")
            else:
                cap = _probe_llm_model_capability(
                    provider,
                    base_url,
                    api_key,
                    model_id,
                    timeout_sec=min(12.0, remaining),
                    deadline_monotonic=capability_deadline,
                )
            if _should_cache_probe_capability(cap):
                _store_probe_cache(
                    cache,
                    provider,
                    base_url,
                    api_key,
                    model_id,
                    cap,
                    now=now,
                )
                cache_changed = True
        if cap is None:
            cap = _unknown_llm_model_capability()
        if _llm_capability_is_image_only(cap):
            continue
        if not _llm_capability_tags(cap):
            continue
        out.append(_LLMModelOption(model_id, cap))
    if cache_changed:
        _write_llm_capability_cache(cache)
    return out


class _LLMModelDiscoveryWorker(QObject):
    finished = Signal(list)
    failed = Signal(str, str)

    def __init__(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        *,
        detect_capability: bool = False,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._base_url = base_url
        self._api_key = api_key
        self._detect_capability = bool(detect_capability)

    def run(self) -> None:
        try:
            self.finished.emit(
                _fetch_llm_model_options(
                    self._provider,
                    self._base_url,
                    self._api_key,
                    detect_capability=self._detect_capability,
                )
            )
        except _LLMModelFetchError as e:
            self.failed.emit(str(e), e.detail)
        except Exception as e:
            self.failed.emit(str(e), "")


def _llm_provider_combo_display_order() -> list[str]:
    """
    LLM 下拉项 = :class:`~llm.llm_manager.LLMAdapterFactory` 合并后的全部 provider（含插件
    ``register_llm_adapter``）。仅对同时出现在 ``LLM_BASE_URLS`` 的条目保留常用顺序，其余按名排序。
    """
    adapters = dict(LLMAdapterFactory._adapters)
    out: list[str] = []
    for k in LLM_BASE_URLS.keys():
        if k in adapters:
            out.append(k)
    for k in sorted(adapters.keys()):
        if k not in out:
            out.append(k)
    return out


def _tts_canonical_slug(saved: str | None) -> str:
    s = (saved or "").strip().lower()
    if s in ("none", "off", "disable", "disabled", ""):
        return "none"
    for k in TTSAdapterFactory._adapters:
        if k.lower() == s:
            return k
    return (saved or "").strip().lower() or "none"


def _fill_tts_provider_combo(combo: QComboBox, saved_tts: str) -> None:
    combo.clear()
    combo.addItem(tr_i18n("api.tts.none"), "none")
    adapters = dict(TTSAdapterFactory._adapters)
    by_lower = {k.lower(): k for k in adapters}
    seen: set[str] = set()
    for slug, label in _TTS_LABEL_PREFS:
        sl = slug.lower()
        if sl in by_lower:
            ck = by_lower[sl]
            combo.addItem(label, ck)
            seen.add(ck)
    for ck in sorted(adapters.keys(), key=str.lower):
        if ck not in seen:
            combo.addItem(str(ck).replace("-", " ").title(), ck)
    canon = _tts_canonical_slug(saved_tts)
    if canon == "none":
        ix = combo.findData("none")
        combo.setCurrentIndex(max(0, ix))
        return
    ix = combo.findData(canon)
    if ix >= 0:
        combo.setCurrentIndex(ix)
    else:
        combo.addItem(canon, canon)
        combo.setCurrentIndex(combo.count() - 1)


def _t2i_engine_ordered_keys() -> list[str]:
    adapters = dict(T2IAdapterFactory._adapters)
    by_lower = {k.lower(): k for k in adapters}
    out: list[str] = []
    for pl in _PREFERRED_T2I_KEYS_LOWER:
        if pl in by_lower:
            out.append(by_lower[pl])
    for k in sorted(adapters.keys(), key=str.lower):
        if k not in out:
            out.append(k)
    return out


def _t2i_engine_combo_label(canonical_key: str) -> str:
    fixed = {"comfyui": "ComfyUI", "stable diffusion": "Stable Diffusion"}
    lk = canonical_key.lower()
    for k, lab in fixed.items():
        if k == lk:
            return lab
    return canonical_key.replace("-", " ").title()


def _t2i_engine_key_from_saved(saved: str | None) -> str:
    s = (saved or "").strip().lower()
    for k in T2IAdapterFactory._adapters:
        if k.lower() == s:
            return k
    return "comfyui"


def _fill_t2i_engine_combo(combo: QComboBox, saved: str) -> None:
    combo.clear()
    want = _t2i_engine_key_from_saved(saved)
    for ck in _t2i_engine_ordered_keys():
        combo.addItem(_t2i_engine_combo_label(ck), ck)
    ix = combo.findData(want)
    if ix >= 0:
        combo.setCurrentIndex(ix)
    else:
        combo.addItem(_t2i_engine_combo_label(want), want)
        combo.setCurrentIndex(combo.count() - 1)


def _tree_widget_item_depth(item: QTreeWidgetItem) -> int:
    """PySide6 的 QTreeWidgetItem 无 ``depth()``，用手工向上数父节点。"""
    d = 0
    p = item.parent()
    while p is not None:
        d += 1
        p = p.parent()
    return d


def _refresh_collapsible_tree_row_heights(tree: QTreeWidget) -> None:
    """QTreeWidget.setItemWidget 不会自动按内容增高行；需刷新 sizeHint 否则表单纵向挤成一团。"""
    vp_w = tree.viewport().width()
    if vp_w < 60:
        vp_w = max(tree.width() - 40, 320)
    for ti in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(ti)
        for ci in range(top.childCount()):
            child = top.child(ci)
            w = tree.itemWidget(child, 0)
            if w is None:
                continue
            lay = w.layout()
            margin = tree.indentation() * max(1, _tree_widget_item_depth(child))
            avail_w = max(vp_w - margin - 16, 200)
            w.setMinimumWidth(avail_w)
            w.resize(max(avail_w, 1), 8000)
            if lay is not None:
                lay.invalidate()
                lay.activate()
            h = w.sizeHint().height()
            if lay is not None:
                h = max(h, lay.minimumSize().height())
            h_final = max(int(h), 56)
            pad = 20
            child.setSizeHint(0, QSize(vp_w, h_final + pad))
            w.resize(avail_w, h_final)
            w.setMinimumHeight(h_final)
    tree.viewport().update()


def _add_collapsible_block(
    tree: QTreeWidget, title: str, content: QWidget, *, expanded: bool = False
) -> None:
    """在树中增加一项，展开后显示 content。"""
    top = QTreeWidgetItem([title])
    tree.addTopLevelItem(top)
    child = QTreeWidgetItem()
    top.addChild(child)
    content.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    tree.setItemWidget(child, 0, content)
    top.setExpanded(expanded)
    # 占满列宽、避免子行缩进过窄
    child.setFirstColumnSpanned(True)


class ApiSettingsTab(QWidget):
    def _asr_extra_schema_map(self) -> dict[str, type]:
        """当前进程内已合并的 ASR 后端（含插件 ``register_asr_adapter``）。"""
        return dict(ASRAdapterFactory._adapters)

    def _setup_asr_provider_combo(self, scfg) -> None:
        self._asr_provider.clear()
        self._asr_provider.addItem("Vosk", "vosk")
        _labels = {"faster_whisper": "faster-whisper", "realtime_stt": "RealtimeSTT"}
        for slug in sorted(k for k in ASRAdapterFactory._adapters.keys() if k != "vosk"):
            self._asr_provider.addItem(_labels.get(slug, slug), slug)
        prov = (scfg.asr_provider or "vosk").strip().lower().replace("-", "_")
        for i in range(self._asr_provider.count()):
            if str(self._asr_provider.itemData(i)) == prov:
                self._asr_provider.setCurrentIndex(i)
                break
        else:
            self._asr_provider.setCurrentIndex(0)

    def __init__(self, ctx: SettingsUIContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._llm_model_thread: QThread | None = None
        self._llm_model_worker: _LLMModelDiscoveryWorker | None = None
        self._llm_model_active_fetch_key: tuple[str, str, str] | None = None
        self._llm_model_fetched_key: tuple[str, str, str] | None = None
        self._build_ui()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_refresh_main_tree_heights()

    def eventFilter(self, obj, event) -> bool:
        if (
            hasattr(self, "llm_model")
            and obj is self.llm_model
            and event.type()
            in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.LayoutRequest,
                QEvent.Type.Polish,
            }
        ):
            QTimer.singleShot(0, self._position_llm_model_fetch_button)
        return super().eventFilter(obj, event)

    def _schedule_refresh_main_tree_heights(self) -> None:
        QTimer.singleShot(0, self._apply_main_tree_row_heights)

    def _apply_main_tree_row_heights(self) -> None:
        tree = getattr(self, "_main_tree", None)
        if tree is not None:
            _refresh_collapsible_tree_row_heights(tree)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        resume_row = QHBoxLayout()
        self._resume_chat_btn = QPushButton(tr_i18n("api.resume.btn"))
        self._resume_chat_btn.setToolTip(tr_i18n("api.resume.tip"))
        self._resume_chat_btn.clicked.connect(self._on_resume_last_chat)
        resume_row.addWidget(self._resume_chat_btn)
        resume_row.addStretch(1)
        root.addLayout(resume_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)

        self._lang_group = QGroupBox(tr_i18n("lang.group"))
        lgl = QVBoxLayout(self._lang_group)
        self._lang_hint = QLabel(tr_i18n("lang.hint"))
        self._lang_hint.setWordWrap(True)
        self._lang_combo = QComboBox()
        for label, code in (("简体中文", "zh_CN"), ("English", "en"), ("日本語", "ja")):
            self._lang_combo.addItem(label, code)
        _lc = normalize_lang(
            str(self._ctx.config_manager.config.system_config.ui_language)
        )
        self._lang_combo.setCurrentIndex(
            {"zh_CN": 0, "en": 1, "ja": 2}.get(_lc, 0)
        )
        self._lang_combo.activated.connect(self._on_language_activated)
        lgh = QHBoxLayout()
        lgh.addWidget(self._lang_combo)
        lgh.addStretch(1)
        lgl.addLayout(lgh)
        lgl.addWidget(self._lang_hint)
        lay.addWidget(self._lang_group)

        self._api_h2 = QLabel(tr_i18n("api.h2"))
        self._api_sub = QLabel(tr_i18n("api.subtitle"))
        self._api_sub.setObjectName("apiSettingsSubtitle")
        self._api_sub.setWordWrap(True)
        lay.addWidget(self._api_h2)
        lay.addWidget(self._api_sub)

        _provider, _model, _base_url, _api_key = self._ctx.config_manager.get_llm_api_config()
        _is_streaming = self._ctx.config_manager.config.api_config.is_streaming

        # --- 区块：LLM API ---
        llm_panel = QWidget()
        llm_outer = QVBoxLayout(llm_panel)
        llm_outer.setContentsMargins(0, 0, 0, 0)
        llm_outer.setSpacing(10)
        llm_fields = QWidget()
        llm_form = QFormLayout(llm_fields)
        llm_form.setContentsMargins(0, 0, 0, 0)
        llm_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        llm_form.setVerticalSpacing(10)
        self.llm_provider = QComboBox()
        self.llm_provider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.llm_provider.addItems(_llm_provider_combo_display_order())
        idx = self.llm_provider.findText(_provider)
        if idx >= 0:
            self.llm_provider.setCurrentIndex(idx)
        self.llm_model = QComboBox()
        self.llm_model.setEditable(True)
        self._llm_model_line_edit = _LLMModelLineEdit(self.llm_model)
        self.llm_model.setLineEdit(self._llm_model_line_edit)
        self.llm_model.installEventFilter(self)
        self.llm_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.llm_model.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._llm_model_delegate = _LLMModelCapabilityDelegate(self.llm_model.view())
        self.llm_model.view().setItemDelegate(self._llm_model_delegate)
        setattr(
            self.llm_model.view(),
            _COMBO_POPUP_HOVER_DELEGATE_ATTR,
            self._llm_model_delegate,
        )
        if _model:
            self.llm_model.addItem(_model, _model)
        self.llm_model.setEditText(_model)
        self._llm_model_line_edit.setPlaceholderText(tr_i18n("api.form.ph_model"))
        self._llm_model_fetch_btn = QPushButton()
        self._llm_model_fetch_btn.setObjectName("llmModelInlineFetchButton")
        self._llm_model_fetch_btn.setParent(self.llm_model)
        self._llm_model_fetch_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self._llm_model_fetch_btn.setText(tr_i18n("api.form.model_fetch_tip"))
        self._llm_model_fetch_btn.setToolTip(tr_i18n("api.form.model_fetch_tip"))
        self._llm_model_fetch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._llm_model_fetch_btn.setStyleSheet(_LLM_MODEL_FETCH_BUTTON_QSS)
        self._llm_model_fetch_btn.clicked.connect(self._on_fetch_llm_models)
        self._set_llm_model_fetch_button_visible(True)
        self.api_key = QLineEdit(_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText(tr_i18n("api.form.ph_key"))
        self.base_url = QLineEdit(_base_url)
        self.base_url.setPlaceholderText(tr_i18n("api.form.ph_base"))
        self.stream_yes = QRadioButton(tr_i18n("common.yes"))
        self.stream_no = QRadioButton(tr_i18n("common.no"))
        if _is_streaming:
            self.stream_yes.setChecked(True)
        else:
            self.stream_no.setChecked(True)
        stream_grp = QButtonGroup(self)
        stream_grp.addButton(self.stream_yes)
        stream_grp.addButton(self.stream_no)
        stream_row = QWidget()
        sr = QHBoxLayout(stream_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(self.stream_yes)
        sr.addWidget(self.stream_no)
        self._f_llm_provider = QLabel(tr_i18n("api.form.llm_provider"))
        self._f_base = QLabel(tr_i18n("api.form.base_url"))
        self._f_api_key = QLabel(tr_i18n("api.form.api_key"))
        self._f_model = QLabel(tr_i18n("api.form.model_id"))
        self._f_stream = QLabel(tr_i18n("api.form.stream"))
        llm_form.addRow(self._f_llm_provider, self.llm_provider)
        llm_form.addRow(self._f_base, self.base_url)
        llm_form.addRow(self._f_api_key, self.api_key)
        llm_form.addRow(self._f_model, self.llm_model)
        llm_form.addRow(self._f_stream, stream_row)
        self._llm_extra_holder = QWidget()
        self._llm_extra_holder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._llm_extra_layout = QVBoxLayout(self._llm_extra_holder)
        self._llm_extra_layout.setContentsMargins(0, 0, 0, 0)
        self._llm_extra_layout.setSpacing(12)
        llm_outer.addWidget(llm_fields)
        llm_outer.addWidget(self._llm_extra_holder)
        self._llm_extra_editors: dict[str, QWidget] = {}

        # --- 高级 LLM：双列表单节省纵向空间 ---
        adv = QWidget()
        adv_lay = QVBoxLayout(adv)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        self._adv_help = QLabel(tr_i18n("api.adv.help"))
        self._adv_help.setWordWrap(True)
        self._adv_help.setObjectName("apiSectionHint")
        self._adv_help.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        adv_lay.addWidget(self._adv_help)
        ac = self._ctx.config_manager.config.api_config
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setValue(float(ac.temperature))
        self.temperature.setToolTip(tr_i18n("api.adv.tt_temp"))
        self.repetition_penalty = QDoubleSpinBox()
        self.repetition_penalty.setRange(0.5, 2.0)
        self.repetition_penalty.setSingleStep(0.05)
        self.repetition_penalty.setValue(float(ac.repetition_penalty))
        self.repetition_penalty.setToolTip(tr_i18n("api.adv.tt_rep"))
        self.presence_penalty = QDoubleSpinBox()
        self.presence_penalty.setRange(-2.0, 2.0)
        self.presence_penalty.setSingleStep(0.05)
        self.presence_penalty.setValue(float(ac.presence_penalty))
        self.frequency_penalty = QDoubleSpinBox()
        self.frequency_penalty.setRange(-2.0, 2.0)
        self.frequency_penalty.setSingleStep(0.05)
        self.frequency_penalty.setValue(float(ac.frequency_penalty))
        self.max_context_tokens = QSpinBox()
        self.max_context_tokens.setRange(0, 2_000_000)
        self.max_context_tokens.setValue(int(ac.max_context_tokens))
        self.max_context_tokens.setToolTip(tr_i18n("api.adv.tt_maxctx"))
        self.compact_threshold = QDoubleSpinBox()
        self.compact_threshold.setRange(0.10, 0.95)
        self.compact_threshold.setSingleStep(0.05)
        self.compact_threshold.setValue(float(ac.compact_threshold))
        self.compact_threshold.setToolTip(tr_i18n("api.adv.tt_compact_threshold"))
        self.compact_target_ratio = QDoubleSpinBox()
        self.compact_target_ratio.setRange(0.05, 0.90)
        self.compact_target_ratio.setSingleStep(0.05)
        self.compact_target_ratio.setValue(float(ac.compact_target_ratio))
        self.compact_target_ratio.setToolTip(tr_i18n("api.adv.tt_compact_target"))
        self.compact_threshold.valueChanged.connect(self._sync_compact_target_bounds)
        self._sync_compact_target_bounds()
        self.history_recent_messages = QSpinBox()
        self.history_recent_messages.setRange(1, 200)
        self.history_recent_messages.setValue(int(ac.history_recent_messages))
        self.history_recent_messages.setToolTip(tr_i18n("api.adv.tt_history_recent"))
        self.max_tool_result_chars = QSpinBox()
        self.max_tool_result_chars.setRange(100, 200_000)
        self.max_tool_result_chars.setValue(int(ac.max_tool_result_chars))
        self.max_tool_result_chars.setToolTip(tr_i18n("api.adv.tt_tool_result"))
        self.max_active_tool_groups = QSpinBox()
        self.max_active_tool_groups.setRange(1, 20)
        self.max_active_tool_groups.setValue(int(ac.max_active_tool_groups))
        self.max_active_tool_groups.setToolTip(tr_i18n("api.adv.tt_tool_groups"))
        adv_2col = QHBoxLayout()
        adv_l = QFormLayout()
        adv_l.setContentsMargins(0, 0, 8, 0)
        self._adv_l_temp = QLabel(tr_i18n("api.adv.l_temp"))
        self._adv_l_presence = QLabel(tr_i18n("api.adv.l_presence"))
        self._adv_l_max = QLabel(tr_i18n("api.adv.l_maxctx"))
        self._adv_l_compact_threshold = QLabel(tr_i18n("api.adv.l_compact_threshold"))
        self._adv_l_history_recent = QLabel(tr_i18n("api.adv.l_history_recent"))
        self._adv_l_tool_groups = QLabel(tr_i18n("api.adv.l_tool_groups"))
        self._adv_l_rep = QLabel(tr_i18n("api.adv.l_rep"))
        self._adv_l_freq = QLabel(tr_i18n("api.adv.l_freq"))
        self._adv_l_compact_target = QLabel(tr_i18n("api.adv.l_compact_target"))
        self._adv_l_tool_result = QLabel(tr_i18n("api.adv.l_tool_result"))
        adv_l.addRow(self._adv_l_temp, self.temperature)
        adv_l.addRow(self._adv_l_presence, self.presence_penalty)
        adv_l.addRow(self._adv_l_max, self.max_context_tokens)
        adv_l.addRow(self._adv_l_compact_threshold, self.compact_threshold)
        adv_l.addRow(self._adv_l_history_recent, self.history_recent_messages)
        adv_l.addRow(self._adv_l_tool_groups, self.max_active_tool_groups)
        adv_r = QFormLayout()
        adv_r.setContentsMargins(0, 0, 0, 0)
        adv_r.addRow(self._adv_l_rep, self.repetition_penalty)
        adv_r.addRow(self._adv_l_freq, self.frequency_penalty)
        adv_r.addRow(self._adv_l_compact_target, self.compact_target_ratio)
        adv_r.addRow(self._adv_l_tool_result, self.max_tool_result_chars)
        adv_2col.addLayout(adv_l, stretch=1)
        adv_2col.addLayout(adv_r, stretch=1)
        adv_lay.addLayout(adv_2col)

        main_tree = QTreeWidget()
        main_tree.setColumnCount(1)
        main_tree.setHeaderHidden(True)
        main_tree.setAnimated(True)
        main_tree.setIndentation(18)
        main_tree.setMinimumHeight(220)
        main_tree.setUniformRowHeights(False)
        main_tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        main_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # 主题里 QTreeView 选中行会为粉红色；此处仅作分类折叠，不需要选中高亮。
        main_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.llm"), llm_panel, expanded=True)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.adv"), adv, expanded=False)

        _gsv_url, _gpt_sovits_work_path, _tts_provider = self._ctx.config_manager.get_gpt_sovits_config()
        tts_w = QWidget()
        tts_lay = QVBoxLayout(tts_w)
        tts_lay.setContentsMargins(0, 0, 0, 0)
        tts_dl_box = QWidget()
        tts_dl_lay = QVBoxLayout(tts_dl_box)
        tts_dl_lay.setContentsMargins(0, 0, 0, 0)
        self._tts_dl_short_hint = QLabel(tr_i18n("api.tts.env.inline_hint"))
        self._tts_dl_short_hint.setWordWrap(True)
        self._tts_dl_short_hint.setObjectName("apiSectionHint")
        self._tts_dl_btn = QPushButton(tr_i18n("api.tts.env.btn_dl"))
        self._tts_dl_btn.clicked.connect(self._on_tts_bundle_download)
        tdlh = QHBoxLayout()
        tdlh.setContentsMargins(0, 0, 0, 0)
        tdlh.addWidget(self._tts_dl_btn)
        tdlh.addStretch(1)
        tts_dl_lay.addWidget(self._tts_dl_short_hint)
        tts_dl_lay.addLayout(tdlh)
        tts_lay.addWidget(tts_dl_box)

        self._tts_hint = QLabel(tr_i18n("api.tts.hint"))
        self._tts_hint.setWordWrap(True)
        self._tts_hint.setObjectName("apiSectionHint")
        tts_lay.addWidget(self._tts_hint)
        self.tts_provider = QComboBox()
        self.tts_provider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        _fill_tts_provider_combo(self.tts_provider, _tts_provider)
        self.sovits_url = QLineEdit(_gsv_url)
        self.sovits_url.setPlaceholderText(tr_i18n("api.tts.ph_url"))
        self.gpt_sovits_api_path = QLineEdit(_gpt_sovits_work_path)
        self.gpt_sovits_api_path.setPlaceholderText(tr_i18n("api.tts.ph_path"))
        tts_fields = QWidget()
        tts_inner_form = QFormLayout(tts_fields)
        tts_inner_form.setContentsMargins(0, 0, 0, 0)
        tts_inner_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        tts_inner_form.setVerticalSpacing(10)
        self._tts_engine = QLabel(tr_i18n("api.tts.engine"))
        self._tts_url = QLabel(tr_i18n("api.tts.url"))
        self._tts_path = QLabel(tr_i18n("api.tts.path"))
        tts_inner_form.addRow(self._tts_engine, self.tts_provider)
        tts_inner_form.addRow(self._tts_url, self.sovits_url)
        tts_inner_form.addRow(self._tts_path, self.gpt_sovits_api_path)
        # TTS 分句开关
        api_cfg = self._ctx.config_manager.config.api_config
        self.tts_split_enabled = QCheckBox(tr_i18n("api.tts.split_enabled"))
        self.tts_split_enabled.setChecked(getattr(api_cfg, "tts_split_enabled", False))
        self.tts_max_sentence_length = QSpinBox()
        self.tts_max_sentence_length.setRange(5, 100)
        self.tts_max_sentence_length.setValue(getattr(api_cfg, "tts_max_sentence_length", 15))
        self.tts_max_sentence_length.setToolTip(tr_i18n("api.tts.max_sentence_length"))
        self._tts_split_len_label = QLabel(tr_i18n("api.tts.max_sentence_length"))
        tts_split_row = QHBoxLayout()
        tts_split_row.setContentsMargins(0, 0, 0, 0)
        tts_split_row.addWidget(self.tts_split_enabled)
        tts_split_row.addWidget(self._tts_split_len_label)
        tts_split_row.addWidget(self.tts_max_sentence_length)
        tts_split_row.addStretch(1)
        tts_split_w = QWidget()
        tts_split_w.setLayout(tts_split_row)
        tts_inner_form.addRow(tts_split_w)

        def _toggle_split_visibility(checked):
            self._tts_split_len_label.setVisible(checked)
            self.tts_max_sentence_length.setVisible(checked)
        self.tts_split_enabled.toggled.connect(_toggle_split_visibility)
        _toggle_split_visibility(self.tts_split_enabled.isChecked())
        self._tts_extra_holder = QWidget()
        self._tts_extra_holder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._tts_extra_layout = QVBoxLayout(self._tts_extra_holder)
        self._tts_extra_layout.setContentsMargins(0, 0, 0, 0)
        self._tts_extra_layout.setSpacing(12)
        self._tts_extra_editors: dict[str, QWidget] = {}

        tts_lay.addWidget(tts_fields)
        tts_lay.addWidget(self._tts_extra_holder)

        scfg = self._ctx.config_manager.config.system_config
        asr_w = QWidget()
        asr_ly = QVBoxLayout(asr_w)
        asr_ly.setContentsMargins(0, 0, 0, 0)
        asr_ly.setSpacing(10)
        self._asr_hint = QLabel(tr_i18n("api.asr.hint"))
        self._asr_hint.setWordWrap(True)
        self._asr_hint.setObjectName("apiSectionHint")
        asr_ly.addWidget(self._asr_hint)
        self._vosk_hint = QLabel(tr_i18n("api.asr.vosk_hint"))
        self._vosk_hint.setWordWrap(True)
        self._vosk_hint.setOpenExternalLinks(True)
        self._vosk_hint.setObjectName("apiSectionHint")
        self._vosk_hint.setVisible(True)
        asr_ly.addWidget(self._vosk_hint)
        asr_form = QFormLayout()
        asr_form.setContentsMargins(0, 0, 0, 0)
        asr_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        asr_form.setVerticalSpacing(10)
        self._asr_provider = QComboBox()
        self._asr_provider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._setup_asr_provider_combo(scfg)
        self._asr_language = QComboBox()
        self._asr_language.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._asr_language.addItem(tr_i18n("api.asr.follow_ui"), "")
        self._asr_language.addItem(tr_i18n("api.asr.lang_en"), "en")
        self._asr_language.addItem(tr_i18n("api.asr.lang_zh"), "zh")
        self._asr_language.addItem(tr_i18n("api.asr.lang_ja"), "ja")
        self._asr_language.addItem(tr_i18n("api.asr.lang_yue"), "yue")
        _asr_lang_saved = str(getattr(scfg, "asr_language", "") or "").strip()
        for i in range(self._asr_language.count()):
            d = self._asr_language.itemData(i)
            if ("" if d is None else str(d)) == _asr_lang_saved:
                self._asr_language.setCurrentIndex(i)
                break
        else:
            self._asr_language.setCurrentIndex(0)
        self._asr_whisper_model_combo = QComboBox()
        self._asr_whisper_model_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        for mid in _ASR_WHISPER_MODEL_PRESETS:
            self._asr_whisper_model_combo.addItem(mid, mid)
        self._asr_whisper_model_combo.addItem(
            tr_i18n("api.asr.model_custom"), "__custom__"
        )
        self._asr_whisper_model_custom = QLineEdit()
        self._asr_whisper_model_custom.setPlaceholderText(
            tr_i18n("api.asr.ph_model_custom")
        )
        self._asr_whisper_model_custom.setVisible(False)
        _raw_model = str(scfg.asr_whisper_model_size or "small").strip()
        _matched = False
        for i in range(self._asr_whisper_model_combo.count()):
            d = self._asr_whisper_model_combo.itemData(i)
            if d is None or str(d) == "__custom__":
                continue
            if str(d) == _raw_model:
                self._asr_whisper_model_combo.setCurrentIndex(i)
                _matched = True
                break
        if not _matched:
            last = self._asr_whisper_model_combo.count() - 1
            self._asr_whisper_model_combo.setCurrentIndex(last)
            self._asr_whisper_model_custom.setText(_raw_model)
            self._asr_whisper_model_custom.setVisible(True)
        self._asr_whisper_model_combo.currentIndexChanged.connect(
            self._on_asr_whisper_model_preset_changed
        )
        self._asr_model_row = QWidget()
        _mrow = QVBoxLayout(self._asr_model_row)
        _mrow.setContentsMargins(0, 0, 0, 0)
        _mrow.setSpacing(4)
        _mrow.addWidget(self._asr_whisper_model_combo)
        _mrow.addWidget(self._asr_whisper_model_custom)
        self._asr_device = QComboBox()
        self._asr_device.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._asr_device.addItem(tr_i18n("common.auto"), "auto")
        self._asr_device.addItem("CUDA", "cuda")
        self._asr_device.addItem("CPU", "cpu")
        dev = (scfg.asr_whisper_device or "auto").strip().lower()
        for i in range(self._asr_device.count()):
            if str(self._asr_device.itemData(i)) == dev:
                self._asr_device.setCurrentIndex(i)
                break
        else:
            self._asr_device.setCurrentIndex(0)
        self._asr_compute = QComboBox()
        self._asr_compute.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        _ct_saved = (scfg.asr_whisper_compute_type or "").strip()
        for lbl, dat in (
            (tr_i18n("api.asr.compute_auto"), ""),
            ("int8", "int8"),
            ("float16", "float16"),
            ("int8_float16", "int8_float16"),
            ("int16", "int16"),
            ("float32", "float32"),
        ):
            self._asr_compute.addItem(lbl, dat)
        _ct_idx = 0
        for i in range(self._asr_compute.count()):
            d = self._asr_compute.itemData(i)
            if ("" if d is None else str(d)) == _ct_saved:
                _ct_idx = i
                break
        else:
            if _ct_saved:
                self._asr_compute.addItem(_ct_saved, _ct_saved)
                _ct_idx = self._asr_compute.count() - 1
        self._asr_compute.setCurrentIndex(_ct_idx)
        self._f_asr_provider = QLabel(tr_i18n("api.asr.provider"))
        self._f_asr_language = QLabel(tr_i18n("api.asr.language"))
        self._f_asr_model = QLabel(tr_i18n("api.asr.whisper_model"))
        self._f_asr_dev = QLabel(tr_i18n("api.asr.device"))
        self._f_asr_ct = QLabel(tr_i18n("api.asr.compute_type"))
        asr_form.addRow(self._f_asr_provider, self._asr_provider)
        asr_form.addRow(self._f_asr_language, self._asr_language)
        self._asr_whisper_block = QWidget()
        _asr_wf = QFormLayout(self._asr_whisper_block)
        _asr_wf.setContentsMargins(0, 0, 0, 0)
        _asr_wf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        _asr_wf.setVerticalSpacing(10)
        _asr_wf.addRow(self._f_asr_model, self._asr_model_row)
        _asr_wf.addRow(self._f_asr_dev, self._asr_device)
        _asr_wf.addRow(self._f_asr_ct, self._asr_compute)
        asr_form.addRow(self._asr_whisper_block)
        self._asr_extra_holder = QWidget()
        self._asr_extra_holder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._asr_extra_layout = QVBoxLayout(self._asr_extra_holder)
        self._asr_extra_layout.setContentsMargins(0, 0, 0, 0)
        self._asr_extra_layout.setSpacing(12)
        self._asr_extra_editors: dict[str, QWidget] = {}
        self._update_asr_whisper_specific_visibility()
        asr_ly.addLayout(asr_form)
        asr_ly.addWidget(self._asr_extra_holder)

        api = self._ctx.config_manager.config.api_config
        comfy_w = QWidget()
        cvl = QVBoxLayout(comfy_w)
        cvl.setContentsMargins(0, 0, 0, 0)
        cvl.setSpacing(10)
        self._c_hint = QLabel(tr_i18n("api.comfy.hint"))
        self._c_hint.setWordWrap(True)
        self._c_hint.setObjectName("apiSectionHint")
        cvl.addWidget(self._c_hint)
        cf = QFormLayout()
        cf.setContentsMargins(0, 0, 0, 0)
        cf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        cf.setVerticalSpacing(10)
        self.t2i_engine = QComboBox()
        self.t2i_engine.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        _fill_t2i_engine_combo(
            self.t2i_engine, getattr(api, "t2i_provider", None) or "comfyui"
        )
        self._f_t2i_engine = QLabel(tr_i18n("api.comfy.engine"))
        self.t2i_url = QLineEdit(api.t2i_api_url)
        self.t2i_work_path = QLineEdit(api.t2i_work_path)
        self.t2i_default_workflow_path = QLineEdit(api.t2i_default_workflow_path)
        self.prompt_node_id = QLineEdit(api.t2i_prompt_node_id)
        self.output_node_id = QLineEdit(api.t2i_output_node_id)
        self.t2i_url.setPlaceholderText(tr_i18n("api.comfy.ph_t2i"))
        self._cf_t2i = QLabel(tr_i18n("api.comfy.t2i_url"))
        self._cf_dir = QLabel(tr_i18n("api.comfy.t2i_dir"))
        self._cf_wf = QLabel(tr_i18n("api.comfy.workflow"))
        self._cf_p = QLabel(tr_i18n("api.comfy.prompt_id"))
        self._cf_o = QLabel(tr_i18n("api.comfy.out_id"))
        cf.addRow(self._f_t2i_engine, self.t2i_engine)
        cf.addRow(self._cf_t2i, self.t2i_url)
        cf.addRow(self._cf_dir, self.t2i_work_path)
        cf.addRow(self._cf_wf, self.t2i_default_workflow_path)
        cf.addRow(self._cf_p, self.prompt_node_id)
        cf.addRow(self._cf_o, self.output_node_id)
        cvl.addLayout(cf)
        self._t2i_extra_holder = QWidget()
        self._t2i_extra_holder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._t2i_extra_layout = QVBoxLayout(self._t2i_extra_holder)
        self._t2i_extra_layout.setContentsMargins(0, 0, 0, 0)
        self._t2i_extra_layout.setSpacing(12)
        cvl.addWidget(self._t2i_extra_holder)
        self._t2i_extra_editors: dict[str, QWidget] = {}
        _add_collapsible_block(main_tree, tr_i18n("api.tree.tts"), tts_w, expanded=True)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.asr"), asr_w, expanded=False)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.comfy"), comfy_w, expanded=False)

        links_w = QWidget()
        links_ly = QVBoxLayout(links_w)
        links_ly.setContentsMargins(0, 0, 0, 0)
        self._links_title = QLabel(tr_i18n("api.links.title"))
        links_ly.addWidget(self._links_title)
        self._res_link_data = [
            ("api.links.link1", "https://github.com/RVC-Boss/GPT-SoVITS"),
            (
                "api.links.link2",
                "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604.7z",
            ),
            (
                "api.links.link3",
                "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604-nvidia50.7z",
            ),

            ("api.links.link4", "https://github.com/High-Logic/Genie-TTS"),
            (
                "api.links.link5",
                "https://www.modelscope.cn/models/twillzxy/genie-tts-server/resolve/master/Genie-TTS%20Server.7z",
            ),
        ]
        self._res_link_labels: list[QLabel] = []
        for key, url in self._res_link_data:
            lb = QLabel(f'<a href="{url}">{tr_i18n(key)}</a>')
            lb.setOpenExternalLinks(True)
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            self._res_link_labels.append(lb)
            links_ly.addWidget(lb)
        self._links_help = QLabel(tr_i18n("api.links.help"))
        self._links_help.setWordWrap(True)
        links_ly.addWidget(self._links_help)
        _add_collapsible_block(main_tree, tr_i18n("api.tree.resource"), links_w)

        self._main_tree = main_tree
        main_tree.itemExpanded.connect(lambda *_: self._schedule_refresh_main_tree_heights())
        main_tree.itemCollapsed.connect(lambda *_: self._schedule_refresh_main_tree_heights())
        lay.addWidget(main_tree, stretch=1)

        self.llm_provider.currentTextChanged.connect(self._on_provider_change)
        self.llm_model.editTextChanged.connect(self._on_model_text_changed)
        self.llm_model.currentIndexChanged.connect(
            self._refresh_llm_selected_capability_badges
        )
        self.base_url.textChanged.connect(self._on_llm_connection_fields_changed)
        self.api_key.textChanged.connect(self._on_llm_connection_fields_changed)
        self.tts_provider.currentIndexChanged.connect(self._on_tts_provider_changed)
        self.t2i_engine.currentIndexChanged.connect(self._on_t2i_engine_changed)
        self._asr_provider.currentIndexChanged.connect(self._on_asr_provider_changed)
        self._rebuild_llm_extra_panel()
        self._rebuild_tts_extra_panel()
        self._rebuild_asr_extra_panel()
        self._rebuild_t2i_extra_panel()
        root.addWidget(scroll, stretch=1)

        foot = QFrame()
        foot.setObjectName("apiTabFooter")
        foot.setFrameShape(QFrame.Shape.NoFrame)
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        fl.addWidget(sep)
        save_row = QHBoxLayout()
        save_row.setContentsMargins(12, 8, 12, 8)
        self._api_save = QPushButton(tr_i18n("api.save"))
        self._api_save.setMinimumWidth(160)
        self._api_save.setToolTip(tr_i18n("api.save_tip"))
        self._api_save.clicked.connect(self._on_save)
        save_row.addWidget(self._api_save)
        save_row.addStretch(1)
        fl.addLayout(save_row)
        root.addWidget(foot)

    def _sync_compact_target_bounds(self):
        if not hasattr(self, "compact_threshold") or not hasattr(self, "compact_target_ratio"):
            return
        max_target = max(0.05, float(self.compact_threshold.value()) - 0.05)
        self.compact_target_ratio.setMaximum(max_target)
        if self.compact_target_ratio.value() > max_target:
            self.compact_target_ratio.setValue(max_target)

    def _on_resume_last_chat(self) -> None:
        ok, msg = launch_chat_resume_last(self._ctx)
        if ok:
            toast_success(self, tr_i18n("api.resume.title"), msg)
        else:
            message_fail(self, tr_i18n("api.resume.title"), msg)

    def _on_language_activated(self, index: int) -> None:
        code = self._lang_combo.itemData(index) or "zh_CN"
        self._ctx.config_manager.set_ui_language(code)
        init_i18n(code)
        w = self.window()
        if w is not None and hasattr(w, "apply_i18n"):
            w.apply_i18n()

    def apply_i18n(self) -> None:
        self._resume_chat_btn.setText(tr_i18n("api.resume.btn"))
        self._resume_chat_btn.setToolTip(tr_i18n("api.resume.tip"))
        self._api_h2.setText(tr_i18n("api.h2"))
        self._api_sub.setText(tr_i18n("api.subtitle"))
        self._lang_group.setTitle(tr_i18n("lang.group"))
        self._lang_hint.setText(tr_i18n("lang.hint"))
        self._api_save.setText(tr_i18n("api.save"))
        self._api_save.setToolTip(tr_i18n("api.save_tip"))
        self._f_llm_provider.setText(tr_i18n("api.form.llm_provider"))
        self._f_model.setText(tr_i18n("api.form.model_id"))
        self._f_api_key.setText(tr_i18n("api.form.api_key"))
        self._f_base.setText(tr_i18n("api.form.base_url"))
        self._f_stream.setText(tr_i18n("api.form.stream"))
        if self.llm_model.lineEdit() is not None:
            self.llm_model.lineEdit().setPlaceholderText(tr_i18n("api.form.ph_model"))
        model_fetching = self._llm_model_thread is not None
        fetch_text = self._llm_model_fetch_button_text(model_fetching)
        self._llm_model_fetch_btn.setText(fetch_text)
        self._llm_model_fetch_btn.setToolTip(fetch_text)
        self._refresh_llm_model_display_labels()
        QTimer.singleShot(0, self._position_llm_model_fetch_button)
        self.api_key.setPlaceholderText(tr_i18n("api.form.ph_key"))
        self.base_url.setPlaceholderText(tr_i18n("api.form.ph_base"))
        self._adv_help.setText(tr_i18n("api.adv.help"))
        self.temperature.setToolTip(tr_i18n("api.adv.tt_temp"))
        self.repetition_penalty.setToolTip(tr_i18n("api.adv.tt_rep"))
        self.max_context_tokens.setToolTip(tr_i18n("api.adv.tt_maxctx"))
        self.compact_threshold.setToolTip(tr_i18n("api.adv.tt_compact_threshold"))
        self.compact_target_ratio.setToolTip(tr_i18n("api.adv.tt_compact_target"))
        self.history_recent_messages.setToolTip(tr_i18n("api.adv.tt_history_recent"))
        self.max_tool_result_chars.setToolTip(tr_i18n("api.adv.tt_tool_result"))
        self.max_active_tool_groups.setToolTip(tr_i18n("api.adv.tt_tool_groups"))
        self._adv_l_temp.setText(tr_i18n("api.adv.l_temp"))
        self._adv_l_rep.setText(tr_i18n("api.adv.l_rep"))
        self._adv_l_presence.setText(tr_i18n("api.adv.l_presence"))
        self._adv_l_freq.setText(tr_i18n("api.adv.l_freq"))
        self._adv_l_max.setText(tr_i18n("api.adv.l_maxctx"))
        self._adv_l_compact_threshold.setText(tr_i18n("api.adv.l_compact_threshold"))
        self._adv_l_compact_target.setText(tr_i18n("api.adv.l_compact_target"))
        self._adv_l_history_recent.setText(tr_i18n("api.adv.l_history_recent"))
        self._adv_l_tool_result.setText(tr_i18n("api.adv.l_tool_result"))
        self._adv_l_tool_groups.setText(tr_i18n("api.adv.l_tool_groups"))
        self._tts_hint.setText(tr_i18n("api.tts.hint"))
        self._tts_dl_short_hint.setText(tr_i18n("api.tts.env.inline_hint"))
        self._tts_dl_btn.setText(tr_i18n("api.tts.env.btn_dl"))
        self.sovits_url.setPlaceholderText(tr_i18n("api.tts.ph_url"))
        self.gpt_sovits_api_path.setPlaceholderText(tr_i18n("api.tts.ph_path"))
        self._tts_engine.setText(tr_i18n("api.tts.engine"))
        self._tts_url.setText(tr_i18n("api.tts.url"))
        self._tts_path.setText(tr_i18n("api.tts.path"))
        i_none = self.tts_provider.findData("none")
        if i_none >= 0:
            self.tts_provider.setItemText(i_none, tr_i18n("api.tts.none"))
        _cur_tts = self.tts_provider.currentData()
        _ti = self.tts_provider.findData(_cur_tts)
        if _ti >= 0:
            self.tts_provider.setCurrentIndex(_ti)
        self._c_hint.setText(tr_i18n("api.comfy.hint"))
        self._f_t2i_engine.setText(tr_i18n("api.comfy.engine"))
        self.t2i_url.setPlaceholderText(tr_i18n("api.comfy.ph_t2i"))
        self._cf_t2i.setText(tr_i18n("api.comfy.t2i_url"))
        self._cf_dir.setText(tr_i18n("api.comfy.t2i_dir"))
        self._cf_wf.setText(tr_i18n("api.comfy.workflow"))
        self._cf_p.setText(tr_i18n("api.comfy.prompt_id"))
        self._cf_o.setText(tr_i18n("api.comfy.out_id"))
        self._links_title.setText(tr_i18n("api.links.title"))
        for lb, (key, url) in zip(self._res_link_labels, self._res_link_data, strict=True):
            lb.setText(f'<a href="{url}">{tr_i18n(key)}</a>')
        self._links_help.setText(tr_i18n("api.links.help"))
        self.stream_yes.setText(tr_i18n("common.yes"))
        self.stream_no.setText(tr_i18n("common.no"))
        self._asr_hint.setText(tr_i18n("api.asr.hint"))
        self._vosk_hint.setText(tr_i18n("api.asr.vosk_hint"))
        self._f_asr_provider.setText(tr_i18n("api.asr.provider"))
        self._f_asr_language.setText(tr_i18n("api.asr.language"))
        _asr_lang_cur = self._asr_language.currentData()
        self._f_asr_model.setText(tr_i18n("api.asr.whisper_model"))
        self._f_asr_dev.setText(tr_i18n("api.asr.device"))
        self._f_asr_ct.setText(tr_i18n("api.asr.compute_type"))
        _lc_asr = self._asr_language.count()
        if _lc_asr >= 5:
            self._asr_language.setItemText(0, tr_i18n("api.asr.follow_ui"))
            self._asr_language.setItemText(1, tr_i18n("api.asr.lang_en"))
            self._asr_language.setItemText(2, tr_i18n("api.asr.lang_zh"))
            self._asr_language.setItemText(3, tr_i18n("api.asr.lang_ja"))
            self._asr_language.setItemText(4, tr_i18n("api.asr.lang_yue"))
        _asr_li = self._asr_language.findData(_asr_lang_cur)
        if _asr_li >= 0:
            self._asr_language.setCurrentIndex(_asr_li)
        lc = self._asr_whisper_model_combo.count() - 1
        if lc >= 0:
            self._asr_whisper_model_combo.setItemText(lc, tr_i18n("api.asr.model_custom"))
        self._asr_whisper_model_custom.setPlaceholderText(
            tr_i18n("api.asr.ph_model_custom")
        )
        self._asr_compute.setItemText(0, tr_i18n("api.asr.compute_auto"))
        self._asr_device.setItemText(0, tr_i18n("common.auto"))
        if self._main_tree and self._main_tree.topLevelItemCount() >= 6:
            _tree_keys = (
                "tree.llm",
                "tree.adv",
                "tree.tts",
                "tree.asr",
                "tree.comfy",
                "tree.resource",
            )
            for i, k in enumerate(_tree_keys):
                it = self._main_tree.topLevelItem(i)
                if it is not None:
                    it.setText(0, tr_i18n(f"api.{k}"))
        sidx = {"zh_CN": 0, "en": 1, "ja": 2}.get(
            normalize_lang(
                str(self._ctx.config_manager.config.system_config.ui_language)
            ),
            0,
        )
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentIndex(sidx)
        self._lang_combo.blockSignals(False)
        for w in QApplication.topLevelWidgets():
            if isinstance(w, TtsBundleDownloadDialog) and w.isVisible():
                w.apply_i18n()
        self._schedule_refresh_main_tree_heights()

    def _llm_model_text(self) -> str:
        text = self.llm_model.currentText().strip()
        idx = self.llm_model.currentIndex()
        if idx >= 0 and text == self.llm_model.itemText(idx):
            data = self.llm_model.itemData(idx)
            if isinstance(data, str) and data.strip():
                return data.strip()
        text_idx = self.llm_model.findText(text)
        if text_idx >= 0:
            data = self.llm_model.itemData(text_idx)
            if isinstance(data, str) and data.strip():
                return data.strip()
        return text

    def _refresh_llm_model_display_labels(self) -> None:
        view = self.llm_model.view()
        if view is not None and view.viewport() is not None:
            view.viewport().update()
        self._refresh_llm_selected_capability_badges()

    def _current_llm_model_capability(self) -> _LLMModelCapability | None:
        text = self.llm_model.currentText().strip()
        idx = self.llm_model.currentIndex()
        if idx >= 0 and text == self.llm_model.itemText(idx):
            cap = self.llm_model.itemData(idx, _LLM_CAPABILITY_ROLE)
            return cap if isinstance(cap, _LLMModelCapability) else None
        text_idx = self.llm_model.findText(text)
        if text_idx >= 0:
            cap = self.llm_model.itemData(text_idx, _LLM_CAPABILITY_ROLE)
            return cap if isinstance(cap, _LLMModelCapability) else None
        return None

    def _refresh_llm_selected_capability_badges(self, *_args) -> None:
        cap = self._current_llm_model_capability()
        tags = _llm_capability_tags(cap)
        line_edit = self.llm_model.lineEdit() if hasattr(self, "llm_model") else None
        if isinstance(line_edit, _LLMModelLineEdit):
            line_edit.set_capability_tags(tags)

    def _position_llm_model_fetch_button(self) -> None:
        btn = getattr(self, "_llm_model_fetch_btn", None)
        combo = getattr(self, "llm_model", None)
        if btn is None or combo is None or not btn.isVisible():
            return
        btn.adjustSize()
        hint = btn.sizeHint()
        width = min(max(34, hint.width()), max(34, combo.width() - 8))
        height = min(max(22, hint.height()), max(22, combo.height() - 6))
        x = max(2, combo.width() - width - 4)
        y = max(0, (combo.height() - height) // 2)
        btn.setGeometry(x, y, width, height)
        btn.raise_()
        line_edit = combo.lineEdit()
        if isinstance(line_edit, _LLMModelLineEdit):
            line_edit.set_action_reserved_width(width)

    def _set_llm_model_fetch_button_visible(self, visible: bool) -> None:
        self._llm_model_fetch_btn.setVisible(visible)
        self.llm_model.setStyleSheet(_LLM_MODEL_FETCH_MODE_QSS if visible else "")
        line_edit = self.llm_model.lineEdit()
        if isinstance(line_edit, _LLMModelLineEdit):
            width = self._llm_model_fetch_btn.sizeHint().width() if visible else 0
            line_edit.set_action_reserved_width(width)
        QTimer.singleShot(0, self._position_llm_model_fetch_button)

    def _current_llm_model_fetch_key(self) -> tuple[str, str, str]:
        return (
            self.llm_provider.currentText().strip(),
            self.base_url.text().strip(),
            self.api_key.text().strip(),
        )

    def _reset_llm_model_fetch_state(self) -> None:
        self._llm_model_fetched_key = None
        current = self._llm_model_text()
        self.llm_model.blockSignals(True)
        self.llm_model.clear()
        if current:
            self.llm_model.addItem(current, current)
            self.llm_model.setEditText(current)
        self.llm_model.blockSignals(False)
        self._refresh_llm_selected_capability_badges()
        self._set_llm_model_fetch_button_visible(True)
        self._set_llm_model_fetching(self._llm_model_thread is not None)

    def _on_llm_connection_fields_changed(self, *_args) -> None:
        self._reset_llm_model_fetch_state()

    def _set_llm_model_text(self, model: str) -> None:
        text = (model or "").strip()
        if not text:
            self.llm_model.setEditText("")
            return
        data_idx = self.llm_model.findData(text)
        if data_idx >= 0:
            self.llm_model.setCurrentIndex(data_idx)
            return
        text_idx = self.llm_model.findText(text)
        if text_idx >= 0:
            self.llm_model.setCurrentIndex(text_idx)
            return
        self.llm_model.addItem(text, text)
        self.llm_model.setEditText(text)

    def _set_llm_model_candidates(self, models: list[str | _LLMModelOption]) -> None:
        current = self._llm_model_text()
        self.llm_model.blockSignals(True)
        self.llm_model.clear()
        for item in models:
            if isinstance(item, _LLMModelOption):
                self.llm_model.addItem(item.model_id, item.model_id)
                row = self.llm_model.count() - 1
                self.llm_model.setItemData(row, item.capability, _LLM_CAPABILITY_ROLE)
            else:
                model_id = str(item or "").strip()
                if model_id:
                    self.llm_model.addItem(model_id, model_id)
        if current:
            data_idx = self.llm_model.findData(current)
            if data_idx >= 0:
                self.llm_model.setCurrentIndex(data_idx)
            else:
                self.llm_model.setEditText(current)
        elif models:
            self.llm_model.setCurrentIndex(0)
        self.llm_model.blockSignals(False)
        self._refresh_llm_model_display_labels()
        self._on_model_text_changed(self._llm_model_text())

    def _on_asr_whisper_model_preset_changed(self, _index: int = 0) -> None:
        data = self._asr_whisper_model_combo.currentData()
        is_custom = data is not None and str(data) == "__custom__"
        self._asr_whisper_model_custom.setVisible(is_custom)
        self._schedule_refresh_main_tree_heights()

    def _asr_whisper_model_config_value(self) -> str:
        data = self._asr_whisper_model_combo.currentData()
        if data is not None and str(data) == "__custom__":
            t = self._asr_whisper_model_custom.text().strip()
            return t if t else "small"
        return str(data or "small")

    def _asr_whisper_compute_config_value(self) -> str:
        d = self._asr_compute.currentData()
        return "" if d is None else str(d)

    def _on_provider_change(self, name: str) -> None:
        try:
            base, model, key = self._ctx.config_manager.update_llm_info(name)
        except Exception as e:
            self._reset_llm_model_fetch_state()
            message_fail(
                self,
                tr_i18n("api.msg.config"),
                tr_i18n("api.msg.provider_fail").format(e=e),
            )
            return
        self.base_url.setText(base)
        self.llm_model.clear()
        self._set_llm_model_text(model)
        self._refresh_llm_selected_capability_badges()
        self.api_key.setText(key)
        self._reset_llm_model_fetch_state()
        self._rebuild_llm_extra_panel()
        self._update_thinking_ui()

    _NO_THINKING_MODELS = frozenset({"deepseek-v4-flash", "deepseek-chat"})

    def _on_model_text_changed(self, text: str) -> None:
        self._update_thinking_ui()
        self._refresh_llm_selected_capability_badges()

    def _llm_model_fetch_button_text(self, fetching: bool) -> str:
        if not fetching:
            return tr_i18n("api.form.model_fetch_tip")
        return tr_i18n("api.form.model_fetching")

    def _set_llm_model_fetching(self, fetching: bool) -> None:
        self._llm_model_fetch_btn.setEnabled(not fetching)
        fetch_text = self._llm_model_fetch_button_text(fetching)
        self._llm_model_fetch_btn.setText(fetch_text)
        self._llm_model_fetch_btn.setToolTip(fetch_text)
        QTimer.singleShot(0, self._position_llm_model_fetch_button)

    def _on_fetch_llm_models(self) -> None:
        provider = self.llm_provider.currentText().strip()
        base_url = self.base_url.text().strip()
        api_key = self.api_key.text().strip()
        if not base_url or not api_key:
            message_fail(
                self,
                tr_i18n("api.msg.config"),
                tr_i18n("api.msg.model_fetch_missing"),
            )
            return
        if self._llm_model_thread is not None:
            return

        fetch_key = self._current_llm_model_fetch_key()
        self._llm_model_active_fetch_key = fetch_key
        self._set_llm_model_fetching(True)
        thread = QThread(self)
        worker = _LLMModelDiscoveryWorker(
            provider,
            base_url,
            api_key,
            detect_capability=True,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_llm_models_fetched)
        worker.failed.connect(self._on_llm_models_fetch_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_llm_models_fetch_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._llm_model_thread = thread
        self._llm_model_worker = worker
        thread.start()

    def _on_llm_models_fetched(self, models: list[str | _LLMModelOption]) -> None:
        fetch_key = self._llm_model_active_fetch_key
        if fetch_key != self._current_llm_model_fetch_key():
            return
        if not models:
            self._llm_model_fetched_key = None
            self._set_llm_model_fetch_button_visible(True)
            message_fail(
                self,
                tr_i18n("api.msg.config"),
                tr_i18n("api.msg.model_fetch_empty"),
            )
            return
        self._llm_model_fetched_key = fetch_key
        self._set_llm_model_candidates(models)
        self._set_llm_model_fetch_button_visible(False)
        message_info(
            self,
            tr_i18n("api.msg.config"),
            tr_i18n("api.msg.model_fetch_done").format(count=len(models)),
        )

    def _on_llm_models_fetch_failed(self, error: str, detail: str = "") -> None:
        if self._llm_model_active_fetch_key != self._current_llm_model_fetch_key():
            return
        self._llm_model_fetched_key = None
        self._set_llm_model_fetch_button_visible(True)
        message_fail(
            self,
            tr_i18n("api.msg.config"),
            tr_i18n("api.msg.model_fetch_failed").format(e=error),
            details=detail,
        )

    def _on_llm_models_fetch_thread_finished(self) -> None:
        self._llm_model_thread = None
        self._llm_model_worker = None
        self._llm_model_active_fetch_key = None
        self._set_llm_model_fetching(False)
        self._set_llm_model_fetch_button_visible(
            self._llm_model_fetched_key != self._current_llm_model_fetch_key()
        )

    def _update_thinking_ui(self) -> None:
        """deepseek-v4-flash / deepseek-chat 不支持思考模式，禁用控件并取消勾选。"""
        model = self._llm_model_text().lower()
        w = self._llm_extra_editors.get("thinking_enabled")
        if w is None or not isinstance(w, (QCheckBox,)):
            return
        if model in self._NO_THINKING_MODELS:
            w.setChecked(False)
            w.setEnabled(False)
            w.setToolTip(tr_i18n("api.msg.thinking_unsupported"))
        else:
            w.setEnabled(True)
            w.setToolTip("")

    def _clear_extra_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild_llm_extra_panel(self) -> None:
        self._clear_extra_layout(self._llm_extra_layout)
        self._llm_extra_editors.clear()
        name = self.llm_provider.currentText()
        cls = LLMAdapterFactory._adapters.get(name)
        schema = cls.get_config_schema() if cls else {}
        if not schema:
            self._llm_extra_holder.setVisible(False)
            self._schedule_refresh_main_tree_heights()
            return
        self._llm_extra_holder.setVisible(True)
        vals = self._ctx.config_manager.get_adapter_extra_config("llm", name)
        panel, eds = build_schema_widgets(schema, vals, self._llm_extra_holder)
        self._llm_extra_layout.addWidget(panel)
        self._llm_extra_editors = eds
        self._update_thinking_ui()
        self._schedule_refresh_main_tree_heights()

    def _rebuild_tts_extra_panel(self) -> None:
        self._clear_extra_layout(self._tts_extra_layout)
        self._tts_extra_editors.clear()
        raw = self.tts_provider.currentData()
        slug = str(raw or "").strip().lower()
        if slug in ("none", ""):
            self._tts_extra_holder.setVisible(False)
            self._schedule_refresh_main_tree_heights()
            return
        cls = TTSAdapterFactory._adapters.get(slug)
        schema = cls.get_config_schema() if cls else {}
        if not schema:
            self._tts_extra_holder.setVisible(False)
            self._schedule_refresh_main_tree_heights()
            return
        self._tts_extra_holder.setVisible(True)
        vals = self._ctx.config_manager.get_adapter_extra_config("tts", slug)
        panel, eds = build_schema_widgets(schema, vals, self._tts_extra_holder)
        self._tts_extra_layout.addWidget(panel)
        self._tts_extra_editors = eds
        self._schedule_refresh_main_tree_heights()

    def _rebuild_asr_extra_panel(self) -> None:
        self._clear_extra_layout(self._asr_extra_layout)
        self._asr_extra_editors.clear()
        key = normalize_asr_provider_storage_key(
            str(self._asr_provider.currentData() or "vosk")
        )
        cls = self._asr_extra_schema_map().get(key)
        schema = cls.get_config_schema() if cls else {}
        if not schema:
            self._asr_extra_holder.setVisible(False)
            self._schedule_refresh_main_tree_heights()
            return
        self._asr_extra_holder.setVisible(True)
        vals = self._ctx.config_manager.get_adapter_extra_config("asr", key)
        panel, eds = build_schema_widgets(schema, vals, self._asr_extra_holder)
        self._asr_extra_layout.addWidget(panel)
        self._asr_extra_editors = eds
        self._schedule_refresh_main_tree_heights()

    def _rebuild_t2i_extra_panel(self) -> None:
        self._clear_extra_layout(self._t2i_extra_layout)
        self._t2i_extra_editors.clear()
        key = self._current_t2i_engine_key()
        cls = T2IAdapterFactory._adapters.get(key.lower())
        schema = cls.get_config_schema() if cls else {}
        if not schema:
            self._t2i_extra_holder.setVisible(False)
            self._schedule_refresh_main_tree_heights()
            return
        self._t2i_extra_holder.setVisible(True)
        vals = self._ctx.config_manager.get_adapter_extra_config("t2i", key)
        panel, eds = build_schema_widgets(schema, vals, self._t2i_extra_holder)
        self._t2i_extra_layout.addWidget(panel)
        self._t2i_extra_editors = eds
        self._schedule_refresh_main_tree_heights()

    def _current_t2i_engine_key(self) -> str:
        d = self.t2i_engine.currentData()
        return str(d) if d is not None else "comfyui"

    def _on_t2i_engine_changed(self, _index: int = 0) -> None:
        self._rebuild_t2i_extra_panel()

    def _on_tts_provider_changed(self, _index: int = 0) -> None:
        self._rebuild_tts_extra_panel()

    def _on_asr_provider_changed(self, _index: int = 0) -> None:
        self._update_asr_whisper_specific_visibility()
        self._rebuild_asr_extra_panel()

    def _update_asr_whisper_specific_visibility(self) -> None:
        """Whisper 模型/设备/精度仅适用于 faster-whisper 与 RealtimeSTT。"""
        key = normalize_asr_provider_storage_key(
            str(self._asr_provider.currentData() or "vosk")
        )
        is_vosk = key == "vosk"
        self._asr_whisper_block.setVisible(not is_vosk)
        self._vosk_hint.setVisible(is_vosk)

    def _on_tts_bundle_download(self) -> None:
        dlg = TtsBundleDownloadDialog(
            self,
            gpt_sovits_api_path=self.gpt_sovits_api_path,
            tts_provider=self.tts_provider,
        )
        dlg.exec()

    def _on_save(self) -> None:
        from sdk.ui.validators import not_empty, no_quotes, validate_or_block, valid_url, dir_exists
        if not validate_or_block(
            not_empty(self.base_url.text().strip(), tr_i18n("api.form.base_url")),
            no_quotes(self.base_url.text().strip(), tr_i18n("api.form.base_url")),
            not_empty(self.api_key.text().strip(), tr_i18n("api.form.api_key")),
            not_empty(self._llm_model_text(), tr_i18n("api.form.model_id")),
            title=tr_i18n("api.msg.validation_title"),
            parent=self,
        ):
            return

        tts_slug = self.tts_provider.currentData()
        if tts_slug is None:
            tts_slug = "gpt-sovits"
        tts_slug = str(tts_slug).strip().lower()

        if tts_slug in ("gpt-sovits", "genie-tts"):
            if not validate_or_block(
                not_empty(self.sovits_url.text().strip(), tr_i18n("api.tts.url")),
                no_quotes(self.sovits_url.text().strip(), tr_i18n("api.tts.url")),
                valid_url(self.sovits_url.text().strip(), tr_i18n("api.tts.url")),
                not_empty(self.gpt_sovits_api_path.text().strip(), tr_i18n("api.tts.path")),
                no_quotes(self.gpt_sovits_api_path.text().strip(), tr_i18n("api.tts.path")),
                dir_exists(self.gpt_sovits_api_path.text().strip(), tr_i18n("api.tts.path")),
                title=tr_i18n("api.msg.validation_title"),
                parent=self,
            ):
                return

        is_streaming = "是" if self.stream_yes.isChecked() else "否"
        llm_prov = self.llm_provider.currentText()
        llm_cls = LLMAdapterFactory._adapters.get(llm_prov)
        llm_schema = llm_cls.get_config_schema() if llm_cls else {}
        self._ctx.config_manager.set_adapter_extra_config(
            "llm", llm_prov, read_schema_values(llm_schema, self._llm_extra_editors)
        )

        tts_cls = (
            TTSAdapterFactory._adapters.get(tts_slug)
            if tts_slug not in ("none", "")
            else None
        )
        tts_schema = tts_cls.get_config_schema() if tts_cls else {}
        self._ctx.config_manager.set_adapter_extra_config(
            "tts", tts_slug, read_schema_values(tts_schema, self._tts_extra_editors)
        )

        asr_key = normalize_asr_provider_storage_key(
            str(self._asr_provider.currentData() or "vosk")
        )
        asr_cls = self._asr_extra_schema_map().get(asr_key)
        asr_schema = asr_cls.get_config_schema() if asr_cls else {}
        self._ctx.config_manager.set_adapter_extra_config(
            "asr", asr_key, read_schema_values(asr_schema, self._asr_extra_editors)
        )

        t2i_key = self._current_t2i_engine_key()
        t2i_cls = T2IAdapterFactory._adapters.get(t2i_key.lower())
        t2i_schema = t2i_cls.get_config_schema() if t2i_cls else {}
        self._ctx.config_manager.set_adapter_extra_config(
            "t2i", t2i_key, read_schema_values(t2i_schema, self._t2i_extra_editors)
        )

        msg = self._ctx.config_manager.save_api_config_new(
            self.llm_provider.currentText(),
            self._llm_model_text(),
            self.api_key.text(),
            self.base_url.text().strip(),
            is_streaming,
            tts_slug,
            self.sovits_url.text().strip(),
            self.gpt_sovits_api_path.text().strip(),
            self._current_t2i_engine_key(),
            self.t2i_url.text().strip(),
            self.t2i_work_path.text().strip(),
            self.t2i_default_workflow_path.text().strip(),
            self.prompt_node_id.text().strip(),
            self.output_node_id.text().strip(),
            self.temperature.value(),
            self.repetition_penalty.value(),
            self.presence_penalty.value(),
            self.frequency_penalty.value(),
            self.max_context_tokens.value(),
            self.tts_split_enabled.isChecked(),
            self.tts_max_sentence_length.value(),
            self.compact_threshold.value(),
            self.compact_target_ratio.value(),
            self.history_recent_messages.value(),
            self.max_tool_result_chars.value(),
            self.max_active_tool_groups.value(),
        )
        prov = str(self._asr_provider.currentData() or "vosk")
        dev = str(self._asr_device.currentData() or "auto")
        _asr_lang_data = self._asr_language.currentData()
        _asr_lang_val = (
            "" if _asr_lang_data is None else str(_asr_lang_data).strip()
        )
        sc_new = self._ctx.config_manager.config.system_config.model_copy(
            update={
                "asr_provider": prov,
                "asr_language": _asr_lang_val,
                "asr_whisper_model_size": self._asr_whisper_model_config_value(),
                "asr_whisper_device": dev,
                "asr_whisper_compute_type": self._asr_whisper_compute_config_value(),
            }
        )
        self._ctx.config_manager.config.system_config = sc_new
        self._ctx.config_manager.save_system_config()
        msg = f"{msg}\n{tr_i18n('api.asr.saved_suffix')}"
        feedback_result(self, tr_i18n("api.msg.config"), msg)
