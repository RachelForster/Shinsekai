from __future__ import annotations

from ui.migrate_helper.release import (
    ReleaseAsset,
    current_platform_label,
    select_release_asset,
)


def _asset(name: str) -> ReleaseAsset:
    return ReleaseAsset(name=name, browser_download_url=f"https://example.test/{name}")


def test_selects_windows_msi_before_setup_exe() -> None:
    asset = select_release_asset(
        [
            _asset("Shinsekai_0.1.0_x64-setup.exe"),
            _asset("Shinsekai_0.1.0_x64_en-US.msi"),
        ],
        system="Windows",
        machine="AMD64",
    )

    assert asset is not None
    assert asset.name == "Shinsekai_0.1.0_x64_en-US.msi"


def test_selects_macos_arm_dmg() -> None:
    asset = select_release_asset(
        [
            _asset("Shinsekai_0.1.0_x64.dmg"),
            _asset("Shinsekai_0.1.0_aarch64.dmg"),
        ],
        system="Darwin",
        machine="arm64",
    )

    assert asset is not None
    assert asset.name == "Shinsekai_0.1.0_aarch64.dmg"


def test_selects_linux_appimage_before_deb() -> None:
    asset = select_release_asset(
        [
            _asset("Shinsekai_0.1.0_amd64.deb"),
            _asset("Shinsekai_0.1.0_amd64.AppImage"),
        ],
        system="Linux",
        machine="x86_64",
    )

    assert asset is not None
    assert asset.name == "Shinsekai_0.1.0_amd64.AppImage"


def test_platform_label_normalizes_machine() -> None:
    assert current_platform_label("Windows", "AMD64") == "Windows / x64"
