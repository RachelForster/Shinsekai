"""Release asset discovery for the frontend migration helper."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import platform
from urllib.request import Request, urlopen

REPOSITORY = "RachelForster/Shinsekai"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    browser_download_url: str


@dataclass(frozen=True)
class DownloadTarget:
    url: str
    label: str
    direct: bool
    message: str


def normalize_machine(machine: str | None = None) -> str:
    value = (machine or platform.machine() or "").lower()
    if value in {"amd64", "x86_64", "x64"}:
        return "x64"
    if value in {"aarch64", "arm64"}:
        return "arm64"
    if value in {"i386", "i686", "x86"}:
        return "x86"
    return value or "unknown"


def current_platform_label(
    system: str | None = None,
    machine: str | None = None,
) -> str:
    system_name = (system or platform.system() or "Unknown").strip() or "Unknown"
    return f"{system_name} / {normalize_machine(machine)}"


def _arch_aliases(arch: str) -> tuple[str, ...]:
    if arch == "x64":
        return ("x64", "amd64", "x86_64")
    if arch == "arm64":
        return ("arm64", "aarch64")
    if arch == "x86":
        return ("x86", "i386", "i686")
    return (arch,)


def asset_preferences(
    system: str | None = None,
    machine: str | None = None,
) -> list[tuple[str, ...]]:
    system_name = (system or platform.system() or "").lower()
    arch = normalize_machine(machine)
    arch_aliases = _arch_aliases(arch)
    if system_name == "windows":
        return [
            *(tuple((alias, ".msi")) for alias in arch_aliases),
            *(tuple(("windows", alias, ".msi")) for alias in arch_aliases),
            *(tuple(("win", alias, ".msi")) for alias in arch_aliases),
            *(tuple((alias, "setup", ".exe")) for alias in arch_aliases),
            *(tuple(("windows", alias, ".exe")) for alias in arch_aliases),
            *(tuple(("win", alias, ".exe")) for alias in arch_aliases),
            (".msi",),
            ("setup", ".exe"),
            (".exe",),
        ]
    if system_name == "darwin":
        return [
            *(tuple((alias, ".dmg")) for alias in arch_aliases),
            *(tuple(("macos", alias, ".dmg")) for alias in arch_aliases),
            *(tuple(("darwin", alias, ".dmg")) for alias in arch_aliases),
            *(tuple((alias, ".app.tar.gz")) for alias in arch_aliases),
            (".dmg",),
            (".app.tar.gz",),
        ]
    if system_name == "linux":
        return [
            *(tuple((alias, ".appimage")) for alias in arch_aliases),
            *(tuple((alias, ".deb")) for alias in arch_aliases),
            *(tuple((alias, ".rpm")) for alias in arch_aliases),
            *(tuple(("linux", alias, ".appimage")) for alias in arch_aliases),
            *(tuple(("linux", alias, ".deb")) for alias in arch_aliases),
            *(tuple(("linux", alias, ".rpm")) for alias in arch_aliases),
            (".appimage",),
            (".deb",),
            (".rpm",),
        ]
    return [
        (arch,),
        (".msi",),
        (".exe",),
        (".dmg",),
        (".appimage",),
        (".deb",),
    ]


def release_asset_from_mapping(raw: Mapping[str, object]) -> ReleaseAsset | None:
    name = raw.get("name")
    url = raw.get("browser_download_url")
    if not isinstance(name, str) or not isinstance(url, str):
        return None
    if not name.strip() or not url.strip():
        return None
    return ReleaseAsset(name=name.strip(), browser_download_url=url.strip())


def select_release_asset(
    assets: Iterable[ReleaseAsset],
    *,
    system: str | None = None,
    machine: str | None = None,
) -> ReleaseAsset | None:
    asset_list = list(assets)
    for terms in asset_preferences(system, machine):
        for asset in asset_list:
            name = asset.name.lower()
            if all(term.lower() in name for term in terms):
                return asset
    return asset_list[0] if asset_list else None


def fetch_latest_release_assets(timeout_sec: float = 12.0) -> list[ReleaseAsset]:
    request = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Shinsekai-Migration-Helper",
        },
    )
    with urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw_assets = payload.get("assets", [])
    if not isinstance(raw_assets, list):
        return []
    assets: list[ReleaseAsset] = []
    for raw in raw_assets:
        if isinstance(raw, Mapping):
            asset = release_asset_from_mapping(raw)
            if asset is not None:
                assets.append(asset)
    return assets


def resolve_download_target(
    *,
    system: str | None = None,
    machine: str | None = None,
    timeout_sec: float = 12.0,
) -> DownloadTarget:
    assets = fetch_latest_release_assets(timeout_sec=timeout_sec)
    asset = select_release_asset(assets, system=system, machine=machine)
    if asset is None:
        return DownloadTarget(
            url=RELEASES_URL,
            label="Releases",
            direct=False,
            message="没有找到可下载的发行包，已打开 Releases 页面。",
        )
    return DownloadTarget(
        url=asset.browser_download_url,
        label=asset.name,
        direct=True,
        message=f"已匹配当前平台发行包：{asset.name}",
    )
