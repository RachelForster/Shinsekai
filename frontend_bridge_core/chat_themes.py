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
import os
import stat
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sdk.file_transactions import (
    atomic_write_text,
    copy_directory_without_links,
    private_temporary_directory,
    inspect_portable_directory_tree_with_metadata,
    private_sibling_path,
    read_bytes_snapshot_without_links,
    read_text_without_links,
    remove_directory_without_links,
    remove_file_without_links,
    rename_path_without_overwrite,
    replace_directory_transactionally,
    require_directory_identity,
    snapshot_directory_entries_without_links,
)
from sdk.path_contract import (
    _metadata_is_link_or_reparse_point,
    managed_child_path,
    managed_project_storage,
    path_is_link_or_reparse_point,
    project_root as configured_project_root,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resource_path,
)

from .builtin_chat_themes import (
    BUILTIN_THEME_IDS,
    DEFAULT_BUILTIN_CHAT_THEME_ID,
    LEGACY_UNMARKED_BUILTIN_THEME_IDS,
)
from sdk.chat_ui_theme import (
    MANIFEST_NAME,
    locate_manifest_root,
    safe_extract,
    slugify_theme_id,
    validate_manifest,
    validate_theme_dir,
)

from sdk.path_references import state_project_root
from .security import safe_child_path, safe_existing_file_path
from application.runtime.state import BridgeState

#: 用户可写主题目录（只相对权威项目根）。
USER_THEMES_DIR = Path("data") / "chat_ui_themes"
BUILTIN_THEMES_DIR = Path("assets") / "chat_ui_themes"
RETIRED_BUILTIN_THEME_IDS = {"classic-dark", "light-paper"}

#: manifest schema 版本，与前端 CHAT_THEME_SCHEMA 一致。
CHAT_THEME_SCHEMA = 1
BUILTIN_THEME_OWNER_MARKER = ".shinsekai-builtin-theme"
_THEME_PUBLICATION_LOCK = threading.RLock()


@dataclass(frozen=True)
class _ThemeManifestSnapshot:
    identity: os.stat_result
    files: tuple[tuple[Path, os.stat_result], ...]
    manifest: Dict[str, Any]


def _themes_root(state: BridgeState | None = None) -> Path:
    base = state_project_root(state) if state is not None else configured_project_root()
    return managed_project_storage(USER_THEMES_DIR, root=base)


def _prepare_themes_root(state: BridgeState | None = None) -> Path:
    """Create and revalidate the exact writable theme directory."""

    root = _themes_root(state)
    root.mkdir(parents=True, exist_ok=True)
    return require_directory_without_links(
        root,
        field="chat theme directory",
    )


def _builtin_themes_root() -> Path:
    return resource_path(BUILTIN_THEMES_DIR)


def _registered_builtin_theme(
    theme_id: str,
    state: BridgeState | None = None,
) -> Optional[tuple[str, Path]]:
    """Return a trusted registry ID and its canonical user-data directory."""
    for registered_id in BUILTIN_THEME_IDS:
        if theme_id == registered_id:
            return registered_id, managed_child_path(
                _themes_root(state),
                registered_id,
                field="theme id",
            )
    return None


def _is_builtin_theme_dir(theme_id: str, state: BridgeState | None = None) -> bool:
    try:
        registered = _registered_builtin_theme(theme_id, state)
        if registered is None:
            return False
        theme_id, registered_dir = registered
        unresolved = _themes_root(state) / theme_id
        if path_is_link_or_reparse_point(unresolved):
            return False
        if theme_id in LEGACY_UNMARKED_BUILTIN_THEME_IDS:
            # Missing legacy built-ins are still registry-owned so manifest
            # lookup can fall back to the default.  Existing symlinks were
            # rejected above and existing non-directories are never owned.
            return not unresolved.exists() or registered_dir.is_dir()
        if not registered_dir.is_dir():
            return False
        marker = managed_child_path(
            registered_dir,
            BUILTIN_THEME_OWNER_MARKER,
            field="built-in theme marker",
        )
        return read_text_without_links(marker).strip() == theme_id
    except (OSError, ValueError):
        return False


def _mark_builtin_theme_owned(theme_id: str, state: BridgeState | None = None) -> None:
    registered = _registered_builtin_theme(theme_id, state)
    if registered is None:
        raise ValueError(f"unknown built-in theme id: {theme_id}")
    registered_id, registered_dir = registered
    unresolved = _themes_root(state) / registered_id
    if path_is_link_or_reparse_point(unresolved) or not registered_dir.is_dir():
        raise PermissionError("内置主题目录不能是符号链接")
    marker = managed_child_path(
        registered_dir,
        BUILTIN_THEME_OWNER_MARKER,
        field="built-in theme marker",
    )
    atomic_write_text(marker, f"{registered_id}\n")


def _is_retired_builtin_theme_id(theme_id: str) -> bool:
    return theme_id in RETIRED_BUILTIN_THEME_IDS


def _safe_theme_id(theme_id: str) -> str:
    raw = str(theme_id or "")
    safe_id = slugify_theme_id(raw)
    if not safe_id or safe_id != raw:
        raise ValueError("主题 id 无效")
    return safe_id


def _copy_theme_source(
    source: Path,
    staging: Path,
    root: Path,
    *,
    expected_source_identity: os.stat_result | None = None,
) -> None:
    """Copy a real theme directory that is strictly contained by ``root``."""
    if path_is_link_or_reparse_point(root) or path_is_link_or_reparse_point(source):
        raise PermissionError("基础主题路径不能是符号链接")
    canonical_root = root.resolve(strict=True)
    canonical_source = source.resolve(strict=True)
    try:
        relative = canonical_source.relative_to(canonical_root)
    except ValueError as exc:
        raise PermissionError("基础主题路径超出主题目录") from exc
    if not relative.parts:
        raise PermissionError("基础主题路径超出主题目录")
    # Preserve the unresolved source for the copy helper.  Replacing the
    # selected directory with a link between validation and copying must be
    # rejected, not silently dereferenced to another theme.
    copy_directory_without_links(
        source,
        staging,
        expected_source_identity=expected_source_identity,
    )


def _atomic_write_manifest(
    theme_dir: Path,
    manifest: Dict[str, Any],
    *,
    expected_theme_identity: os.stat_result | None = None,
) -> None:
    theme_metadata = theme_dir.lstat()
    if (
        _metadata_is_link_or_reparse_point(theme_metadata)
        or not stat.S_ISDIR(theme_metadata.st_mode)
    ):
        raise NotADirectoryError(theme_dir)
    if (
        expected_theme_identity is not None
        and not os.path.samestat(expected_theme_identity, theme_metadata)
    ):
        raise PermissionError(f"主题目录身份已变化：{theme_dir.name}")
    manifest_path = managed_child_path(
        theme_dir,
        MANIFEST_NAME,
        field="theme manifest filename",
    )
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        expected_parent_identity=theme_metadata,
    )
    final_theme_metadata = theme_dir.lstat()
    if not os.path.samestat(theme_metadata, final_theme_metadata):
        raise PermissionError(f"主题目录身份在保存期间发生变化：{theme_dir.name}")


def _publish_new_theme(staging: Path, target: Path, theme_id: str) -> None:
    """Atomically publish a complete staged directory without replacing a peer."""

    publication_staging = private_sibling_path(
        target,
        f".publish-{uuid.uuid4().hex}",
        field="theme publication staging directory",
    )
    publication_identity: os.stat_result | None = None
    with _THEME_PUBLICATION_LOCK:
        try:
            if target.exists() or path_is_link_or_reparse_point(target):
                raise FileExistsError(f"主题已存在：{theme_id}")
            copy_directory_without_links(staging, publication_staging)
            publication_identity = publication_staging.lstat()
            replace_directory_transactionally(
                publication_staging,
                target,
                overwrite=False,
                expected_staging_identity=publication_identity,
                expected_destination_identity=None,
            )
        except FileExistsError as error:
            if target.exists() or path_is_link_or_reparse_point(target):
                raise FileExistsError(f"主题已存在：{theme_id}") from error
            raise
        finally:
            if publication_identity is not None:
                try:
                    remove_directory_without_links(
                        publication_staging,
                        expected_identity=publication_identity,
                    )
                except OSError:
                    pass


def _theme_version(theme_dir: Path) -> str:
    snapshot = _read_theme_manifest_snapshot(theme_dir)
    if snapshot is None:
        return ""
    return str(snapshot.manifest.get("version") or "").strip()


def _seed_builtin_themes(state: BridgeState | None = None) -> None:
    root = _prepare_themes_root(state)
    builtin_root = _builtin_themes_root()
    with _THEME_PUBLICATION_LOCK:
        for theme_id in BUILTIN_THEME_IDS:
            source = builtin_root / theme_id
            target = root / theme_id
            if path_is_link_or_reparse_point(source) or not source.is_dir():
                continue
            if path_is_link_or_reparse_point(target):
                # Never refresh through a user-created link, including the two
                # legacy IDs that predate ownership markers.
                continue

            target_exists = target.exists()
            if target_exists and (
                not target.is_dir() or not _is_builtin_theme_dir(theme_id, state)
            ):
                continue
            target_identity = target.lstat() if target_exists else None

            source_version = _theme_version(source)
            refresh = not target_exists or (
                bool(source_version) and source_version != _theme_version(target)
            )
            if not refresh:
                _mark_builtin_theme_owned(theme_id, state)
                continue

            staging = private_sibling_path(
                root / theme_id,
                f".seed-{uuid.uuid4().hex}",
                field="theme seed staging directory",
            )
            staging_identity: os.stat_result | None = None
            try:
                copy_directory_without_links(source, staging)
                staging_identity = staging.lstat()
                atomic_write_text(
                    managed_child_path(
                        staging,
                        BUILTIN_THEME_OWNER_MARKER,
                        field="theme marker filename",
                    ),
                    f"{theme_id}\n",
                )
                result = validate_theme_dir(staging)
                if not result.ok:
                    raise ValueError("内置主题校验失败：\n" + "\n".join(result.errors))
                _replace_theme_directory(
                    staging,
                    target,
                    overwrite=target_exists,
                    expected_staging_identity=staging_identity,
                    expected_destination_identity=target_identity,
                )
            finally:
                if staging_identity is not None:
                    try:
                        remove_directory_without_links(
                            staging,
                            expected_identity=staging_identity,
                        )
                    except OSError:
                        pass


def _read_theme_manifest_snapshot(
    theme_dir: Path,
    *,
    expected_theme_identity: os.stat_result | None = None,
) -> _ThemeManifestSnapshot | None:
    manifest_path = theme_dir / "theme.json"
    try:
        theme_identity, _directories, files = (
            inspect_portable_directory_tree_with_metadata(theme_dir)
        )
        if (
            expected_theme_identity is not None
            and not os.path.samestat(
                expected_theme_identity,
                theme_identity,
            )
        ):
            raise PermissionError(
                f"chat theme directory identity changed: {theme_dir}"
            )
        file_identities = dict(files)
        manifest_identity = file_identities.get(Path(MANIFEST_NAME))
        if manifest_identity is None:
            return None
        payload, _manifest_snapshot = read_bytes_snapshot_without_links(
            manifest_path,
            expected_identity=manifest_identity,
            expected_parent_identity=theme_identity,
        )
        data = json.loads(payload.decode("utf-8"))
        require_directory_identity(
            theme_dir,
            theme_identity,
            field="chat theme directory",
        )
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    result = validate_manifest({**data, "id": theme_dir.name})
    if not result.ok:
        return None
    return _ThemeManifestSnapshot(
        identity=theme_identity,
        files=tuple(files),
        manifest=result.normalized,
    )


def _read_manifest(theme_dir: Path) -> Optional[Dict[str, Any]]:
    snapshot = _read_theme_manifest_snapshot(theme_dir)
    return snapshot.manifest if snapshot is not None else None


def _media_url(rel_path: Path) -> str:
    """主题目录内资源 → 可访问 URL（走已有 /api/media）。"""
    posix = rel_path.as_posix()
    from urllib.parse import quote

    return f"/api/media?path={quote(posix)}"


def _summary(
    theme_dir: Path,
    snapshot: _ThemeManifestSnapshot,
    state: BridgeState | None = None,
) -> Dict[str, Any]:
    manifest = snapshot.manifest
    preview = manifest.get("preview")
    preview_url = None
    if isinstance(preview, str) and preview:
        try:
            candidate = safe_child_path(theme_dir, preview)
            relative = candidate.relative_to(theme_dir)
            expected_preview_identity = dict(snapshot.files).get(relative)
            current_preview_identity = candidate.lstat()
        except (FileNotFoundError, OSError, ValueError):
            expected_preview_identity = None
        if (
            expected_preview_identity is not None
            and stat.S_ISREG(expected_preview_identity.st_mode)
            and os.path.samestat(
                expected_preview_identity,
                current_preview_identity,
            )
        ):
            preview_url = _media_url(USER_THEMES_DIR / theme_dir.name / preview)
    require_directory_identity(
        theme_dir,
        snapshot.identity,
        field="chat theme directory",
    )
    source = (
        "builtin"
        if _is_builtin_theme_dir(theme_dir.name, state)
        else "user"
    )
    require_directory_identity(
        theme_dir,
        snapshot.identity,
        field="chat theme directory",
    )
    return {
        "id": theme_dir.name,
        "name": manifest.get("name") or {"zh_CN": theme_dir.name},
        "author": manifest.get("author"),
        "version": manifest.get("version"),
        "previewUrl": preview_url,
        "source": source,
    }


def list_chat_themes(state: BridgeState) -> List[Dict[str, Any]]:
    """扫描主题目录，返回 ChatThemeSummary[]。"""
    _seed_builtin_themes(state)
    root = _themes_root(state)
    try:
        root, root_identity, entries = snapshot_directory_entries_without_links(
            root,
            field="chat theme directory",
        )
    except (FileNotFoundError, NotADirectoryError):
        return []
    summaries: List[Dict[str, Any]] = []
    for child, child_identity in sorted(
        entries,
        key=lambda item: (
            item[0].name.casefold(),
            item[0].name,
        ),
    ):
        if (
            _metadata_is_link_or_reparse_point(child_identity)
            or not stat.S_ISDIR(child_identity.st_mode)
        ):
            continue
        if _is_retired_builtin_theme_id(child.name):
            continue
        snapshot = _read_theme_manifest_snapshot(
            child,
            expected_theme_identity=child_identity,
        )
        if snapshot is None:
            continue
        try:
            summaries.append(_summary(child, snapshot, state))
        except (FileNotFoundError, PermissionError):
            continue
    require_directory_identity(
        root,
        root_identity,
        field="chat theme directory",
    )
    return summaries


def get_chat_theme_manifest(state: BridgeState, theme_id: str) -> Dict[str, Any]:
    """读取并返回单个主题的完整 manifest。"""
    _seed_builtin_themes(state)
    safe_id = _safe_theme_id(theme_id)
    if _is_retired_builtin_theme_id(safe_id):
        raise FileNotFoundError(f"主题不存在或 theme.json 无效: {theme_id}")
    root = _themes_root(state)
    manifest = _read_manifest(root / safe_id)
    if manifest is None and safe_id != DEFAULT_BUILTIN_CHAT_THEME_ID and _is_builtin_theme_dir(safe_id, state):
        manifest = _read_manifest(root / DEFAULT_BUILTIN_CHAT_THEME_ID)
    if manifest is None:
        raise FileNotFoundError(f"主题不存在或 theme.json 无效: {theme_id}")
    return manifest


def get_active_chat_theme_id(state: BridgeState) -> Dict[str, str]:
    """返回当前激活主题 id（存于 system_config.chat_ui_theme_id）。"""
    system_config = state.config_manager.config.system_config
    theme_id = str(getattr(system_config, "chat_ui_theme_id", "") or "")
    try:
        safe_id = _safe_theme_id(theme_id)
    except ValueError:
        safe_id = DEFAULT_BUILTIN_CHAT_THEME_ID
    if _is_retired_builtin_theme_id(safe_id):
        safe_id = DEFAULT_BUILTIN_CHAT_THEME_ID
    return {"id": safe_id}


def set_active_chat_theme(state: BridgeState, body: Dict[str, Any]) -> Dict[str, str]:
    """设置激活主题 id 并持久化。"""
    theme_id = str((body or {}).get("id") or "")
    if not theme_id:
        raise ValueError("缺少主题 id")
    _seed_builtin_themes(state)
    safe_id = _safe_theme_id(theme_id)
    if _is_retired_builtin_theme_id(safe_id):
        raise FileNotFoundError(f"主题不存在：{theme_id}")
    if _read_manifest(_themes_root(state) / safe_id) is None:
        raise FileNotFoundError(f"主题不存在：{theme_id}")
    system_config = state.config_manager.config.system_config
    previous_id = str(getattr(system_config, "chat_ui_theme_id", "") or "")
    setattr(system_config, "chat_ui_theme_id", safe_id)
    save = (
        getattr(state.config_manager, "save_system_config", None)
        or getattr(state.config_manager, "save_config", None)
        or getattr(state.config_manager, "save", None)
    )
    if not callable(save):
        setattr(system_config, "chat_ui_theme_id", previous_id)
        raise RuntimeError("主题配置无法持久化")
    try:
        save()
    except Exception:
        setattr(system_config, "chat_ui_theme_id", previous_id)
        raise
    return {"id": safe_id}


def _replace_theme_directory(
    staging: Path,
    target: Path,
    *,
    overwrite: bool,
    expected_staging_identity: os.stat_result | None,
    expected_destination_identity: os.stat_result | None,
) -> None:
    """Publish one complete theme tree and restore the old tree on failure."""

    with _THEME_PUBLICATION_LOCK:
        if path_is_link_or_reparse_point(target):
            raise PermissionError("主题安装目标不能是符号链接")
        if target.exists() and not target.is_dir():
            raise FileExistsError(f"主题路径不是目录：{target.name}")
        try:
            replace_directory_transactionally(
                staging,
                target,
                overwrite=overwrite,
                expected_staging_identity=expected_staging_identity,
                expected_destination_identity=expected_destination_identity,
            )
        except FileExistsError as exc:
            raise FileExistsError(f"主题已存在：{target.name}") from exc


def install_theme_from_zip(
    state: BridgeState, zip_path: Path, *, overwrite: bool = False
) -> Dict[str, Any]:
    """安装上传的主题 zip：安全解压 → 定位 theme.json → 校验 → 落地到 data/chat_ui_themes/<id>/。

    返回安装后的 ChatThemeSummary。校验不通过会抛 ``ValueError``，把错误清单返回给前端。
    """
    root = _prepare_themes_root(state)
    _seed_builtin_themes(state)

    with private_temporary_directory(prefix="chat_theme_") as temp_root:
        extracted = safe_extract(
            safe_existing_file_path(zip_path, field="theme zip path"),
            temp_root,
        )
        manifest_root = locate_manifest_root(extracted)
        if manifest_root is None:
            raise ValueError(f"压缩包内未找到 {MANIFEST_NAME}")

        result = validate_theme_dir(manifest_root)
        if not result.ok:
            raise ValueError("主题校验失败：\n" + "\n".join(result.errors))

        theme_id = slugify_theme_id(result.normalized.get("id") or manifest_root.name)
        theme_id = _safe_theme_id(theme_id)
        # The installed directory, persisted manifest, and API identity must
        # remain one value even when a portable-filesystem rewrite was needed.
        result.normalized["id"] = theme_id
        target = managed_child_path(root, theme_id, field="theme id")
        if target.exists() and _is_builtin_theme_dir(theme_id, state):
            raise PermissionError(f"内置主题不可覆盖：{theme_id}")
        if target.exists() and not overwrite:
            raise FileExistsError(f"主题已存在：{theme_id}（如需覆盖请传 overwrite=true）")
        try:
            target_identity = target.lstat()
        except FileNotFoundError:
            target_identity = None

        # 以校验后规整的 manifest 落地（剔除非法字段），其余资源原样拷贝。
        staging = private_sibling_path(
            root / theme_id,
            f".install-{uuid.uuid4().hex}",
            field="theme installation staging directory",
        )
        staging_identity: os.stat_result | None = None
        try:
            copy_directory_without_links(manifest_root, staging)
            staging_identity = staging.lstat()
            remove_file_without_links(
                safe_child_path(staging, BUILTIN_THEME_OWNER_MARKER),
                missing_ok=True,
            )
            _atomic_write_manifest(staging, result.normalized)
            _replace_theme_directory(
                staging,
                target,
                overwrite=overwrite,
                expected_staging_identity=staging_identity,
                expected_destination_identity=target_identity,
            )
        finally:
            if staging_identity is not None:
                try:
                    remove_directory_without_links(
                        staging,
                        expected_identity=staging_identity,
                    )
                except OSError:
                    pass

    snapshot = _read_theme_manifest_snapshot(target)
    if snapshot is None:
        raise ValueError(f"安装后的主题无效：{theme_id}")
    return _summary(target, snapshot, state)


def save_chat_theme(state: BridgeState, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a user-owned theme from a validated manifest.

    New themes clone the selected base directory so relative frame, font, sound,
    and background assets keep working. Existing user themes retain their own
    assets and only replace ``theme.json``. Built-in ownership is never changed.
    """
    _seed_builtin_themes(state)
    root = _prepare_themes_root(state)

    raw_manifest = (body or {}).get("manifest")
    result = validate_manifest(raw_manifest)
    if not result.ok:
        raise ValueError("主题配置校验失败：\n" + "\n".join(result.errors))
    manifest = result.normalized
    theme_id = _safe_theme_id(str(manifest.get("id") or ""))
    base_id = _safe_theme_id(str((body or {}).get("baseId") or DEFAULT_BUILTIN_CHAT_THEME_ID))
    creating = base_id != theme_id
    target = managed_child_path(root, theme_id, field="theme id")

    if target.exists() and _is_builtin_theme_dir(theme_id, state):
        raise PermissionError(f"内置主题不可编辑：{theme_id}")
    if target.exists() and not target.is_dir():
        raise FileExistsError(f"主题路径不是目录：{theme_id}")

    source_identity: os.stat_result
    if creating:
        if target.exists():
            raise FileExistsError(f"主题已存在：{theme_id}")
        if _is_retired_builtin_theme_id(base_id):
            raise FileNotFoundError(f"基础主题不存在：{base_id}")
        source = managed_child_path(root, base_id, field="base theme id")
        source_identity = source.lstat()
        if (
            _metadata_is_link_or_reparse_point(source_identity)
            or not stat.S_ISDIR(source_identity.st_mode)
        ):
            raise FileNotFoundError(f"基础主题不存在或无效：{base_id}")
        if _read_manifest(source) is None:
            raise FileNotFoundError(f"基础主题不存在或无效：{base_id}")
        if not os.path.samestat(source_identity, source.lstat()):
            raise PermissionError(f"基础主题目录身份已变化：{base_id}")
    else:
        if not target.is_dir():
            raise FileNotFoundError(f"主题不存在：{theme_id}")
        source = target
        source_identity = source.lstat()
        if (
            _metadata_is_link_or_reparse_point(source_identity)
            or not stat.S_ISDIR(source_identity.st_mode)
        ):
            raise FileNotFoundError(f"主题不存在：{theme_id}")

    with private_temporary_directory(
        prefix="chat_theme_save_",
        directory=root,
    ) as tmp:
        # The temporary directory is unique already. Keep its child name
        # server-controlled so request data is never used in this copy path.
        staging = tmp / "working-theme"
        _copy_theme_source(
            source,
            staging,
            root,
            expected_source_identity=source_identity,
        )
        remove_file_without_links(
            safe_child_path(staging, BUILTIN_THEME_OWNER_MARKER),
            missing_ok=True,
        )
        atomic_write_text(
            managed_child_path(
                staging,
                MANIFEST_NAME,
                field="theme manifest filename",
            ),
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        staged_result = validate_theme_dir(staging)
        if not staged_result.ok:
            raise ValueError("主题资源校验失败：\n" + "\n".join(staged_result.errors))
        normalized_manifest = staged_result.normalized
        atomic_write_text(
            managed_child_path(
                staging,
                MANIFEST_NAME,
                field="theme manifest filename",
            ),
            json.dumps(normalized_manifest, ensure_ascii=False, indent=2),
        )

        if creating:
            _publish_new_theme(staging, target, theme_id)
        else:
            with _THEME_PUBLICATION_LOCK:
                _atomic_write_manifest(
                    target,
                    normalized_manifest,
                    expected_theme_identity=source_identity,
                )

    saved_snapshot = _read_theme_manifest_snapshot(target)
    if saved_snapshot is None:
        raise ValueError(f"保存后的主题无效：{theme_id}")
    return _summary(target, saved_snapshot, state)


def delete_chat_theme(state: BridgeState, theme_id: str) -> Dict[str, Any]:
    """删除一个用户主题目录。内置主题（M5 种子化后只读）不可删。"""
    safe_id = _safe_theme_id(theme_id)
    target = managed_child_path(_themes_root(state), safe_id, field="theme id")
    if _is_builtin_theme_dir(safe_id, state):
        raise PermissionError(f"内置主题不可删除：{theme_id}")
    if path_is_link_or_reparse_point(target):
        raise PermissionError(f"主题目录不能是符号链接：{theme_id}")
    if not target.is_dir():
        raise FileNotFoundError(f"主题不存在：{theme_id}")
    with _THEME_PUBLICATION_LOCK:
        root = _themes_root(state)
        target = managed_child_path(root, safe_id, field="theme id")
        target_metadata = target.lstat()
        if (
            _metadata_is_link_or_reparse_point(target_metadata)
            or not stat.S_ISDIR(target_metadata.st_mode)
        ):
            raise NotADirectoryError(target)
        trash = require_symlink_free_absolute_path(
            private_sibling_path(
                root / safe_id,
                f".delete-{uuid.uuid4().hex}",
                field="theme deletion staging directory",
            ),
            field="theme deletion staging directory",
        )
        if os.path.lexists(trash):
            raise FileExistsError(trash)
        rename_path_without_overwrite(
            target,
            trash,
            expected_identity=target_metadata,
        )
        active_cleared = False
        try:
            trash = require_symlink_free_absolute_path(
                trash,
                field="theme deletion staging directory",
            )
            trash_metadata = trash.lstat()
            if (
                _metadata_is_link_or_reparse_point(trash_metadata)
                or not stat.S_ISDIR(trash_metadata.st_mode)
                or not os.path.samestat(target_metadata, trash_metadata)
            ):
                raise PermissionError(
                    f"theme directory identity changed before deletion: {safe_id}"
                )
            # 若删除的是当前激活主题，先持久化清空；失败则恢复目录。
            active = get_active_chat_theme_id(state).get("id")
            if active == safe_id:
                _clear_active(state)
                active_cleared = True
            remove_directory_without_links(
                trash,
                expected_identity=target_metadata,
            )
        except BaseException as exc:
            restored = False
            try:
                if os.path.lexists(trash) and not os.path.lexists(target):
                    rollback_metadata = trash.lstat()
                    if not os.path.samestat(target_metadata, rollback_metadata):
                        raise PermissionError("主题删除回滚目录身份已变化")
                    rename_path_without_overwrite(
                        trash,
                        target,
                        expected_identity=target_metadata,
                    )
                    restored = True
            except BaseException as rollback_error:
                raise RuntimeError("主题删除回滚目录失败") from rollback_error
            if active_cleared and restored:
                try:
                    set_active_chat_theme(state, {"id": safe_id})
                except BaseException as rollback_error:
                    raise RuntimeError("主题删除回滚配置失败") from rollback_error
            raise
    return {"id": safe_id, "deleted": True}


def _clear_active(state: BridgeState) -> None:
    system_config = state.config_manager.config.system_config
    previous_id = str(getattr(system_config, "chat_ui_theme_id", "") or "")
    setattr(system_config, "chat_ui_theme_id", "")
    save = (
        getattr(state.config_manager, "save_system_config", None)
        or getattr(state.config_manager, "save_config", None)
        or getattr(state.config_manager, "save", None)
    )
    if not callable(save):
        setattr(system_config, "chat_ui_theme_id", previous_id)
        raise RuntimeError("主题配置无法持久化")
    try:
        save()
    except Exception:
        setattr(system_config, "chat_ui_theme_id", previous_id)
        raise
