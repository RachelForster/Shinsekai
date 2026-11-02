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
MSI_MIGRATION_TEST = (
    REPO_ROOT / "frontend" / "scripts" / "test-msi-nsis-migration.ps1"
)
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


def test_msi_app_root_hint_is_persisted_before_wix_uninstall() -> None:
    template = _installer_text()
    page_reinstall = template.index("Function PageReinstall\n")
    matched_wix = template.index("StrCpy $WixMode 1", page_reinstall)
    product_code = template.index('StrCpy $LegacyMsiProductCode "$1"', matched_wix)
    validate = template.index("Call ValidateLegacyMsiProductCode", product_code)
    persist = template.index("Call PersistLegacyMsiAppRootHint", validate)
    leave_reinstall = template.index("Function PageLeaveReinstall\n", persist)
    uninstall = template.index(
        'ExecWait \'"$SYSDIR\\msiexec.exe" /X$LegacyMsiProductCode',
        leave_reinstall,
    )
    persist_function = template[
        template.index("Function PersistLegacyMsiAppRootHint\n") : template.index(
            "Function AbortLegacyMsiMigration\n"
        )
    ]

    assert matched_wix < product_code < validate < persist < leave_reinstall < uninstall
    assert 'ReadRegStr $LegacyMsiCandidate HKLM "$R6" "InstallLocation"' in persist_function
    assert (
        'ReadRegStr $LegacyMsiCandidate HKCU "Software\\shinsekai\\Shinsekai" "InstallDir"'
        in persist_function
    )
    assert (
        'ReadRegStr $LegacyMsiCandidate HKCU "Software\\Shinsekai Contributors\\Shinsekai" "InstallDir"'
        in persist_function
    )
    write_hint = persist_function.index(
        'WriteRegStr HKCU "${LEGACY_MIGRATION_KEY}" "LegacyMsiAppRoot"'
    )
    write_failure = persist_function.index("IfErrors", write_hint)
    abort_failure = persist_function.index("Call AbortLegacyMsiMigration", write_failure)
    assert write_hint < write_failure < abort_failure
    assert '${GetOptions} $CMDLINE "/P" $PassiveMode' in template
    assert '${GetOptions} $CMDLINE "/UPDATE" $UpdateMode' in template


def test_existing_nsis_wins_and_explicit_msi_transition_fails_before_uninstall() -> None:
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
    skip_after_msi = template[
        template.index("Function SkipIfPassive\n") : template.index(
            "FunctionEnd", template.index("Function SkipIfPassive\n")
        )
    ]

    placeholder_guard = on_init.index('${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"')
    explicit_guard = on_init.index('${If} $INSTDIR != "${PLACEHOLDER_INSTALL_DIR}"')
    mark_explicit = on_init.index("StrCpy $HasExplicitNsisInstallDir 1", explicit_guard)
    save_platform_default = on_init.index(
        'StrCpy $LegacyMigrationDefaultInstallDir "$INSTDIR"', placeholder_guard
    )
    restore_nsis = on_init.index("Call RestorePreviousInstallLocation")
    read_nsis = on_init.index('ReadRegStr $5 SHCTX "${MANUPRODUCTKEY}" ""')
    mark_existing_nsis = on_init.index(
        "StrCpy $HasAuthoritativeNsisInstallDir 1", read_nsis
    )
    authority_guard = on_init.index(
        "${If} $HasAuthoritativeNsisInstallDir != 1", restore_nsis
    )
    restore_platform_default = on_init.index(
        'StrCpy $INSTDIR "$LegacyMigrationDefaultInstallDir"', authority_guard
    )

    assert explicit_guard < mark_explicit < read_nsis < mark_existing_nsis < placeholder_guard
    assert placeholder_guard < save_platform_default < restore_nsis
    assert restore_nsis < authority_guard < restore_platform_default
    assert 'StrCpy $INSTDIR "$LOCALAPPDATA\\${PRODUCTNAME}"' in on_init
    assert "ReadRegStr $LegacyMsiCandidate" not in on_init
    restore_function = template[
        template.index("Function RestorePreviousInstallLocation\n") : template.index(
            "FunctionEnd", template.index("Function RestorePreviousInstallLocation\n")
        )
    ]
    assert "$LegacyMigrationDefaultInstallDir" not in restore_function
    assert "CanInheritLegacyMsiInstallDir" not in template
    assert "LegacyMsiInstallDir" not in template
    assert not re.search(r"StrCpy\s+\$INSTDIR\s+\"?\$LegacyMsi", template)

    page_authority_guard = page_reinstall.index(
        "${If} $HasAuthoritativeNsisInstallDir = 1"
    )
    page_skip = page_reinstall.index("Goto wix_loop_done", page_authority_guard)
    page_enumeration = page_reinstall.index("EnumRegKey $1 HKLM")
    assert page_authority_guard < page_skip < page_enumeration
    explicit_msi_guard = page_reinstall.index("${If} $HasExplicitNsisInstallDir = 1")
    explicit_msi_abort = page_reinstall.index(
        "Call AbortExplicitLegacyMsiTarget", explicit_msi_guard
    )
    persist_hint = page_reinstall.index("Call PersistLegacyMsiAppRootHint")
    assert explicit_msi_guard < explicit_msi_abort < persist_hint
    assert "${IfThen} $WixMode = 1 ${|} Abort ${|}" in skip_after_msi

    silent_authority_guard = silent_migration.index(
        "${If} $HasAuthoritativeNsisInstallDir = 1"
    )
    silent_skip = silent_migration.index("Goto silent_wix_done", silent_authority_guard)
    silent_enumeration = silent_migration.index("EnumRegKey $1 HKLM")
    assert silent_authority_guard < silent_skip < silent_enumeration


def test_msi_identity_and_uninstall_are_fixed_fail_closed_contracts() -> None:
    template = _installer_text()
    blocked = template[
        template.index("Function AbortLegacyMsiMigration\n") : template.index(
            "Function AbortSilentLegacyWixMigration\n"
        )
    ]
    explicit_blocked = template[
        template.index("Function AbortExplicitLegacyMsiTarget\n") : template.index(
            "Function AbortLegacyMsiMigration\n"
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

    assert "${If} $PassiveMode = 1" in blocked
    assert "MessageBox MB_OK|MB_ICONSTOP" in blocked
    assert "SetErrorLevel 3" in blocked
    assert "Quit" in blocked
    assert "cannot use an explicit /D target" in explicit_blocked
    assert "SetErrorLevel 3" in explicit_blocked
    assert "Quit" in explicit_blocked

    assert 'StrCmp "$R1" "${MANUFACTURER}" wix_publisher_match' in page_reinstall
    assert 'StrCmp "$R1" "shinsekai" wix_publisher_match wix_loop' in page_reinstall
    assert 'ReadRegDWORD $R2 HKLM' in page_reinstall
    assert '"WindowsInstaller"' in page_reinstall
    validate_call = page_reinstall.index("Call ValidateLegacyMsiProductCode")
    persist_call = page_reinstall.index("Call PersistLegacyMsiAppRootHint")
    passive_leave = page_reinstall.index("Call PageLeaveReinstall")
    assert validate_call < persist_call < passive_leave
    assert "ExecWait '$R1' $0" not in page_reinstall
    assert '"$SYSDIR\\msiexec.exe" /X$LegacyMsiProductCode /passive /norestart' in leave_reinstall
    assert '"$SYSDIR\\msiexec.exe" /X$LegacyMsiProductCode /norestart' in leave_reinstall
    assert 'ReadRegStr $R1 HKLM "$R6" "DisplayName"' in leave_reinstall
    assert 'MsiQueryProductStateW(w "$LegacyMsiProductCode")' in leave_reinstall
    assert "${ElseIf} $1 != -1" in leave_reinstall
    assert '"$LegacyMsiCandidate\\${MAINBINARYNAME}.exe"' in leave_reinstall
    assert "SetRebootFlag true" in leave_reinstall
    assert "StrCpy $LegacyMsiRebootRequired 1" in leave_reinstall
    assert "${If} $LegacyMsiRebootRequired != 1" in leave_reinstall
    assert 'GetFullPathName $R2 "$INSTDIR"' not in leave_reinstall
    reboot_success = leave_reinstall.index("SetRebootFlag true")
    product_state_guard = leave_reinstall.index("${If} $0 = 0", reboot_success)
    product_state_check = leave_reinstall.index("MsiQueryProductStateW", product_state_guard)
    assert reboot_success < product_state_guard < product_state_check
    passive_failure = leave_reinstall.index("${If} $PassiveMode = 1")
    assert leave_reinstall.index("SetErrorLevel $0", passive_failure) < leave_reinstall.index(
        "Quit", passive_failure
    )
    wix_success = leave_reinstall.index("${If} $0 = 0", passive_failure)
    bypass_instdir = leave_reinstall.index("Goto reinst_done", wix_success)
    upstream_instdir_check = leave_reinstall.index(
        '${OrIf} ${FileExists} "$INSTDIR\\${MAINBINARYNAME}.exe"', bypass_instdir
    )
    assert wix_success < bypass_instdir < upstream_instdir_check

    product_validation = template[
        template.index("Function ValidateLegacyMsiProductCode\n") : template.index(
            "Function ValidateLegacyMsiAppRoot\n"
        )
    ]
    assert '${If} $0 != 38' in product_validation
    assert 'StrCmp $2 "{"' in product_validation
    assert 'StrCmp $2 "}"' in product_validation
    assert 'StrCmp $2 "-"' in product_validation


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

    # Pinned Tauri's SetContext selects the target architecture's registry view
    # before either page callbacks or the silent scan run. The released x64 MSI
    # registers in Registry64.
    set_context = on_init.index("!insertmacro SetContext")
    silent_call = on_init.index("Call AbortSilentLegacyWixMigration")
    assert set_context < silent_call


def test_legacy_path_validation_checks_identity_without_write_permission_probe() -> None:
    template = _installer_text()
    validation = template[
        template.index("Function ValidateLegacyMsiAppRoot\n") : template.index(
            "Function PersistLegacyMsiAppRootHint\n"
        )
    ]

    assert "GetFullPathName" in validation
    assert "GetDriveTypeW" in validation
    assert 'IfFileExists "$0\\."' in validation
    assert 'IfFileExists "$0\\${MAINBINARYNAME}.exe"' in validation
    assert "shinsekai-nsis-write-probe" not in validation
    assert "CreateFileW" not in validation
    assert "WriteFile" not in validation
    assert "FileOpen" not in validation
    assert "RmDir" not in validation
    assert "DeleteReg" not in validation


def test_release_workflow_keeps_windows_assets_nsis_only() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("bundles: nsis") >= 2
    assert 'bundle/nsis/*.exe" "${base}-setup.exe"' in workflow
    assert 'bundle/msi/*.msi" "${base}.msi"' not in workflow
    assert "Delete stale Windows MSI release assets" in workflow

    template = _installer_text()
    delete_data = template[
        template.index("${If} $DeleteAppDataCheckboxState = 1") : template.index(
            "SetShellVarContext current",
            template.index("${If} $DeleteAppDataCheckboxState = 1"),
        )
    ]
    assert 'DeleteRegKey HKCU "${LEGACY_MIGRATION_KEY}"' in delete_data


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
    restore_legacy_msi = build_job.index("- name: Restore legacy MSI fixture cache")
    migration_test = build_job.index("- name: Test real MSI-to-NSIS migration")
    save_legacy_msi = build_job.index("- name: Save verified legacy MSI fixture cache")
    test_project_root = build_job.index("- name: Test Windows project-root resolution")
    verify_runtime = build_job.index("- name: Verify packaged embedded Python runtime")
    assert (
        build_tauri
        < restore_legacy_msi
        < migration_test
        < save_legacy_msi
        < test_project_root
        < verify_runtime
    )

    legacy_msi_path = ".cache/legacy-installers/Shinsekai-2.1.0_windows-x64.msi"
    legacy_msi_cache_prefix = (
        "legacy-msi-windows-x64-v2.1.0-sha256-"
        "c896cc45f718a41f9e2183d624e8af60c998718a3842ed2686f745f93b6cdce9-v2-"
    )
    legacy_msi_cache_key = (
        legacy_msi_cache_prefix
        + "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    legacy_msi_cache = build_job[restore_legacy_msi:migration_test]
    assert "if: matrix.platform == 'windows-x64'" in legacy_msi_cache
    assert "uses: actions/cache/restore@v4" in legacy_msi_cache
    assert "continue-on-error: true" in legacy_msi_cache
    assert legacy_msi_path in legacy_msi_cache
    assert f"key: {legacy_msi_cache_key}" in legacy_msi_cache
    assert f"restore-keys: |\n            {legacy_msi_cache_prefix}" in legacy_msi_cache

    migration_step = build_job[migration_test:save_legacy_msi]
    assert "if: matrix.platform == 'windows-x64'" in migration_step
    assert "id: msi-migration-test" in migration_step
    assert "shell: pwsh" in migration_step
    assert "./frontend/scripts/test-msi-nsis-migration.ps1" in migration_step
    assert (
        "-LegacyMsiPath '.cache/legacy-installers/"
        "Shinsekai-2.1.0_windows-x64.msi'"
        in migration_step
    )

    save_cache_step = build_job[save_legacy_msi:test_project_root]
    assert "if: success()" in save_cache_step
    assert "steps.msi-migration-test.outputs.legacy-msi-updated == 'true'" in save_cache_step
    assert "uses: actions/cache/save@v4" in save_cache_step
    assert "continue-on-error: true" in save_cache_step
    assert legacy_msi_path in save_cache_step
    assert f"key: {legacy_msi_cache_key}" in save_cache_step
    assert MSI_MIGRATION_TEST.is_file()
    migration_script = MSI_MIGRATION_TEST.read_text(encoding="utf-8")
    assert (
        "https://github.com/RachelForster/Shinsekai/releases/download/v2.1.0/"
        "Shinsekai-2.1.0_windows-x64.msi"
    ) in migration_script
    assert (
        '"c896cc45f718a41f9e2183d624e8af60c998718a3842ed2686f745f93b6cdce9"'
        in migration_script
    )
    assert '"LegacyMsiAppRoot"' in migration_script
    assert '@("/P", "/UPDATE", "/NS")' in migration_script
    assert "Registry64" in migration_script
    assert "ExpectedNsisInstallDir" in migration_script
    assert '[string]$LegacyMsiPath = ""' in migration_script
    assert "[int]$MaxAttempts = 5" in migration_script
    assert "[int]$TotalTimeoutSeconds = 360" in migration_script
    assert "$httpClient.Timeout = [TimeSpan]::FromSeconds" in migration_script
    assert "$httpClient.GetByteArrayAsync($Uri).GetAwaiter().GetResult()" in migration_script
    assert "[IO.File]::WriteAllBytes($partialPath, $downloadBytes)" in migration_script
    assert '"legacy-msi-updated="' in migration_script
    assert '"$DestinationPath.partial.$PID"' in migration_script
    partial_hash = migration_script.index(
        "Get-FileHash -LiteralPath $partialPath -Algorithm SHA256"
    )
    verified_move = migration_script.index(
        "Move-Item -LiteralPath $partialPath -Destination $DestinationPath"
    )
    final_hash = migration_script.index(
        "Get-FileHash -LiteralPath $LegacyMsiPath -Algorithm SHA256"
    )
    msi_install = migration_script.index("Invoke-CheckedProcess -FilePath $msiexec")
    assert partial_hash < verified_move < final_hash < msi_install
    assert "Invoke-WebRequest" not in migration_script
    assert "MaximumRetryCount" not in migration_script

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
