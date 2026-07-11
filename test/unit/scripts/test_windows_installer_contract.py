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
TAURI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tauri-desktop.yml"
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


def test_msi_path_is_captured_and_required_before_wix_uninstall() -> None:
    template = _installer_text()
    page_reinstall = template.index("Function PageReinstall\n")
    matched_wix = template.index("StrCpy $WixMode 1", page_reinstall)
    inherit = template.index("Call InheritLegacyMsiInstallDir", matched_wix)
    blocked_guard = template.index(
        "${If} $LegacyMsiMigrationBlocked = 1", inherit
    )
    blocked_abort = template.index(
        "Call AbortBlockedLegacyMsiMigration", blocked_guard
    )
    leave_reinstall = template.index("Function PageLeaveReinstall\n", inherit)
    uninstall = template.index("ExecWait '$R1' $0", leave_reinstall)

    assert matched_wix < inherit < blocked_guard < blocked_abort < leave_reinstall < uninstall
    assert 'ReadRegStr $LegacyMsiCandidate HKLM "$R6" "InstallLocation"' in template
    assert (
        'ReadRegStr $LegacyMsiCandidate HKCU "${MANUPRODUCTKEY}" "InstallDir"'
        in template
    )
    assert '${GetOptions} $CMDLINE "/P" $PassiveMode' in template
    assert '${GetOptions} $CMDLINE "/UPDATE" $UpdateMode' in template


def test_existing_nsis_bypasses_msi_while_explicit_target_only_blocks_inheritance() -> None:
    template = _installer_text()
    on_init = template[template.index("Function .onInit\n") : template.index("Section EarlyChecks")]
    page_reinstall = template[
        template.index("Function PageReinstall\n") : template.index(
            "Function PageReinstallUpdateSelection\n"
        )
    ]
    silent_migration = template[
        template.index("Function AbortSilentLegacyWixMigration\n") : template.index(
            COMPAT_END, template.index("Function AbortSilentLegacyWixMigration\n")
        )
    ]

    placeholder_guard = on_init.index('${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"')
    enable_inheritance = on_init.index("StrCpy $CanInheritLegacyMsiInstallDir 1")
    save_platform_default = on_init.index(
        'StrCpy $LegacyMigrationDefaultInstallDir "$INSTDIR"', placeholder_guard
    )
    restore_nsis = on_init.index("Call RestorePreviousInstallLocation")
    read_nsis = on_init.index('ReadRegStr $5 SHCTX "${MANUPRODUCTKEY}" ""')
    mark_existing_nsis = on_init.index(
        "StrCpy $HasAuthoritativeNsisInstallDir 1", read_nsis
    )
    authority_guard = on_init.index(
        "${If} $HasAuthoritativeNsisInstallDir = 1", restore_nsis
    )
    disable_inheritance = on_init.index(
        "StrCpy $CanInheritLegacyMsiInstallDir 0", authority_guard
    )
    restore_platform_default = on_init.index(
        'StrCpy $INSTDIR "$LegacyMigrationDefaultInstallDir"', authority_guard
    )
    read_legacy_msi = on_init.index(
        'ReadRegStr $LegacyMsiCandidate HKCU "${MANUPRODUCTKEY}" "InstallDir"',
        restore_platform_default,
    )

    assert read_nsis < mark_existing_nsis < placeholder_guard
    assert placeholder_guard < enable_inheritance < save_platform_default < restore_nsis
    assert restore_nsis < authority_guard < disable_inheritance
    assert authority_guard < restore_platform_default < read_legacy_msi
    restore_function = template[
        template.index("Function RestorePreviousInstallLocation\n") : template.index(
            "FunctionEnd", template.index("Function RestorePreviousInstallLocation\n")
        )
    ]
    assert "$LegacyMigrationDefaultInstallDir" not in restore_function
    assert on_init.index("StrCpy $CanInheritLegacyMsiInstallDir 0") < placeholder_guard

    page_authority_guard = page_reinstall.index(
        "${If} $HasAuthoritativeNsisInstallDir = 1"
    )
    page_skip = page_reinstall.index("Goto wix_loop_done", page_authority_guard)
    page_enumeration = page_reinstall.index("EnumRegKey $1 HKLM")
    assert page_authority_guard < page_skip < page_enumeration

    silent_authority_guard = silent_migration.index(
        "${If} $HasAuthoritativeNsisInstallDir = 1"
    )
    silent_skip = silent_migration.index("Goto silent_wix_done", silent_authority_guard)
    silent_enumeration = silent_migration.index("EnumRegKey $1 HKLM")
    assert silent_authority_guard < silent_skip < silent_enumeration

    inherit = template[
        template.index("Function InheritLegacyMsiInstallDir\n") : template.index(
            "Function AbortBlockedLegacyMsiMigration\n"
        )
    ]
    assert "${If} $CanInheritLegacyMsiInstallDir != 1" in inherit


def test_unavailable_or_unwritable_msi_root_fails_before_passive_uninstall() -> None:
    template = _installer_text()
    inherit = template[
        template.index("Function InheritLegacyMsiInstallDir\n") : template.index(
            "Function AbortBlockedLegacyMsiMigration\n"
        )
    ]
    blocked = template[
        template.index("Function AbortBlockedLegacyMsiMigration\n") : template.index(
            "Function AbortSilentLegacyWixMigration\n"
        )
    ]
    page_reinstall = template[
        template.index("Function PageReinstall\n") : template.index(
            "Function PageReinstallUpdateSelection\n"
        )
    ]
    leave_reinstall = template[
        template.index("Function PageLeaveReinstall\n") : template.index(
            "; 5. Choose install directory page"
        )
    ]

    assert "${Else}\n    StrCpy $LegacyMsiMigrationBlocked 1" in inherit
    assert "${If} $PassiveMode = 1" in blocked
    assert "MessageBox MB_OK|MB_ICONSTOP" in blocked
    assert "SetErrorLevel 3" in blocked
    assert "Quit" in blocked

    inherit_call = page_reinstall.index("Call InheritLegacyMsiInstallDir")
    blocked_check = page_reinstall.index("${If} $LegacyMsiMigrationBlocked = 1")
    abort_call = page_reinstall.index("Call AbortBlockedLegacyMsiMigration")
    passive_leave = page_reinstall.index("Call PageLeaveReinstall")
    assert inherit_call < blocked_check < abort_call < passive_leave
    assert "ExecWait '$R1' $0" not in page_reinstall
    assert "ExecWait '$R1' $0" in leave_reinstall


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
    authority_guard = fail_closed.index(
        "${If} $HasAuthoritativeNsisInstallDir = 1"
    )
    authority_skip = fail_closed.index("Goto silent_wix_done", authority_guard)
    msi_scan = fail_closed.index("EnumRegKey $1 HKLM")
    assert authority_guard < authority_skip < msi_scan
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


def test_windows_ci_renders_custom_nsis_and_runs_project_root_tests() -> None:
    workflow = TAURI_WORKFLOW.read_text(encoding="utf-8")
    build_job = workflow[workflow.index("\n  build:\n") :]
    release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    tauri_config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))

    assert tauri_config["build"]["frontendDist"] == "../dist"
    assert re.search(
        r"platform: windows-x64\s+os: windows-latest\s+bundles: nsis",
        build_job,
    )
    build_tauri = build_job.index("- name: Build Tauri bundle")
    test_project_root = build_job.index("- name: Test Windows project-root resolution")
    verify_runtime = build_job.index("- name: Verify packaged embedded Python runtime")
    assert build_tauri < test_project_root < verify_runtime

    project_root_step = build_job[test_project_root:verify_runtime]
    assert "if: runner.os == 'Windows'" in project_root_step
    assert (
        "cargo test --manifest-path frontend/src-tauri/Cargo.toml --release --lib project_root"
        in project_root_step
    )
    assert "Build frontend for Windows Tauri tests" not in build_job
    assert "shared-key: build" in build_job
    assert "shared-key: build" in release_workflow
    assert "choco install nsis" not in workflow
    assert "choco install nsis" not in release_workflow
    assert "frontend/src-tauri/target/release/bundle/nsis/*.exe" in build_job
