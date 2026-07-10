from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TAURI_CONFIG = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
INSTALLER_TEMPLATE = REPO_ROOT / "frontend" / "src-tauri" / "windows" / "installer.nsi"
FRONTEND_LOCK = REPO_ROOT / "frontend" / "pnpm-lock.yaml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
UPSTREAM_BASELINE_SHA256 = (
    "ee84148e405adc4d736a46456dd8345a644751bd1f28a335dd7fd833a32d7c3e"
)
COMPAT_BEGIN = "SHINSEKAI MSI->NSIS COMPAT BEGIN"
COMPAT_END = "SHINSEKAI MSI->NSIS COMPAT END"


def _installer_text() -> str:
    return INSTALLER_TEMPLATE.read_text(encoding="utf-8")


def _strip_shinsekai_changes(template: str) -> str:
    """Reconstruct the byte-for-byte upstream template from marked changes."""

    upstream: list[str] = []
    before_upstream = True
    inside_change = False
    for line in template.splitlines(keepends=True):
        if before_upstream:
            if line == "Unicode true\n":
                before_upstream = False
                upstream.append(line)
            continue
        if COMPAT_BEGIN in line:
            assert not inside_change
            inside_change = True
            continue
        if COMPAT_END in line:
            assert inside_change
            inside_change = False
            continue
        if not inside_change:
            upstream.append(line)
    assert not before_upstream
    assert not inside_change
    return "".join(upstream)


def test_custom_template_is_pinned_to_exact_tauri_2_11_2_baseline() -> None:
    template = _installer_text()

    assert "Tauri 2.11.2 / tauri-bundler 2.9.2" in template
    reconstructed = _strip_shinsekai_changes(template).encode("utf-8")
    assert hashlib.sha256(reconstructed).hexdigest() == UPSTREAM_BASELINE_SHA256

    importer = FRONTEND_LOCK.read_text(encoding="utf-8").split("packages:", 1)[0]
    assert re.search(
        r"'@tauri-apps/cli':\s+specifier: \^2\.11\.2\s+version: 2\.11\.2(?:\s|$)",
        importer,
    )


def test_tauri_uses_current_user_custom_nsis_template() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    nsis = config["bundle"]["windows"]["nsis"]

    assert nsis["installMode"] == "currentUser"
    assert nsis["template"] == "./windows/installer.nsi"
    assert INSTALLER_TEMPLATE.is_file()


def test_msi_path_is_captured_before_gui_or_passive_wix_uninstall() -> None:
    template = _installer_text()
    page_reinstall = template.index("Function PageReinstall\n")
    matched_wix = template.index("StrCpy $WixMode 1", page_reinstall)
    inherit = template.index("Call InheritLegacyMsiInstallDir", matched_wix)
    leave_reinstall = template.index("Function PageLeaveReinstall\n", inherit)
    uninstall = template.index("ExecWait '$R1' $0", leave_reinstall)

    assert matched_wix < inherit < leave_reinstall < uninstall
    assert 'ReadRegStr $LegacyMsiCandidate HKLM "$R6" "InstallLocation"' in template
    assert (
        'ReadRegStr $LegacyMsiCandidate HKCU "${MANUPRODUCTKEY}" "InstallDir"'
        in template
    )
    assert '${GetOptions} $CMDLINE "/P" $PassiveMode' in template
    assert '${GetOptions} $CMDLINE "/UPDATE" $UpdateMode' in template


def test_explicit_or_existing_nsis_location_blocks_msi_inheritance() -> None:
    template = _installer_text()
    on_init = template[template.index("Function .onInit\n") : template.index("Section EarlyChecks")]

    placeholder_guard = on_init.index('${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"')
    enable_inheritance = on_init.index("StrCpy $CanInheritLegacyMsiInstallDir 1")
    restore_nsis = on_init.index("Call RestorePreviousInstallLocation")
    read_nsis = on_init.index('ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""')
    disable_inheritance = on_init.index("StrCpy $CanInheritLegacyMsiInstallDir 0", read_nsis)

    assert placeholder_guard < enable_inheritance < restore_nsis
    assert restore_nsis < read_nsis < disable_inheritance


def test_true_silent_msi_transition_fails_closed_before_install_sections() -> None:
    template = _installer_text()
    on_init = template[template.index("Function .onInit\n") : template.index("Section EarlyChecks")]
    fail_closed = template[
        template.index("Function AbortSilentLegacyWixMigration\n") : template.index(
            COMPAT_END, template.index("Function AbortSilentLegacyWixMigration\n")
        )
    ]

    assert "${If} ${Silent}" in on_init
    assert "Call AbortSilentLegacyWixMigration" in on_init
    assert '"DisplayName"' in fail_closed
    assert '"Publisher"' in fail_closed
    assert '"UninstallString"' in fail_closed
    assert '"msiexec"' in fail_closed
    assert "GetStdHandle(i -12) p .r0" in fail_closed
    assert 'FileWrite $0 "Shinsekai:' in fail_closed
    assert "SetErrorLevel 3" in fail_closed
    assert "Quit" in fail_closed


def test_legacy_path_validation_is_local_existing_and_writable() -> None:
    template = _installer_text()
    validation = template[
        template.index("Function ValidateLegacyMsiInstallDir\n") : template.index(
            "Function InheritLegacyMsiInstallDir\n"
        )
    ]

    assert "GetFullPathName" in validation
    assert "GetDriveTypeW" in validation
    assert 'IfFileExists "$0\\."' in validation
    assert 'IfFileExists "$0\\${MAINBINARYNAME}.exe"' in validation
    assert "shinsekai-nsis-write-probe-$2-$3.tmp" in validation
    assert "CreateFileW" in validation
    assert "WriteFile" in validation
    assert "i 1" in validation  # CREATE_NEW: never truncate a colliding path.
    assert "FileOpen" not in validation
    assert 'Delete "$4"' in validation
    assert "RmDir" not in validation
    assert "DeleteReg" not in validation


def test_release_workflow_keeps_windows_assets_nsis_only() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("bundles: nsis") >= 2
    assert 'bundle/nsis/*.exe" "${base}-setup.exe"' in workflow
    assert 'bundle/msi/*.msi" "${base}.msi"' not in workflow
    assert "Delete stale Windows MSI release assets" in workflow
