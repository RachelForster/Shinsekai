from __future__ import annotations

from ui.migrate_helper.release import (
    ReleaseAsset,
    current_platform_label,
    default_download_dir,
    safe_asset_filename,
    select_release_asset,
    unique_download_path,
)


def _asset(name: str) -> ReleaseAsset:
    return ReleaseAsset(name=name, browser_download_url=f"https://example.test/{name}")


def test_selects_windows_setup_exe_before_legacy_msi() -> None:
    asset = select_release_asset(
        [
            _asset("Shinsekai_0.1.0_x64-setup.exe"),
            _asset("Shinsekai_0.1.0_x64_en-US.msi"),
        ],
        system="Windows",
        machine="AMD64",
    )

    assert asset is not None
    assert asset.name == "Shinsekai_0.1.0_x64-setup.exe"


def test_windows_installer_does_not_select_updater_signature() -> None:
    asset = select_release_asset(
        [
            _asset("Shinsekai_0.1.0_x64-setup.exe.sig"),
            _asset("Shinsekai_0.1.0_x64-setup.exe"),
        ],
        system="Windows",
        machine="AMD64",
    )

    assert asset is not None
    assert asset.name == "Shinsekai_0.1.0_x64-setup.exe"


def test_windows_does_not_fall_back_to_updater_signature() -> None:
    asset = select_release_asset(
        [_asset("Shinsekai_0.1.0_x64-setup.exe.sig")],
        system="Windows",
        machine="AMD64",
    )

    assert asset is None


def test_windows_falls_back_to_legacy_msi_when_no_nsis_asset_exists() -> None:
    asset = select_release_asset(
        [_asset("Shinsekai_0.1.0_x64_en-US.msi")],
        system="Windows",
        machine="AMD64",
    )

    assert asset is not None
    assert asset.name == "Shinsekai_0.1.0_x64_en-US.msi"


def test_windows_legacy_msi_wins_over_unrelated_helper_executable() -> None:
    asset = select_release_asset(
        [
            _asset("Shinsekai-migration-helper.exe"),
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


def test_safe_asset_filename_removes_invalid_path_chars() -> None:
    assert safe_asset_filename('Shinsekai:setup/preview?.msi') == "preview_.msi"


def test_default_download_dir_uses_downloads_folder(tmp_path) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    assert default_download_dir(tmp_path) == downloads / "Shinsekai"


def test_unique_download_path_adds_suffix_when_file_exists(tmp_path) -> None:
    (tmp_path / "Shinsekai.msi").write_text("", encoding="utf-8")

    assert unique_download_path(tmp_path, "Shinsekai.msi") == tmp_path / "Shinsekai-1.msi"
