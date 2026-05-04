"""GitHub 源码归档下载、解压与覆盖合并（宿主工程与插件）。"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Literal

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.plugins.registry_download import sanitize_plugins_directory_name

logger = logging.getLogger(__name__)

_DEFAULT_APP_REPO = "RachelForster/Shinsekai"
_USER_AGENT_APP = (
    "EasyAIDesktopAssistant/1.0 (+bundle-update; https://github.com/RachelForster/Shinsekai)"
)

RefKindApi = Literal["latest", "head", "tag"]


def default_app_github_repo_slug() -> str:
    """主程序源码仓库 slug（GitHub），可通过环境变量 SHINSEKAI_APP_REPO 覆盖。"""
    env = os.environ.get("SHINSEKAI_APP_REPO", "").strip()
    if env:
        return normalize_repo_slug_str(env)
    return _DEFAULT_APP_REPO


def normalize_repo_slug_str(repo: str) -> str:
    parts = [p.strip() for p in repo.strip().strip("/").split("/") if p.strip()]
    return "/".join(parts)


def resolve_project_root() -> Path:
    frozen = getattr(sys, "frozen", False)
    if frozen:
        root = Path(sys.executable).resolve().parent
        env = os.environ.get("EASYAI_PROJECT_ROOT", "").strip()
        if env:
            return Path(env)
        parent = root.parent
        return parent if root.name.lower() == "settingsui" else root
    return Path(__file__).resolve().parents[2]


def read_local_version(project_root: Path | None = None) -> str:
    """读取项目根 VERSION 单行；无文件或为空则返回占位「未知」（由 UI 再行 i18n）。"""
    root = project_root if project_root is not None else resolve_project_root()
    vf = root / "VERSION"
    if not vf.is_file():
        return ""
    try:
        line = vf.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        txt = line[0].strip() if line else ""
        return txt
    except OSError:
        return ""


def _api_get_json(url: str, *, timeout_sec: float = 20.0) -> Any:
    req = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT_APP})
    with urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def fetch_latest_release_tag(slug: str, *, timeout_sec: float = 20.0) -> str | None:
    slug = normalize_repo_slug_str(slug)
    if slug.count("/") < 1:
        return None
    url = f"https://api.github.com/repos/{slug}/releases/latest"
    try:
        data = _api_get_json(url, timeout_sec=timeout_sec)
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as e:
        logger.info("releases/latest unavailable for %s: %s", slug, e)
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name")
    return tag.strip() if isinstance(tag, str) and tag.strip() else None


def fetch_recent_tag_names(slug: str, *, limit: int = 30, timeout_sec: float = 25.0) -> list[str]:
    slug = normalize_repo_slug_str(slug)
    if slug.count("/") < 1:
        return []
    url = f"https://api.github.com/repos/{slug}/tags?per_page={min(limit, 10)}"
    try:
        data = _api_get_json(url, timeout_sec=timeout_sec)
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as e:
        logger.info("tags list unavailable for %s: %s", slug, e)
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


def github_archive_zip_url(slug: str, *, ref_heads_or_tags: str, ref_name: str) -> str:
    base = normalize_repo_slug_str(slug)
    rot = ref_heads_or_tags.strip().lower()
    if rot not in ("heads", "tags"):
        raise ValueError("ref_heads_or_tags must be heads or tags")
    name = ref_name.strip().strip("/")
    if not name:
        raise ValueError("empty ref_name")
    from urllib.parse import quote

    q = quote(name, safe="")
    return f"https://github.com/{base}/archive/refs/{rot}/{q}.zip"


def stream_download_zip(url: str, *, timeout_sec: float = 300.0, progress: Callable[[int, int | None], None] | None = None) -> bytes:
    req = Request(url, headers={"User-Agent": _USER_AGENT_APP})
    with urlopen(req, timeout=timeout_sec) as resp:
        total: int | None = None
        cl = resp.headers.get("Content-Length")
        if cl is not None and str(cl).isdigit():
            total = int(cl)
        chunks: list[bytes] = []
        read_n = 0
        while True:
            block = resp.read(65536)
            if not block:
                break
            chunks.append(block)
            read_n += len(block)
            if progress is not None:
                progress(read_n, total)
    return b"".join(chunks)


def _zip_top_folder_name(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if not names:
            raise ValueError("empty archive")
        top = names[0].split("/")[0]
        if not top:
            raise ValueError("invalid archive layout")
        return top


def merge_source_tree_into(
    dest_root: Path,
    source_top: Path,
    *,
    also_skip_top_level: frozenset[str] = frozenset(),
) -> None:
    """
    将 source_top 下的条目合并进 dest_root：文件覆盖拷贝，跳过常见依赖与 VCS 目录。

    ``also_skip_top_level``：在归档根下按「首段路径名」整棵跳过的目录名（不区分大小写），
    用于主程序更新时保留本机 ``plugins/``、``data/`` 等。
    """
    skip_root = frozenset(
        {".git", "venv", ".venv", "__pycache__", "node_modules", ".cursor", "dist", "build", ".idea"}
    ) | {n.casefold() for n in also_skip_top_level}

    dest_root.mkdir(parents=True, exist_ok=True)
    if not source_top.is_dir():
        raise NotADirectoryError(str(source_top))

    for root, dirs, files in os.walk(source_top, followlinks=False):
        rel = Path(root).relative_to(source_top)
        parts = rel.parts if rel.parts != (".",) else ()
        if parts and parts[0].casefold() in skip_root:
            dirs.clear()
            continue
        dirs[:] = [
            d
            for d in dirs
            if d.casefold() not in skip_root and not d.endswith(".egg-info")
        ]
        rp = "_".join(parts) if parts else ""
        if ".git" in parts or rp.startswith(".git"):
            dirs.clear()
            continue
        dst_dir = dest_root.joinpath(*parts) if parts else dest_root
        dst_dir.mkdir(parents=True, exist_ok=True)
        for fn in files:
            if fn in (".git",):
                continue
            sp = Path(root) / fn
            dp = dst_dir / fn
            shutil.copy2(sp, dp)


def resolve_ref_for_download(slug: str, ref_kind: RefKindApi, tag_name: str) -> tuple[str, str]:
    """
    Returns (heads|tags, ref_segment) for ZIP URL构建。
    latest：优先 GitHub Releases 最新 tag；无 release 则用 heads/main→master。
    """
    slug = normalize_repo_slug_str(slug)
    if ref_kind == "tag":
        t = tag_name.strip()
        if not t:
            raise ValueError("missing tag_name for ref_kind tag")
        return "tags", t
    if ref_kind == "head":
        return "heads", resolve_default_branch_slug(slug)
    # latest
    tag = fetch_latest_release_tag(slug)
    if tag:
        return "tags", tag
    return "heads", resolve_default_branch_slug(slug)


def resolve_default_branch_slug(slug: str) -> str:
    """返回存在的默认分支名 main 或 master。"""
    for br in ("main", "master"):
        url = github_archive_zip_url(slug, ref_heads_or_tags="heads", ref_name=br)
        req = Request(url, headers={"User-Agent": _USER_AGENT_APP, "Accept": "*/*"})
        try:
            with urlopen(req, timeout=15.0) as resp:
                if resp.status in (200, 206):
                    return br
        except HTTPError as e:
            if e.code != 404:
                logger.debug("probe branch %s: HTTP %s", br, e.code)
        except URLError:
            break
        except OSError:
            break
    return "main"


def download_zip_extract_top_folder(
    slug: str,
    *,
    ref_heads_or_tags: str,
    ref_name: str,
    progress: Callable[[int, int | None], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
    timeout_sec: float = 300.0,
) -> tuple[Path, Path]:
    """
    下载并解压归档到临时目录，返回 ``(temporary_parent, extracted_top_folder)``。
    调用方负责善后删除 temporary_parent。
    """
    slug = normalize_repo_slug_str(slug)
    url = github_archive_zip_url(slug, ref_heads_or_tags=ref_heads_or_tags, ref_name=ref_name)
    body = stream_download_zip(url, timeout_sec=timeout_sec, progress=progress)

    td = Path(tempfile.mkdtemp(prefix="ghzip_"))
    zip_path = td / "_src.zip"
    zip_path.write_bytes(body)
    top_name = _zip_top_folder_name(zip_path)
    if on_phase is not None:
        on_phase("extract")
    extract_into = td / "_out"
    extract_into.mkdir()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_into)
    zip_path.unlink(missing_ok=True)
    extracted_top = extract_into / top_name
    if not extracted_top.is_dir():
        shutil.rmtree(td, ignore_errors=True)
        raise RuntimeError(f"extract missing top folder {top_name}")
    return td, extracted_top


def overwrite_merge_app_tree(slug: str, ref_kind: RefKindApi, tag_name: str, *, progress, on_phase) -> None:
    """下载指定 ref 并把归档根目录内容合并覆盖到当前工程根目录（不覆盖本机 ``plugins/``、``data/``）。"""
    rr = resolve_ref_for_download(slug, ref_kind, tag_name)
    td, extracted = download_zip_extract_top_folder(
        slug,
        ref_heads_or_tags=rr[0],
        ref_name=rr[1],
        progress=progress,
        on_phase=on_phase,
    )
    try:
        dest = resolve_project_root()
        merge_source_tree_into(
            dest,
            extracted,
            also_skip_top_level=frozenset({"plugins", "data"}),
        )
    finally:
        shutil.rmtree(td, ignore_errors=True)


def install_github_plugin_under_plugins(
    repo: str,
    *,
    catalog_display_name: str,
    ref_kind: RefKindApi,
    tag_name: str,
    overwrite: bool,
    plugins_parent: Path | None,
    progress: Callable[[int, int | None], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> Path:
    """
    将 GitHub 归档解压到 plugins/。
    overwrite=True：若目标文件夹已存在则先删除再替换；False：目录已存在时仅合并覆盖文件。
    """
    slug = normalize_repo_slug_str(repo)
    rr = resolve_ref_for_download(slug, ref_kind, tag_name)
    td, extracted_top = download_zip_extract_top_folder(
        slug,
        ref_heads_or_tags=rr[0],
        ref_name=rr[1],
        progress=progress,
        on_phase=on_phase,
        timeout_sec=300.0,
    )
    try:
        parent = Path(plugins_parent) if plugins_parent is not None else Path("plugins")
        parent.mkdir(parents=True, exist_ok=True)
        dn_raw = sanitize_plugins_directory_name((catalog_display_name or "").strip())
        if not dn_raw:
            tail = slug.split("/")[-1] if "/" in slug else slug
            dn_raw = sanitize_plugins_directory_name(tail)
        dest = parent / dn_raw

        if dest.is_dir():
            if overwrite:
                shutil.rmtree(dest, ignore_errors=True)
            else:
                merge_source_tree_into(dest, extracted_top)
                return dest.resolve()

        shutil.move(str(extracted_top), str(dest))
        return dest.resolve()
    finally:
        shutil.rmtree(td, ignore_errors=True)
