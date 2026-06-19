"""chat_ui 主题 mod 系统 —— bridge 侧扫描 / 读取 / 校验 / 激活（M0 占位骨架）。

设计文档《chat_ui_react_migration_and_theme_system.md》"主题系统设计" + "参考接口输出 · B"。

主题 = 一个文件夹，含 ``theme.json``（manifest + tokens）+ 可选 ``preview.png`` + ``assets/``。
- 用户主题目录：``data/chat_ui_themes/``（可写，可安装 mod）。
- 内置主题：随仓库附带的示例，首启拷贝到用户目录作示例。

M0：实现目录扫描 + 读取 + 激活 id 读写（落到 system_config.chat_ui_theme_id）；
manifest 严格校验 + token 过滤 + url() 沙箱 + 首启种子拷贝在 M5 补全。
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .builtin_chat_themes import BUILTIN_THEME_MANIFESTS, DEFAULT_BUILTIN_CHAT_THEME_ID
from sdk.chat_ui_theme import (
    MANIFEST_NAME,
    locate_manifest_root,
    safe_extract,
    slugify_theme_id,
    validate_manifest,
    validate_theme_dir,
)

from .state import BridgeState

#: 用户可写主题目录（相对项目根 / cwd）。
USER_THEMES_DIR = Path("data") / "chat_ui_themes"
BUILTIN_THEMES_DIR = Path("assets") / "chat_ui_themes"
BUILTIN_THEME_IDS = {DEFAULT_BUILTIN_CHAT_THEME_ID}
RETIRED_BUILTIN_THEME_IDS = {"classic-dark", "light-paper"}

#: manifest schema 版本，与前端 CHAT_THEME_SCHEMA 一致。
CHAT_THEME_SCHEMA = 1


def _themes_root() -> Path:
    root = USER_THEMES_DIR
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def _builtin_themes_root() -> Path:
    return (Path(__file__).resolve().parents[1] / BUILTIN_THEMES_DIR).resolve()


def _is_builtin_theme_id(theme_id: str) -> bool:
    return theme_id in BUILTIN_THEME_IDS


def _is_retired_builtin_theme_id(theme_id: str) -> bool:
    return theme_id in RETIRED_BUILTIN_THEME_IDS


def _seed_builtin_themes() -> None:
    root = _themes_root()
    builtin_root = _builtin_themes_root()
    root.mkdir(parents=True, exist_ok=True)
    for theme_id in BUILTIN_THEME_IDS:
        source = builtin_root / theme_id
        target = root / theme_id
        if target.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, target)
            continue
        manifest = BUILTIN_THEME_MANIFESTS.get(theme_id)
        if manifest:
            target.mkdir(parents=True, exist_ok=True)
            (target / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def _read_manifest(theme_dir: Path) -> Optional[Dict[str, Any]]:
    manifest_path = theme_dir / "theme.json"
    if not manifest_path.is_file():
        return None
    try:
        with manifest_path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    result = validate_manifest({**data, "id": theme_dir.name})
    if not result.ok:
        return None
    return result.normalized


def _media_url(rel_path: Path) -> str:
    """主题目录内资源 → 可访问 URL（走已有 /api/media）。"""
    posix = rel_path.as_posix()
    from urllib.parse import quote

    return f"/api/media?path={quote(posix)}"


def _summary(theme_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    preview = manifest.get("preview")
    preview_url = None
    if isinstance(preview, str) and preview:
        candidate = theme_dir / preview
        if candidate.is_file():
            preview_url = _media_url(USER_THEMES_DIR / theme_dir.name / preview)
    return {
        "id": theme_dir.name,
        "name": manifest.get("name") or {"zh_CN": theme_dir.name},
        "author": manifest.get("author"),
        "version": manifest.get("version"),
        "previewUrl": preview_url,
        "source": "builtin" if _is_builtin_theme_id(theme_dir.name) else "user",
    }


def list_chat_themes(state: BridgeState) -> List[Dict[str, Any]]:
    """扫描主题目录，返回 ChatThemeSummary[]。"""
    _seed_builtin_themes()
    root = _themes_root()
    if not root.is_dir():
        return []
    summaries: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if _is_retired_builtin_theme_id(child.name):
            continue
        manifest = _read_manifest(child)
        if manifest is None:
            continue
        summaries.append(_summary(child, manifest))
    return summaries


def get_chat_theme_manifest(state: BridgeState, theme_id: str) -> Dict[str, Any]:
    """读取并返回单个主题的完整 manifest。"""
    _seed_builtin_themes()
    safe_id = Path(theme_id).name  # 防目录穿越
    if _is_retired_builtin_theme_id(safe_id):
        raise FileNotFoundError(f"主题不存在或 theme.json 无效: {theme_id}")
    theme_dir = _themes_root() / safe_id
    manifest = _read_manifest(theme_dir)
    if manifest is None:
        raise FileNotFoundError(f"主题不存在或 theme.json 无效: {theme_id}")
    return manifest


def get_active_chat_theme_id(state: BridgeState) -> Dict[str, str]:
    """返回当前激活主题 id（存于 system_config.chat_ui_theme_id）。"""
    system_config = state.config_manager.config.system_config
    theme_id = str(getattr(system_config, "chat_ui_theme_id", "") or "")
    if not theme_id or _is_retired_builtin_theme_id(Path(theme_id).name):
        theme_id = DEFAULT_BUILTIN_CHAT_THEME_ID
    return {"id": theme_id}


def set_active_chat_theme(state: BridgeState, body: Dict[str, Any]) -> Dict[str, str]:
    """设置激活主题 id 并持久化。"""
    theme_id = str((body or {}).get("id") or "").strip()
    if not theme_id:
        raise ValueError("缺少主题 id")
    _seed_builtin_themes()
    safe_id = Path(theme_id).name
    if _is_retired_builtin_theme_id(safe_id):
        raise FileNotFoundError(f"主题不存在：{theme_id}")
    if _read_manifest(_themes_root() / safe_id) is None:
        raise FileNotFoundError(f"主题不存在：{theme_id}")
    system_config = state.config_manager.config.system_config
    setattr(system_config, "chat_ui_theme_id", safe_id)
    save = (
        getattr(state.config_manager, "save_system_config", None)
        or getattr(state.config_manager, "save_config", None)
        or getattr(state.config_manager, "save", None)
    )
    if callable(save):
        try:
            save()
        except Exception:
            pass
    return {"id": safe_id}


def install_theme_from_zip(
    state: BridgeState, zip_path: Path, *, overwrite: bool = False
) -> Dict[str, Any]:
    """安装上传的主题 zip：安全解压 → 定位 theme.json → 校验 → 落地到 data/chat_ui_themes/<id>/。

    返回安装后的 ChatThemeSummary。校验不通过会抛 ``ValueError``，把错误清单返回给前端。
    """
    root = _themes_root()
    root.mkdir(parents=True, exist_ok=True)
    _seed_builtin_themes()

    with tempfile.TemporaryDirectory(prefix="chat_theme_") as tmp:
        extracted = safe_extract(Path(zip_path), Path(tmp))
        manifest_root = locate_manifest_root(extracted)
        if manifest_root is None:
            raise ValueError(f"压缩包内未找到 {MANIFEST_NAME}")

        result = validate_theme_dir(manifest_root)
        if not result.ok:
            raise ValueError("主题校验失败：\n" + "\n".join(result.errors))

        theme_id = slugify_theme_id(result.normalized.get("id") or manifest_root.name)
        target = root / theme_id
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"主题已存在：{theme_id}（如需覆盖请传 overwrite=true）")
            shutil.rmtree(target, ignore_errors=True)

        # 以校验后规整的 manifest 落地（剔除非法字段），其余资源原样拷贝。
        shutil.copytree(manifest_root, target)
        (target / MANIFEST_NAME).write_text(
            json.dumps(result.normalized, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    manifest = _read_manifest(target)
    return _summary(target, manifest or {})


def delete_chat_theme(state: BridgeState, theme_id: str) -> Dict[str, Any]:
    """删除一个用户主题目录。内置主题（M5 种子化后只读）不可删。"""
    safe_id = Path(theme_id).name
    if _is_builtin_theme_id(safe_id):
        raise PermissionError(f"内置主题不可删除：{theme_id}")
    target = _themes_root() / safe_id
    if not target.is_dir():
        raise FileNotFoundError(f"主题不存在：{theme_id}")
    shutil.rmtree(target, ignore_errors=True)
    # 若删除的是当前激活主题，清空激活态。
    active = get_active_chat_theme_id(state).get("id")
    if active == safe_id:
        _clear_active(state)
    return {"id": safe_id, "deleted": True}


def _clear_active(state: BridgeState) -> None:
    system_config = state.config_manager.config.system_config
    setattr(system_config, "chat_ui_theme_id", "")
    save = (
        getattr(state.config_manager, "save_system_config", None)
        or getattr(state.config_manager, "save_config", None)
        or getattr(state.config_manager, "save", None)
    )
    if callable(save):
        try:
            save()
        except Exception:
            pass
