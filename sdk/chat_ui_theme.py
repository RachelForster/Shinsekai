"""chat_ui 主题 mod SDK —— 主题清单的权威模型、校验器与打包/读取工具。

这是"自定义 chat_ui 样式"的**单一事实来源**：bridge 安装上传主题时调用本模块校验，
主题作者也可用本模块在本地校验/打包：

    python -m sdk.chat_ui_theme validate ./my-theme
    python -m sdk.chat_ui_theme pack ./my-theme -o my-theme.zip

设计原则（与前端 ``chatChromeTheme.ts`` / ``chatTheme.ts`` 规则保持一致）：
- 主题 = **令牌 + 资源，无可执行代码**（只有 JSON + 图片/字体/音效）。
- 禁止破坏布局的 CSS 声明（width/height/position/font-size 等）。
- 资源只能引用主题目录内的相对路径（沙箱），禁止 ``..`` / 绝对路径 / 网络 URL。

仅依赖标准库，可在最小环境运行。
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sdk.archive_paths import (
    UnsafeArchiveError,
    extract_zip_safely,
    write_directory_to_zip_without_links,
)
from sdk.file_transactions import (
    atomic_binary_writer,
    file_snapshot_is_stable,
    inspect_portable_directory_tree,
    open_binary_read_without_links,
    read_text_snapshot_without_links,
)
from sdk.path_contract import (
    path_is_within,
    project_root,
    require_symlink_free_absolute_path,
    resolve_managed_project_path,
    resolve_project_output_path,
    safe_path_component,
    validate_exact_path_text,
)

#: manifest schema 版本，与前端 ``CHAT_THEME_SCHEMA`` 一致。
CHAT_THEME_SCHEMA = 1

#: 主题清单文件名。
MANIFEST_NAME = "theme.json"

#: 资源子目录名（沙箱根）。
ASSETS_DIR = "assets"

#: 每个可视化块允许的属性。
ALLOWED_VISUAL_PROPS = frozenset(
    {
        "background",
        "backgroundImage",
        "borderColor",
        "borderRadius",
        "boxShadow",
        "color",
        # schema=1 historically accepted these on every visual block. Keep accepting
        # them for installed-theme compatibility; unsupported UI blocks ignore them.
        "frameImage",
        "frameSlice",
        "padding",
    }
)

#: 仅具有独立边框层的低密度外壳允许的九宫格边框字段。
FRAME_VISUAL_PROPS = frozenset({"frameOutsetPx", "frameWidthPx"})
FRAME_TOKEN_BLOCKS = frozenset({"dialog", "options", "input", "toolbar", "name"})
LOG_FRAME_VISUAL_BLOCKS = frozenset({"panel", "sidebar", "toolbar", "viewer"})

#: 每个可写 token 块允许的额外字段（在可视化属性之外）。
EXTRA_BLOCK_PROPS = {
    "dialog": frozenset(
        {
            "chrome",
            "heightPx",
            "nameInputGapVh",
            "widthPct",
            "offsetY",
            "textAlign",
            "textShadow",
            "textSizePx",
            "textWeight",
        }
    ),
    "fileItem": frozenset({"active", "hover"}),
    "options": frozenset(
        {
            "active",
            "gap",
            "hover",
            "icon",
            "maxWidthVw",
            "minHeightPx",
            "minHeightVh",
            "minWidthVw",
            "nameClearanceVh",
            "placement",
            "textShadow",
            "textSizeVh",
            "textSizePx",
            "textWeight",
            "widthPx",
            "widthMode",
        }
    ),
    "input": frozenset({"fieldBackground", "fieldBorderRadius", "layout", "maxWidthPx", "sendPlacement"}),
    "line": frozenset({"expanded", "hover"}),
    "name": frozenset(
        {
            "align",
            "decoration",
            "fontFamily",
            "hideWhenStartOption",
            "overlapPx",
            "textShadow",
            "textSizePx",
            "textWeight",
        }
    ),
    "toolbar": frozenset({"placement", "reveal"}),
}

#: tokens 顶层允许的块名（= 统一设计规范的全集）。
ALLOWED_TOKEN_BLOCKS = frozenset(
    {"global", "fonts", "dialog", "options", "input", "toolbar", "send", "name", "logs", "typewriter"}
)

LOG_VISUAL_BLOCKS = frozenset(
    {
        "badge",
        "detail",
        "event",
        "number",
        "page",
        "panel",
        "sidebar",
        "source",
        "toolbar",
        "viewer",
    }
)
LOG_LEVEL_BLOCKS = frozenset({"debug", "default", "error", "info", "warn"})

#: 引用资源的字段（值必须是沙箱内相对路径）。
ASSET_REF_FIELDS = ("backgroundImage", "frameImage", "sound", "src", "preview")

#: 禁止出现在任何字符串值里的破坏布局/注入声明（与 theme_chrome._FORBIDDEN_DECL 同源）。
_FORBIDDEN_VALUE = re.compile(
    r"(?i)\b(width|height|min-width|max-width|min-height|max-height|"
    r"position|left|right|top|bottom|font-size)\s*:"
)

#: 数值字段的取值范围（clamp）。
NUMERIC_BOUNDS = {
    "padding": (8, 72),
    "widthPct": (30, 100),
    "heightPx": (96, 260),
    "nameInputGapVh": (12, 32),
    "offsetY": (-240, 240),
    "gap": (0, 36),
    "cps": (1, 200),
    "frameSlice": (1, 200),
    "frameWidthPx": (0, 96),
    "frameOutsetPx": (0, 96),
    "minHeightPx": (36, 96),
    "minHeightVh": (3, 8),
    "minWidthVw": (12, 42),
    "maxWidthVw": (20, 60),
    "maxWidthPx": (320, 900),
    "nameClearanceVh": (2, 12),
    "overlapPx": (0, 48),
    "textSizeVh": (1, 4),
    "textSizePx": (12, 64),
    "textWeight": (300, 900),
    "widthPx": (260, 720),
}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass
class ThemeValidationResult:
    """校验结果。``ok`` 为 ``True`` 时 ``normalized`` 为可安全使用的 manifest。"""

    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    normalized: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #

def slugify_theme_id(value: str) -> str:
    """把任意字符串规整成可移植的合法主题目录 id。"""
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    slug = slug[:64] or "theme"
    try:
        safe_path_component(slug, field="theme id")
    except ValueError:
        # Windows device aliases (for example CON and LPT1) satisfy the theme
        # id grammar but cannot be directory names.  Keep slugification
        # deterministic while moving the identifier out of that namespace.
        slug = f"theme-{slug}"[:64]
    return slug


def _is_safe_asset_ref(value: str) -> bool:
    """资源引用必须是沙箱内相对路径。"""
    if (
        not value
        or not isinstance(value, str)
        or value != value.strip()
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
    ):
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value):  # 含 scheme（http:/file:/data: 等）
        return False
    if value.startswith("/") or value.startswith("\\"):
        return False
    parts = value.replace("\\", "/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    try:
        for part in parts:
            safe_path_component(part, field="theme asset path component")
    except ValueError:
        return False
    return True


def _is_safe_css_value(value: str) -> bool:
    """字符串 CSS 值不得包含禁用声明、花括号/分号注入或 url()（资源只能走 assetRef 字段）。"""
    if not isinstance(value, str):
        return False
    if "{" in value or "}" in value or ";" in value:
        return False
    if re.search(r"(?i)url\s*\(", value):
        return False
    if _FORBIDDEN_VALUE.search(value):
        return False
    return True


def _validate_visual_block(
    name: str,
    block: Any,
    errors: List[str],
    allowed_extra: frozenset,
    allow_frame: bool = False,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(block, dict):
        errors.append(f"tokens.{name} 必须是对象")
        return out
    allowed_visual_props = ALLOWED_VISUAL_PROPS | FRAME_VISUAL_PROPS if allow_frame else ALLOWED_VISUAL_PROPS
    for key, value in block.items():
        if key in allowed_visual_props:
            if key in {"backgroundImage", "frameImage"}:
                if isinstance(value, str) and _is_safe_asset_ref(value):
                    out[key] = value
                else:
                    errors.append(f"tokens.{name}.{key} 必须是主题目录内相对路径")
            elif key == "padding":
                out[key] = _clamp_numeric("padding", value, errors, f"tokens.{name}.padding")
            elif key in {"frameSlice", "frameWidthPx", "frameOutsetPx"}:
                out[key] = _clamp_numeric(key, value, errors, f"tokens.{name}.{key}")
            elif isinstance(value, str) and _is_safe_css_value(value):
                out[key] = value
            else:
                errors.append(f"tokens.{name}.{key} 值非法或包含禁用声明: {value!r}")
        elif key in allowed_extra:
            pass  # 额外字段在下方按语义单独校验
        else:
            errors.append(f"tokens.{name}.{key} 不是规范允许的字段")
    return out


def _validate_logs_block(block: Any, errors: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(block, dict):
        errors.append("tokens.logs 必须是对象")
        return out

    allowed = LOG_VISUAL_BLOCKS | {"code", "fileItem", "levels", "line"}
    for key in block:
        if key not in allowed:
            errors.append(f"tokens.logs.{key} 不是规范允许的字段")

    for key in LOG_VISUAL_BLOCKS:
        if key in block:
            out[key] = _validate_visual_block(
                f"logs.{key}",
                block[key],
                errors,
                frozenset(),
                allow_frame=key in LOG_FRAME_VISUAL_BLOCKS,
            )

    if "code" in block:
        code = _validate_visual_block("logs.code", block["code"], errors, frozenset({"fontFamily"}))
        font_family = block["code"].get("fontFamily") if isinstance(block["code"], dict) else None
        if font_family is not None:
            if isinstance(font_family, str) and _is_safe_css_value(font_family):
                code["fontFamily"] = font_family
            else:
                errors.append("tokens.logs.code.fontFamily 非法")
        out["code"] = code

    if "fileItem" in block:
        file_item = _validate_visual_block("logs.fileItem", block["fileItem"], errors, EXTRA_BLOCK_PROPS["fileItem"])
        raw = block["fileItem"] if isinstance(block["fileItem"], dict) else {}
        for nested in ("active", "hover"):
            if nested in raw:
                file_item[nested] = _validate_visual_block(
                    f"logs.fileItem.{nested}", raw[nested], errors, frozenset()
                )
        out["fileItem"] = file_item

    if "line" in block:
        line = _validate_visual_block("logs.line", block["line"], errors, EXTRA_BLOCK_PROPS["line"])
        raw = block["line"] if isinstance(block["line"], dict) else {}
        for nested in ("expanded", "hover"):
            if nested in raw:
                line[nested] = _validate_visual_block(
                    f"logs.line.{nested}", raw[nested], errors, frozenset()
                )
        out["line"] = line

    if "levels" in block:
        levels = block["levels"]
        level_out: Dict[str, Any] = {}
        if not isinstance(levels, dict):
            errors.append("tokens.logs.levels 必须是对象")
        else:
            for level, value in levels.items():
                if level not in LOG_LEVEL_BLOCKS:
                    errors.append(f"tokens.logs.levels.{level} 不是规范允许的字段")
                    continue
                level_out[level] = _validate_visual_block(
                    f"logs.levels.{level}", value, errors, frozenset()
                )
        out["levels"] = level_out

    return out


def _clamp_numeric(field_name: str, value: Any, errors: List[str], path: str) -> Optional[int]:
    try:
        num = int(value)
    except (TypeError, ValueError):
        errors.append(f"{path} 必须是数字")
        return None
    lo, hi = NUMERIC_BOUNDS.get(field_name, (None, None))
    if lo is not None:
        num = max(lo, min(hi, num))
    return num


def _clamp_number(field_name: str, value: Any, errors: List[str], path: str) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        errors.append(f"{path} 必须是数字")
        return None
    lo, hi = NUMERIC_BOUNDS.get(field_name, (None, None))
    if lo is not None:
        num = max(lo, min(hi, num))
    return round(num, 2)


def _validate_enum(value: Any, allowed: frozenset, errors: List[str], path: str) -> Optional[str]:
    if isinstance(value, str) and value in allowed:
        return value
    errors.append(f"{path} 必须是 {sorted(allowed)} 之一")
    return None


def _copy_numeric_fields(
    out: Dict[str, Any], block: Dict[str, Any], fields: Iterable[str], errors: List[str], path_prefix: str
) -> None:
    for field in fields:
        if field not in block:
            continue
        val = _clamp_numeric(field, block[field], errors, f"{path_prefix}.{field}")
        if val is not None:
            out[field] = val


def _copy_number_fields(
    out: Dict[str, Any], block: Dict[str, Any], fields: Iterable[str], errors: List[str], path_prefix: str
) -> None:
    for field in fields:
        if field not in block:
            continue
        val = _clamp_number(field, block[field], errors, f"{path_prefix}.{field}")
        if val is not None:
            out[field] = val


def _copy_safe_css_field(out: Dict[str, Any], block: Dict[str, Any], field: str, errors: List[str], path: str) -> None:
    if field not in block:
        return
    value = block[field]
    if isinstance(value, str) and _is_safe_css_value(value):
        out[field] = value
    else:
        errors.append(f"{path} 非法")


def validate_manifest(data: Any) -> ThemeValidationResult:
    """校验一个 manifest dict，返回结果与规整后的 manifest。"""
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(data, dict):
        return ThemeValidationResult(ok=False, errors=["manifest 必须是 JSON 对象"])

    schema = data.get("schema")
    if schema != CHAT_THEME_SCHEMA:
        errors.append(f"schema 必须为 {CHAT_THEME_SCHEMA}，实际 {schema!r}")

    theme_id = str(data.get("id") or "")
    if not theme_id:
        errors.append("缺少 id")
    elif theme_id != theme_id.strip():
        errors.append("id 首尾不能包含空白字符")
    elif not _ID_RE.match(theme_id):
        errors.append("id 仅允许小写字母/数字/-/_，且需以字母数字开头")

    name = data.get("name")
    if not isinstance(name, dict) or not any(str(v).strip() for v in name.values()):
        errors.append("name 必须是非空的多语言对象，如 {\"zh_CN\": \"...\"}")

    tokens = data.get("tokens")
    normalized_tokens: Dict[str, Any] = {}
    if not isinstance(tokens, dict):
        errors.append("tokens 必须是对象")
        tokens = {}

    for block_name in tokens:
        if block_name not in ALLOWED_TOKEN_BLOCKS:
            errors.append(f"tokens.{block_name} 不是规范允许的块（允许：{sorted(ALLOWED_TOKEN_BLOCKS)}）")

    # global
    if isinstance(tokens.get("global"), dict):
        g = {}
        for k, v in tokens["global"].items():
            if k in {"themeColor", "fontFamily"} and isinstance(v, str) and _is_safe_css_value(v):
                g[k] = v
            else:
                errors.append(f"tokens.global.{k} 非法")
        normalized_tokens["global"] = g

    # fonts
    if "fonts" in tokens:
        fonts_out = []
        fonts = tokens.get("fonts")
        if not isinstance(fonts, list):
            errors.append("tokens.fonts 必须是数组")
        else:
            for i, fnt in enumerate(fonts):
                if not isinstance(fnt, dict) or "family" not in fnt or "src" not in fnt:
                    errors.append(f"tokens.fonts[{i}] 需含 family 与 src")
                    continue
                if not _is_safe_asset_ref(str(fnt.get("src"))):
                    errors.append(f"tokens.fonts[{i}].src 必须是主题目录内相对路径")
                    continue
                fonts_out.append(
                    {k: fnt[k] for k in ("family", "src", "weight", "style") if k in fnt}
                )
        normalized_tokens["fonts"] = fonts_out

    # 可视化块
    for block_name in ("dialog", "options", "input", "toolbar", "send", "name"):
        if block_name not in tokens:
            continue
        allowed_extra = EXTRA_BLOCK_PROPS.get(block_name, frozenset())
        out = _validate_visual_block(
            block_name,
            tokens[block_name],
            errors,
            allowed_extra,
            allow_frame=block_name in FRAME_TOKEN_BLOCKS,
        )
        block = tokens[block_name] if isinstance(tokens[block_name], dict) else {}
        # 额外字段语义校验
        if block_name == "dialog":
            _copy_numeric_fields(out, block, ("heightPx", "widthPct", "offsetY"), errors, "tokens.dialog")
            _copy_number_fields(out, block, ("nameInputGapVh",), errors, "tokens.dialog")
            if "chrome" in block:
                val = _validate_enum(block["chrome"], frozenset({"panel", "none"}), errors, "tokens.dialog.chrome")
                if val is not None:
                    out["chrome"] = val
            if "textAlign" in block:
                val = _validate_enum(block["textAlign"], frozenset({"left", "center"}), errors, "tokens.dialog.textAlign")
                if val is not None:
                    out["textAlign"] = val
            _copy_numeric_fields(out, block, ("textSizePx", "textWeight"), errors, "tokens.dialog")
            _copy_safe_css_field(out, block, "textShadow", errors, "tokens.dialog.textShadow")
        if block_name == "options":
            _copy_numeric_fields(
                out,
                block,
                ("gap", "minHeightPx", "textSizePx", "textWeight", "widthPx"),
                errors,
                "tokens.options",
            )
            _copy_number_fields(
                out,
                block,
                ("minHeightVh", "minWidthVw", "maxWidthVw", "nameClearanceVh", "textSizeVh"),
                errors,
                "tokens.options",
            )
            if "active" in block:
                out["active"] = _validate_visual_block(
                    "options.active", block["active"], errors, frozenset()
                )
            if "hover" in block:
                out["hover"] = _validate_visual_block(
                    "options.hover", block["hover"], errors, frozenset()
                )
            if "icon" in block:
                val = _validate_enum(block["icon"], frozenset({"none", "chat"}), errors, "tokens.options.icon")
                if val is not None:
                    out["icon"] = val
            if "placement" in block:
                val = _validate_enum(
                    block["placement"], frozenset({"center", "right"}), errors, "tokens.options.placement"
                )
                if val is not None:
                    out["placement"] = val
            if "widthMode" in block:
                val = _validate_enum(
                    block["widthMode"], frozenset({"fixed", "content"}), errors, "tokens.options.widthMode"
                )
                if val is not None:
                    out["widthMode"] = val
            _copy_safe_css_field(out, block, "textShadow", errors, "tokens.options.textShadow")
        if block_name == "input":
            if "fieldBackground" in block:
                fb = block["fieldBackground"]
                if isinstance(fb, str) and _is_safe_css_value(fb):
                    out["fieldBackground"] = fb
                else:
                    errors.append("tokens.input.fieldBackground 非法")
            if "fieldBorderRadius" in block:
                fbr = block["fieldBorderRadius"]
                if isinstance(fbr, str) and _is_safe_css_value(fbr):
                    out["fieldBorderRadius"] = fbr
                else:
                    errors.append("tokens.input.fieldBorderRadius 非法")
            if "sendPlacement" in block:
                val = _validate_enum(
                    block["sendPlacement"], frozenset({"outside", "inside"}), errors, "tokens.input.sendPlacement"
                )
                if val is not None:
                    out["sendPlacement"] = val
            if "layout" in block:
                val = _validate_enum(block["layout"], frozenset({"default", "pill"}), errors, "tokens.input.layout")
                if val is not None:
                    out["layout"] = val
            _copy_numeric_fields(out, block, ("maxWidthPx",), errors, "tokens.input")
        if block_name == "toolbar":
            if "placement" in block:
                val = _validate_enum(
                    block["placement"], frozenset({"dialog-top", "input", "input-top"}), errors, "tokens.toolbar.placement"
                )
                if val is not None:
                    out["placement"] = val
            if "reveal" in block:
                val = _validate_enum(
                    block["reveal"], frozenset({"always", "hover"}), errors, "tokens.toolbar.reveal"
                )
                if val is not None:
                    out["reveal"] = val
        if block_name == "name" and "align" in block:
            val = _validate_enum(block["align"], frozenset({"left", "center"}), errors, "tokens.name.align")
            if val is not None:
                out["align"] = val
        if block_name == "name" and "decoration" in block:
            val = _validate_enum(
                block["decoration"],
                frozenset({"accent", "arrow-fade", "line-dots"}),
                errors,
                "tokens.name.decoration",
            )
            if val is not None:
                out["decoration"] = val
        if block_name == "name":
            if "hideWhenStartOption" in block:
                if isinstance(block["hideWhenStartOption"], bool):
                    out["hideWhenStartOption"] = block["hideWhenStartOption"]
                else:
                    errors.append("tokens.name.hideWhenStartOption 必须是布尔值")
            _copy_safe_css_field(out, block, "fontFamily", errors, "tokens.name.fontFamily")
            _copy_numeric_fields(out, block, ("overlapPx", "textSizePx", "textWeight"), errors, "tokens.name")
            _copy_safe_css_field(out, block, "textShadow", errors, "tokens.name.textShadow")
        normalized_tokens[block_name] = out

    if "logs" in tokens:
        normalized_tokens["logs"] = _validate_logs_block(tokens["logs"], errors)

    # typewriter
    if isinstance(tokens.get("typewriter"), dict):
        tw = {}
        tdata = tokens["typewriter"]
        if "cps" in tdata:
            val = _clamp_numeric("cps", tdata["cps"], errors, "tokens.typewriter.cps")
            if val is not None:
                tw["cps"] = val
        if "sound" in tdata:
            if _is_safe_asset_ref(str(tdata["sound"])):
                tw["sound"] = tdata["sound"]
            else:
                errors.append("tokens.typewriter.sound 必须是主题目录内相对路径")
        normalized_tokens["typewriter"] = tw

    preview = data.get("preview")
    if preview is not None and not _is_safe_asset_ref(str(preview)):
        errors.append("preview 必须是主题目录内相对路径")
        preview = None

    normalized = {
        "schema": CHAT_THEME_SCHEMA,
        "id": theme_id,
        "name": name if isinstance(name, dict) else {},
        "tokens": normalized_tokens,
    }
    for opt in ("author", "version", "description"):
        if opt in data:
            normalized[opt] = data[opt]
    if preview:
        normalized["preview"] = preview

    return ThemeValidationResult(ok=not errors, errors=errors, warnings=warnings, normalized=normalized)


def validate_theme_dir(theme_dir: str | Path) -> ThemeValidationResult:
    """读取并校验一个主题目录（含 theme.json + 引用资源是否存在）。"""
    raw_theme_dir = validate_exact_path_text(theme_dir, field="theme directory")
    unresolved_theme_dir = Path(raw_theme_dir).expanduser()
    if unresolved_theme_dir.is_absolute():
        try:
            require_symlink_free_absolute_path(
                unresolved_theme_dir,
                field="theme directory",
            )
        except (OSError, ValueError) as exc:
            return ThemeValidationResult(ok=False, errors=[f"主题目录扫描失败: {exc}"])
    theme_dir = resolve_project_output_path(raw_theme_dir, root=project_root())
    try:
        _, files = inspect_portable_directory_tree(theme_dir)
    except (OSError, ValueError) as exc:
        return ThemeValidationResult(
            ok=False,
            errors=[f"主题目录包含符号链接或非法路径，扫描失败: {exc}"],
        )
    file_names = {path.as_posix() for path in files}
    manifest_path = theme_dir / MANIFEST_NAME
    if MANIFEST_NAME not in file_names:
        return ThemeValidationResult(ok=False, errors=[f"缺少 {MANIFEST_NAME}"])
    try:
        manifest_text, _manifest_identity = read_text_snapshot_without_links(
            manifest_path,
        )
        data = json.loads(manifest_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ThemeValidationResult(ok=False, errors=[f"{MANIFEST_NAME} 解析失败: {exc}"])

    result = validate_manifest(data)
    # 校验引用资源是否真实存在于目录内
    for ref in _iter_asset_refs(result.normalized):
        if ref not in file_names:
            result.warnings.append(f"引用的资源不存在: {ref}")
    return result


def _iter_asset_refs(manifest: Dict[str, Any]):
    if manifest.get("preview"):
        yield manifest["preview"]
    tokens = manifest.get("tokens", {})
    yield from _iter_background_image_refs(tokens)
    if tokens.get("typewriter", {}).get("sound"):
        yield tokens["typewriter"]["sound"]
    for fnt in tokens.get("fonts", []) or []:
        if fnt.get("src"):
            yield fnt["src"]


def _iter_background_image_refs(value: Any):
    if isinstance(value, dict):
        for key in ("backgroundImage", "frameImage"):
            ref = value.get(key)
            if isinstance(ref, str) and ref:
                yield ref
        for child in value.values():
            yield from _iter_background_image_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_background_image_refs(child)


# --------------------------------------------------------------------------- #
# 打包 / 安全解压
# --------------------------------------------------------------------------- #

def pack_theme(theme_dir: str | Path, output_zip: str | Path) -> Path:
    """把一个主题目录打成 .zip（校验通过才打包）。"""
    raw_theme_dir = validate_exact_path_text(theme_dir, field="theme directory")
    result = validate_theme_dir(theme_dir)
    if not result.ok:
        raise ValueError("主题校验失败:\n" + "\n".join(result.errors))
    theme_dir = resolve_project_output_path(raw_theme_dir, root=project_root())
    raw_output_zip = validate_exact_path_text(output_zip, field="theme package output")
    unresolved_output_zip = Path(raw_output_zip).expanduser()
    if unresolved_output_zip.is_absolute():
        require_symlink_free_absolute_path(
            unresolved_output_zip,
            field="theme package output",
        )
    output_zip = resolve_project_output_path(raw_output_zip, root=project_root())
    if output_zip == theme_dir or path_is_within(output_zip, theme_dir):
        raise ValueError("主题包输出不能位于待打包主题目录内部")
    with atomic_binary_writer(output_zip) as output_file:
        with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            write_directory_to_zip_without_links(zf, theme_dir)
    return output_zip


def safe_extract(zip_path: str | Path, dest_dir: str | Path) -> Path:
    """zip-slip 安全解压到 ``dest_dir``，返回解压根目录。"""
    raw_zip_path = validate_exact_path_text(zip_path, field="theme package path")
    unresolved_zip_path = Path(raw_zip_path).expanduser()
    if unresolved_zip_path.is_absolute():
        zip_path = require_symlink_free_absolute_path(
            unresolved_zip_path,
            field="theme package path",
        )
    else:
        zip_path = resolve_managed_project_path(
            raw_zip_path,
            root=project_root(),
        )
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)
    raw_dest_dir = validate_exact_path_text(
        dest_dir,
        field="theme extraction directory",
    )
    unresolved_dest_dir = Path(raw_dest_dir).expanduser()
    if unresolved_dest_dir.is_absolute():
        require_symlink_free_absolute_path(
            unresolved_dest_dir,
            field="theme extraction directory",
        )
    dest_dir = resolve_project_output_path(raw_dest_dir, root=project_root())
    try:
        with open_binary_read_without_links(zip_path) as source:
            initial_metadata = os.fstat(source.fileno())
            with zipfile.ZipFile(source) as zf:
                extract_zip_safely(zf, dest_dir)
            final_metadata = os.fstat(source.fileno())
        if not file_snapshot_is_stable(initial_metadata, final_metadata):
            raise PermissionError(
                f"theme package changed while it was extracted: {zip_path}"
            )
    except UnsafeArchiveError as exc:
        raise ValueError(f"非法压缩包条目（路径穿越或非便携路径）: {exc}") from exc
    return dest_dir


def locate_manifest_root(extracted: Path) -> Optional[Path]:
    """在解压结果里定位 theme.json 所在目录（支持 zip 根或单层子目录）。"""
    extracted = Path(extracted)
    try:
        directories, files = inspect_portable_directory_tree(extracted)
    except (OSError, PermissionError, ValueError):
        return None
    file_set = set(files)
    if Path(MANIFEST_NAME) in file_set:
        return extracted
    subdirs = [path for path in directories if len(path.parts) == 1]
    if (
        len(subdirs) == 1
        and subdirs[0] / MANIFEST_NAME in file_set
    ):
        return extracted / subdirs[0]
    return None


# --------------------------------------------------------------------------- #
# 开发者 CLI
# --------------------------------------------------------------------------- #

def _main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m sdk.chat_ui_theme", description="chat_ui 主题工具")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="校验主题目录")
    v.add_argument("dir")
    p = sub.add_parser("pack", help="打包主题目录为 zip")
    p.add_argument("dir")
    p.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        result = validate_theme_dir(args.dir)
        for e in result.errors:
            print(f"[error] {e}")
        for w in result.warnings:
            print(f"[warn]  {w}")
        print("OK" if result.ok else "FAILED")
        return 0 if result.ok else 1
    if args.cmd == "pack":
        out = pack_theme(args.dir, args.output)
        print(f"packed -> {out}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
