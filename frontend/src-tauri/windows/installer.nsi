; Shinsekai custom NSIS installer template.
;
; Upstream baseline: Tauri 2.11.2 / tauri-bundler 2.9.2
; https://github.com/tauri-apps/tauri/blob/tauri-v2.11.2/crates/tauri-bundler/src/bundle/windows/nsis/installer.nsi
; Baseline SHA-256: ee84148e405adc4d736a46456dd8345a644751bd1f28a335dd7fd833a32d7c3e
;
; Project-only changes are enclosed by `SHINSEKAI MSI->NSIS COMPAT` markers.
; They preserve a legacy WiX/MSI app-root recovery hint before the upstream
; reinstall page removes the MSI, while keeping the current-user NSIS itself in
; LocalAppData. Rust only offers that hint when strong project data remains.
; Keep the rest of this file in sync with the pinned upstream template.

Unicode true
ManifestDPIAware true
; Add in `dpiAwareness` `PerMonitorV2` to manifest for Windows 10 1607+ (note this should not affect lower versions since they should be able to ignore this and pick up `dpiAware` `true` set by `ManifestDPIAware true`)
; Currently undocumented on NSIS's website but is in the Docs folder of source tree, see
; https://github.com/kichik/nsis/blob/5fc0b87b819a9eec006df4967d08e522ddd651c9/Docs/src/attributes.but#L286-L300
; https://github.com/tauri-apps/tauri/pull/10106
ManifestDPIAwareness PerMonitorV2

!if "{{compression}}" == "none"
  SetCompress off
!else
  ; Set the compression algorithm. We default to LZMA.
  SetCompressor /SOLID "{{compression}}"
!endif

!include MUI2.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!include "StrFunc.nsh"
${StrCase}
${StrLoc}

{{#if installer_hooks}}
!include "{{installer_hooks}}"
{{/if}}

!define WEBVIEW2APPGUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

!define MANUFACTURER "{{manufacturer}}"
!define PRODUCTNAME "{{product_name}}"
!define VERSION "{{version}}"
!define VERSIONWITHBUILD "{{version_with_build}}"
!define HOMEPAGE "{{homepage}}"
!define INSTALLMODE "{{install_mode}}"
!define LICENSE "{{license}}"
!define INSTALLERICON "{{installer_icon}}"
!define SIDEBARIMAGE "{{sidebar_image}}"
!define HEADERIMAGE "{{header_image}}"
!define UNINSTALLERICON "{{uninstaller_icon}}"
!define UNINSTALLERHEADERIMAGE "{{uninstaller_header_image}}"
!define MAINBINARYNAME "{{main_binary_name}}"
!define MAINBINARYSRCPATH "{{main_binary_path}}"
!define BUNDLEID "{{bundle_id}}"
!define COPYRIGHT "{{copyright}}"
!define OUTFILE "{{out_file}}"
!define ARCH "{{arch}}"
!define ADDITIONALPLUGINSPATH "{{additional_plugins_path}}"
!define ALLOWDOWNGRADES "{{allow_downgrades}}"
!define DISPLAYLANGUAGESELECTOR "{{display_language_selector}}"
!define INSTALLWEBVIEW2MODE "{{install_webview2_mode}}"
!define WEBVIEW2INSTALLERARGS "{{webview2_installer_args}}"
!define WEBVIEW2BOOTSTRAPPERPATH "{{webview2_bootstrapper_path}}"
!define WEBVIEW2INSTALLERPATH "{{webview2_installer_path}}"
!define MINIMUMWEBVIEW2VERSION "{{minimum_webview2_version}}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"
!define MANUKEY "Software\${MANUFACTURER}"
!define MANUPRODUCTKEY "${MANUKEY}\${PRODUCTNAME}"
!define UNINSTALLERSIGNCOMMAND "{{uninstaller_sign_cmd}}"
!define ESTIMATEDSIZE "{{estimated_size}}"
!define STARTMENUFOLDER "{{start_menu_folder}}"

Var PassiveMode
Var UpdateMode
Var NoShortcutMode
Var WixMode
Var OldMainBinaryName
; SHINSEKAI MSI->NSIS COMPAT BEGIN
; An existing NSIS location is authoritative, and `/D` is respected for normal
; NSIS installs. Explicit targets are rejected only during an MSI transition.
; A matching MSI path is retained solely as an untrusted app-root recovery hint
; and must never replace the current-user NSIS install directory.
Var LegacyMsiCandidate
Var LegacyMsiCandidateValid
Var LegacyMsiProductCode
Var LegacyMsiProductCodeValid
Var LegacyMsiRebootRequired
Var HasAuthoritativeNsisInstallDir
Var HasExplicitNsisInstallDir
Var LegacyMigrationDefaultInstallDir
!define LEGACY_MIGRATION_KEY "Software\${BUNDLEID}\Migration"
; SHINSEKAI MSI->NSIS COMPAT END

Name "${PRODUCTNAME}"
BrandingText "${COPYRIGHT}"
OutFile "${OUTFILE}"

; We don't actually use this value as default install path,
; it's just for nsis to append the product name folder in the directory selector
; https://nsis.sourceforge.io/Reference/InstallDir
!define PLACEHOLDER_INSTALL_DIR "placeholder\${PRODUCTNAME}"
InstallDir "${PLACEHOLDER_INSTALL_DIR}"

VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

# additional plugins
!addplugindir "${ADDITIONALPLUGINSPATH}"

; Uninstaller signing command
!if "${UNINSTALLERSIGNCOMMAND}" != ""
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

; Handle install mode, `perUser`, `perMachine` or `both`
!if "${INSTALLMODE}" == "perMachine"
  RequestExecutionLevel admin
!endif

!if "${INSTALLMODE}" == "currentUser"
  RequestExecutionLevel user
!endif

!if "${INSTALLMODE}" == "both"
  !define MULTIUSER_MUI
  !define MULTIUSER_INSTALLMODE_INSTDIR "${PRODUCTNAME}"
  !define MULTIUSER_INSTALLMODE_COMMANDLINE
  !if "${ARCH}" == "x64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !else if "${ARCH}" == "arm64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !endif
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${UNINSTKEY}"
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"
  !define MULTIUSER_INSTALLMODEPAGE_SHOWUSERNAME
  !define MULTIUSER_INSTALLMODE_FUNCTION RestorePreviousInstallLocation
  !define MULTIUSER_EXECUTIONLEVEL Highest
  !include MultiUser.nsh
!endif

; Installer icon
!if "${INSTALLERICON}" != ""
  !define MUI_ICON "${INSTALLERICON}"
!endif

; Installer sidebar image
!if "${SIDEBARIMAGE}" != ""
  !define MUI_WELCOMEFINISHPAGE_BITMAP "${SIDEBARIMAGE}"
!endif

; Enable header images for installer and uninstaller pages when either image is configured.
!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!else if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!endif

; Installer header image
!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_BITMAP "${HEADERIMAGE}"
!endif

; Uninstaller header image
!if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_UNBITMAP "${UNINSTALLERHEADERIMAGE}"
!endif

; Uninstaller icon
!if "${UNINSTALLERICON}" != ""
  !define MUI_UNICON "${UNINSTALLERICON}"
!endif

; Define registry key to store installer language
!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${MANUPRODUCTKEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"

; Installer pages, must be ordered as they appear
; 1. Welcome Page
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_WELCOME

; 2. License Page (if defined)
!if "${LICENSE}" != ""
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MUI_PAGE_LICENSE "${LICENSE}"
!endif

; 3. Install mode (if it is set to `both`)
!if "${INSTALLMODE}" == "both"
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MULTIUSER_PAGE_INSTALLMODE
!endif

; 4. Custom page to ask user if he wants to reinstall/uninstall
;    only if a previous installation was detected
Var ReinstallPageCheck
Page custom PageReinstall PageLeaveReinstall
Function PageReinstall
  ; SHINSEKAI MSI->NSIS COMPAT BEGIN
  ; Tauri NSIS's existing unnamed install-location value is authoritative. Do
  ; not enumerate stale MSI entries in that case: the normal NSIS maintenance
  ; flow below owns the update decision. MSI transitions reject explicit `/D`
  ; targets before uninstalling; the current-user NSIS must first migrate to
  ; LocalAppData so reboot-time MSI deletion cannot target replacement files.
  ${If} $HasAuthoritativeNsisInstallDir = 1
    Goto wix_loop_done
  ${EndIf}
  ; SHINSEKAI MSI->NSIS COMPAT END
  ; Uninstall previous WiX installation if exists.
  ;
  ; A WiX installer stores the installation info in registry
  ; using a UUID and so we have to loop through all keys under
  ; `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`
  ; and check if `DisplayName` and `Publisher` keys match ${PRODUCTNAME} and ${MANUFACTURER}
  ;
  ; This has a potential issue that there maybe another installation that matches
  ; our ${PRODUCTNAME} and ${MANUFACTURER} but wasn't installed by our WiX installer,
  ; however, this should be fine since the user will have to confirm the uninstallation
  ; and they can chose to abort it if doesn't make sense.
  StrCpy $0 0
  wix_loop:
    EnumRegKey $1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" $0
    StrCmp $1 "" wix_loop_done ; Exit loop if there is no more keys to loop on
    IntOp $0 $0 + 1
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "DisplayName"
    ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "Publisher"
    ; SHINSEKAI MSI->NSIS COMPAT BEGIN
    ; Historical v2.0/v2.1 MSI assets used the publisher derived from the
    ; bundle identifier (`shinsekai`). Keep that identity alongside an
    ; explicitly configured current publisher and require a real MSI ARP entry.
    StrCmp "$R0" "${PRODUCTNAME}" 0 wix_loop
    StrCmp "$R1" "${MANUFACTURER}" wix_publisher_match
    StrCmp "$R1" "shinsekai" wix_publisher_match wix_loop
    wix_publisher_match:
    ReadRegDWORD $R2 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "WindowsInstaller"
    StrCmp $R2 1 wix_identity_match wix_loop
    wix_identity_match:
    Goto wix_upstream_identity_matched
    ; SHINSEKAI MSI->NSIS COMPAT END
    StrCmp "$R0$R1" "${PRODUCTNAME}${MANUFACTURER}" 0 wix_loop
    ; SHINSEKAI MSI->NSIS COMPAT BEGIN
    wix_upstream_identity_matched:
    ; SHINSEKAI MSI->NSIS COMPAT END
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "UninstallString"
    ${StrCase} $R1 $R0 "L"
    ${StrLoc} $R0 $R1 "msiexec" ">"
    StrCmp $R0 0 0 wix_loop_done
    StrCpy $WixMode 1
    StrCpy $R6 "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1"
    ; SHINSEKAI MSI->NSIS COMPAT BEGIN
    ; Capture the old application root before msiexec removes its ARP/HKCU
    ; values. Rust treats this as an untrusted project-root candidate requiring
    ; strong project-data markers and explicit user confirmation. Missing or
    ; data-free app roots are ignored. `$INSTDIR` remains the LocalAppData NSIS
    ; destination during an MSI transition.
    StrCpy $LegacyMsiProductCode "$1"
    Call ValidateLegacyMsiProductCode
    ${If} $LegacyMsiProductCodeValid != 1
      Call AbortLegacyMsiMigration
    ${EndIf}
    ${If} $HasExplicitNsisInstallDir = 1
      Call AbortExplicitLegacyMsiTarget
    ${EndIf}
    Call PersistLegacyMsiAppRootHint
    ; SHINSEKAI MSI->NSIS COMPAT END
    Goto compare_version
  wix_loop_done:

  ; Check if there is an existing installation, if not, abort the reinstall page
  ReadRegStr $R0 SHCTX "${UNINSTKEY}" ""
  ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
  ${IfThen} "$R0$R1" == "" ${|} Abort ${|}

  ; Compare this installar version with the existing installation
  ; and modify the messages presented to the user accordingly
  compare_version:
  StrCpy $R4 "$(older)"
  ${If} $WixMode = 1
    ReadRegStr $R0 HKLM "$R6" "DisplayVersion"
  ${Else}
    ReadRegStr $R0 SHCTX "${UNINSTKEY}" "DisplayVersion"
  ${EndIf}
  ${IfThen} $R0 == "" ${|} StrCpy $R4 "$(unknown)" ${|}

  nsis_tauri_utils::SemverCompare "${VERSION}" $R0
  Pop $R0
  ; Reinstalling the same version
  ${If} $R0 = 0
    StrCpy $R1 "$(alreadyInstalledLong)"
    StrCpy $R2 "$(addOrReinstall)"
    StrCpy $R3 "$(uninstallApp)"
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(chooseMaintenanceOption)"
  ; Upgrading
  ${ElseIf} $R0 = 1
    StrCpy $R1 "$(olderOrUnknownVersionInstalled)"
    StrCpy $R2 "$(uninstallBeforeInstalling)"
    StrCpy $R3 "$(dontUninstall)"
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(choowHowToInstall)"
  ; Downgrading
  ${ElseIf} $R0 = -1
    StrCpy $R1 "$(newerVersionInstalled)"
    StrCpy $R2 "$(uninstallBeforeInstalling)"
    !if "${ALLOWDOWNGRADES}" == "true"
      StrCpy $R3 "$(dontUninstall)"
    !else
      StrCpy $R3 "$(dontUninstallDowngrade)"
    !endif
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(choowHowToInstall)"
  ${Else}
    Abort
  ${EndIf}

  ; Skip showing the page if passive
  ;
  ; Note that we don't call this earlier at the begining
  ; of this function because we need to populate some variables
  ; related to current installed version if detected and whether
  ; we are downgrading or not.
  ${If} $PassiveMode = 1
    Call PageLeaveReinstall
  ${Else}
    nsDialogs::Create 1018
    Pop $R4
    ${IfThen} $(^RTL) = 1 ${|} nsDialogs::SetRTL $(^RTL) ${|}

    ${NSD_CreateLabel} 0 0 100% 24u $R1
    Pop $R1

    ${NSD_CreateRadioButton} 30u 50u -30u 8u $R2
    Pop $R2
    ${NSD_OnClick} $R2 PageReinstallUpdateSelection

    ${NSD_CreateRadioButton} 30u 70u -30u 8u $R3
    Pop $R3
    ; Disable this radio button if downgrading and downgrades are disabled
    !if "${ALLOWDOWNGRADES}" == "false"
      ${IfThen} $R0 = -1 ${|} EnableWindow $R3 0 ${|}
    !endif
    ${NSD_OnClick} $R3 PageReinstallUpdateSelection

    ; Check the first radio button if this the first time
    ; we enter this page or if the second button wasn't
    ; selected the last time we were on this page
    ${If} $ReinstallPageCheck <> 2
      SendMessage $R2 ${BM_SETCHECK} ${BST_CHECKED} 0
    ${Else}
      SendMessage $R3 ${BM_SETCHECK} ${BST_CHECKED} 0
    ${EndIf}

    ${NSD_SetFocus} $R2
    nsDialogs::Show
  ${EndIf}
FunctionEnd
Function PageReinstallUpdateSelection
  ${NSD_GetState} $R2 $R1
  ${If} $R1 == ${BST_CHECKED}
    StrCpy $ReinstallPageCheck 1
  ${Else}
    StrCpy $ReinstallPageCheck 2
  ${EndIf}
FunctionEnd
Function PageLeaveReinstall
  ${NSD_GetState} $R2 $R1

  ; If migrating from Wix, always uninstall
  ${If} $WixMode = 1
    Goto reinst_uninstall
  ${EndIf}

  ; In update mode, always proceeds without uninstalling
  ${If} $UpdateMode = 1
    Goto reinst_done
  ${EndIf}

  ; $R0 holds whether same(0)/upgrading(1)/downgrading(-1) version
  ; $R1 holds the radio buttons state:
  ;   1 => first choice was selected
  ;   0 => second choice was selected
  ${If} $R0 = 0 ; Same version, proceed
    ${If} $R1 = 1              ; User chose to add/reinstall
      Goto reinst_done
    ${Else}                    ; User chose to uninstall
      Goto reinst_uninstall
    ${EndIf}
  ${ElseIf} $R0 = 1 ; Upgrading
    ${If} $R1 = 1              ; User chose to uninstall
      Goto reinst_uninstall
    ${Else}
      Goto reinst_done         ; User chose NOT to uninstall
    ${EndIf}
  ${ElseIf} $R0 = -1 ; Downgrading
    ${If} $R1 = 1              ; User chose to uninstall
      Goto reinst_uninstall
    ${Else}
      Goto reinst_done         ; User chose NOT to uninstall
    ${EndIf}
  ${EndIf}

  reinst_uninstall:
    HideWindow
    ClearErrors

    ${If} $WixMode = 1
      ; SHINSEKAI MSI->NSIS COMPAT BEGIN
      StrCpy $LegacyMsiRebootRequired 0
      ; Never execute an arbitrary ARP command. The matched ARP key is a
      ; validated MSI product code, so invoke the system Windows Installer
      ; directly. `/P` updater runs use passive UI and let msiexec request the
      ; elevation required by the historical per-machine package.
      Goto shinsekai_wix_uninstall
      ; SHINSEKAI MSI->NSIS COMPAT END
      ReadRegStr $R1 HKLM "$R6" "UninstallString"
      ExecWait '$R1' $0
      ; SHINSEKAI MSI->NSIS COMPAT BEGIN
      Goto shinsekai_wix_uninstall_done
      shinsekai_wix_uninstall:
        ${If} $PassiveMode = 1
          ExecWait '"$SYSDIR\msiexec.exe" /X$LegacyMsiProductCode /passive /norestart' $0
        ${Else}
          ExecWait '"$SYSDIR\msiexec.exe" /X$LegacyMsiProductCode /norestart' $0
        ${EndIf}
      shinsekai_wix_uninstall_done:
      ; SHINSEKAI MSI->NSIS COMPAT END
    ${Else}
      ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
      ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
      ${IfThen} $UpdateMode = 1 ${|} StrCpy $R1 "$R1 /UPDATE" ${|} ; append /UPDATE
      ${IfThen} $PassiveMode = 1 ${|} StrCpy $R1 "$R1 /P" ${|} ; append /P
      StrCpy $R1 "$R1 _?=$4" ; append uninstall directory
      ExecWait '$R1' $0
    ${EndIf}

    BringToFront

    ${IfThen} ${Errors} ${|} StrCpy $0 2 ${|} ; ExecWait failed, set fake exit code

    ; SHINSEKAI MSI->NSIS COMPAT BEGIN
    ${If} $WixMode = 1
      ; Windows Installer 3010 means success with a reboot required.
      ${If} $0 = 3010
        SetRebootFlag true
        StrCpy $LegacyMsiRebootRequired 1
        StrCpy $0 0
      ${EndIf}

      ; Exit code alone is insufficient: verify that the exact matched product
      ; is no longer registered with Windows Installer and that its installed
      ; executable was removed or scheduled for reboot-time deletion.
      ${If} $0 = 0
        ClearErrors
        System::Call 'msi::MsiQueryProductStateW(w "$LegacyMsiProductCode") i .r1'
        ${If} ${Errors}
          StrCpy $0 2
        ${ElseIf} $1 != -1
          StrCpy $0 2
        ${EndIf}
        ReadRegStr $R1 HKLM "$R6" "DisplayName"
        ${If} $R1 != ""
          StrCpy $0 2
        ${EndIf}

        ; Exit 3010 may leave a locked executable pending deletion at reboot.
        ; Product-state and exact ARP removal still prove the MSI is gone, and
        ; the current-user NSIS installs into a different LocalAppData path.
        ${If} $LegacyMsiRebootRequired != 1
        ${AndIf} ${FileExists} "$LegacyMsiCandidate\${MAINBINARYNAME}.exe"
          StrCpy $0 2
        ${EndIf}
      ${EndIf}

      ; `Abort` is a page-navigation primitive and is not a reliable process
      ; stop when PageLeaveReinstall is called directly by passive mode.
      ${If} $PassiveMode = 1
      ${AndIf} $0 != 0
        System::Call 'kernel32::AttachConsole(i -1) i .r1'
        ${If} $1 <> 0
          System::Call 'kernel32::GetStdHandle(i -12) p .r1'
          FileWrite $1 "Shinsekai: the previous MSI could not be removed; migration stopped before installing the current-user NSIS.$\r$\n"
        ${EndIf}
        SetErrorLevel $0
        Quit
      ${EndIf}

      ; The upstream check below inspects `$INSTDIR`, which is correct for an
      ; NSIS-to-NSIS update but no longer related to the removed MSI. A stale or
      ; explicitly targeted NSIS executable must not turn a successful MSI
      ; removal into a false failure.
      ${If} $0 = 0
        Goto reinst_done
      ${EndIf}
    ${EndIf}
    ; SHINSEKAI MSI->NSIS COMPAT END
    ${If} $0 <> 0
    ${OrIf} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
      ; User cancelled wix uninstaller? return to select un/reinstall page
      ${If} $WixMode = 1
      ${AndIf} $0 = 1602
        Abort
      ${EndIf}

      ; User cancelled NSIS uninstaller? return to select un/reinstall page
      ${If} $0 = 1
        Abort
      ${EndIf}

      ; Other erros? show generic error message and return to select un/reinstall page
      MessageBox MB_ICONEXCLAMATION "$(unableToUninstall)"
      Abort
    ${EndIf}
  reinst_done:
FunctionEnd

; 5. Choose install directory page
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_DIRECTORY

; 6. Start menu shortcut page
Var AppStartMenuFolder
!if "${STARTMENUFOLDER}" != ""
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !define MUI_STARTMENUPAGE_DEFAULTFOLDER "${STARTMENUFOLDER}"
!else
  !define MUI_PAGE_CUSTOMFUNCTION_PRE Skip
!endif
!insertmacro MUI_PAGE_STARTMENU Application $AppStartMenuFolder

; 7. Installation page
!insertmacro MUI_PAGE_INSTFILES

; 8. Finish page
;
; Don't auto jump to finish page after installation page,
; because the installation page has useful info that can be used debug any issues with the installer.
!define MUI_FINISHPAGE_NOAUTOCLOSE
; Use show readme button in the finish page as a button create a desktop shortcut
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "$(createDesktop)"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION CreateOrUpdateDesktopShortcut
; Show run app after installation.
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION RunMainBinary
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_FINISH

Function RunMainBinary
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
FunctionEnd

; Uninstaller Pages
; 1. Confirm uninstall page
Var DeleteAppDataCheckbox
Var DeleteAppDataCheckboxState
!define /ifndef WS_EX_LAYOUTRTL         0x00400000
!define MUI_PAGE_CUSTOMFUNCTION_SHOW un.ConfirmShow
Function un.ConfirmShow ; Add add a `Delete app data` check box
  ; $1 inner dialog HWND
  ; $2 window DPI
  ; $3 style
  ; $4 x
  ; $5 y
  ; $6 width
  ; $7 height
  FindWindow $1 "#32770" "" $HWNDPARENT ; Find inner dialog
  System::Call "user32::GetDpiForWindow(p r1) i .r2"
  ${If} $(^RTL) = 1
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE} | ${WS_EX_LAYOUTRTL}"
    IntOp $4 50 * $2
  ${Else}
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE}"
    IntOp $4 0 * $2
  ${EndIf}
  IntOp $5 100 * $2
  IntOp $6 400 * $2
  IntOp $7 25 * $2
  IntOp $4 $4 / 96
  IntOp $5 $5 / 96
  IntOp $6 $6 / 96
  IntOp $7 $7 / 96
  System::Call 'user32::CreateWindowEx(i r3, w "${__NSD_CheckBox_CLASS}", w "$(deleteAppData)", i ${__NSD_CheckBox_STYLE}, i r4, i r5, i r6, i r7, p r1, i0, i0, i0) i .s'
  Pop $DeleteAppDataCheckbox
  SendMessage $HWNDPARENT ${WM_GETFONT} 0 0 $1
  SendMessage $DeleteAppDataCheckbox ${WM_SETFONT} $1 1
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE un.ConfirmLeave
Function un.ConfirmLeave
  SendMessage $DeleteAppDataCheckbox ${BM_GETCHECK} 0 0 $DeleteAppDataCheckboxState
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_PRE un.SkipIfPassive
!insertmacro MUI_UNPAGE_CONFIRM

; 2. Uninstalling Page
!insertmacro MUI_UNPAGE_INSTFILES

;Languages
{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
!insertmacro MUI_RESERVEFILE_LANGDLL
{{#each language_files}}
  !include "{{this}}"
{{/each}}

Function .onInit
  ; SHINSEKAI MSI->NSIS COMPAT BEGIN
  StrCpy $LegacyMsiCandidate ""
  StrCpy $LegacyMsiCandidateValid 0
  StrCpy $LegacyMsiProductCode ""
  StrCpy $LegacyMsiProductCodeValid 0
  StrCpy $LegacyMsiRebootRequired 0
  StrCpy $HasAuthoritativeNsisInstallDir 0
  StrCpy $HasExplicitNsisInstallDir 0

  ; SHINSEKAI MSI->NSIS COMPAT END
  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/NS" $NoShortcutMode
  ${IfNot} ${Errors}
    StrCpy $NoShortcutMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}

  !if "${DISPLAYLANGUAGESELECTOR}" == "true"
    !insertmacro MUI_LANGDLL_DISPLAY
  !endif

  !insertmacro SetContext
  ; SHINSEKAI MSI->NSIS COMPAT BEGIN
  ${If} $INSTDIR != "${PLACEHOLDER_INSTALL_DIR}"
    StrCpy $HasExplicitNsisInstallDir 1
  ${EndIf}
  ; The unnamed value is authoritative only while the corresponding NSIS
  ; executable still exists. A stale registry value must not hide a real MSI.
  ReadRegStr $5 SHCTX "${MANUPRODUCTKEY}" ""
  ${If} $5 != ""
  ${AndIf} ${FileExists} "$5\${MAINBINARYNAME}.exe"
    StrCpy $HasAuthoritativeNsisInstallDir 1
  ${EndIf}
  ; SHINSEKAI MSI->NSIS COMPAT END

  ${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"
    ; Set default install location
    !if "${INSTALLMODE}" == "perMachine"
      ${If} ${RunningX64}
        !if "${ARCH}" == "x64"
          StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCTNAME}"
        !else if "${ARCH}" == "arm64"
          StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCTNAME}"
        !else
          StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
        !endif
      ${Else}
        StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
      ${EndIf}
    !else if "${INSTALLMODE}" == "currentUser"
      StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"
    !endif

    ; SHINSEKAI MSI->NSIS COMPAT BEGIN
    ; RestorePreviousInstallLocation uses $4 internally, so retain the platform
    ; default in a dedicated variable that the upstream helper cannot clobber.
    StrCpy $LegacyMigrationDefaultInstallDir "$INSTDIR"
    ; SHINSEKAI MSI->NSIS COMPAT END
    Call RestorePreviousInstallLocation
    ; SHINSEKAI MSI->NSIS COMPAT BEGIN
    ; The unnamed value is Tauri NSIS's own install-location contract and wins
    ; over every MSI source. If the value is stale, restore LocalAppData. A
    ; historical MSI root is deliberately never inherited as `$INSTDIR`.
    ${If} $HasAuthoritativeNsisInstallDir != 1
      StrCpy $INSTDIR "$LegacyMigrationDefaultInstallDir"
    ${EndIf}

    ; SHINSEKAI MSI->NSIS COMPAT END
  ${EndIf}


  !if "${INSTALLMODE}" == "both"
    !insertmacro MULTIUSER_INIT
  !endif
  ; SHINSEKAI MSI->NSIS COMPAT BEGIN
  ; NSIS does not execute custom-page callbacks under a true `/S` install, so
  ; PageReinstall cannot safely migrate/uninstall WiX in that mode. Fail closed
  ; when a matching MSI is present instead of silently creating a second root.
  ${If} ${Silent}
    Call AbortSilentLegacyWixMigration
  ${EndIf}
  ; SHINSEKAI MSI->NSIS COMPAT END
FunctionEnd


Section EarlyChecks
  ; Abort silent installer if downgrades is disabled
  !if "${ALLOWDOWNGRADES}" == "false"
  ${If} ${Silent}
    ; If downgrading
    ${If} $R0 = -1
      System::Call 'kernel32::AttachConsole(i -1)i.r0'
      ${If} $0 <> 0
        System::Call 'kernel32::GetStdHandle(i -11)i.r0'
        System::call 'kernel32::SetConsoleTextAttribute(i r0, i 0x0004)' ; set red color
        FileWrite $0 "$(silentDowngrades)"
      ${EndIf}
      Abort
    ${EndIf}
  ${EndIf}
  !endif

SectionEnd

Section WebView2
  ; Check if Webview2 is already installed and skip this section
  ${If} ${RunningX64}
    ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${Else}
    ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}

  ${If} $4 == ""
    ; Webview2 installation
    ;
    ; Skip if updating
    ${If} $UpdateMode <> 1
      !if "${INSTALLWEBVIEW2MODE}" == "downloadBootstrapper"
        Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        DetailPrint "$(webview2Downloading)"
        NSISdl::download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Pop $0
        ${If} $0 == "success"
          DetailPrint "$(webview2DownloadSuccess)"
        ${Else}
          DetailPrint "$(webview2DownloadError)"
          Abort "$(webview2AbortError)"
        ${EndIf}
        StrCpy $6 "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Goto install_webview2
      !endif

      !if "${INSTALLWEBVIEW2MODE}" == "embedBootstrapper"
        Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        File "/oname=$TEMP\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2BOOTSTRAPPERPATH}"
        DetailPrint "$(installingWebview2)"
        StrCpy $6 "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Goto install_webview2
      !endif

      !if "${INSTALLWEBVIEW2MODE}" == "offlineInstaller"
        Delete "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
        File "/oname=$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe" "${WEBVIEW2INSTALLERPATH}"
        DetailPrint "$(installingWebview2)"
        StrCpy $6 "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
        Goto install_webview2
      !endif

      Goto webview2_done

      install_webview2:
        DetailPrint "$(installingWebview2)"
        ; $6 holds the path to the webview2 installer
        ExecWait "$6 ${WEBVIEW2INSTALLERARGS} /install" $1
        ${If} $1 = 0
          DetailPrint "$(webview2InstallSuccess)"
        ${Else}
          DetailPrint "$(webview2InstallError)"
          Abort "$(webview2AbortError)"
        ${EndIf}
      webview2_done:
    ${EndIf}
  ${Else}
    !if "${MINIMUMWEBVIEW2VERSION}" != ""
      ${VersionCompare} "${MINIMUMWEBVIEW2VERSION}" "$4" $R0
      ${If} $R0 = 1
        update_webview:
          DetailPrint "$(installingWebview2)"
          ${If} ${RunningX64}
            ReadRegStr $R1 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate" "path"
          ${Else}
            ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\EdgeUpdate" "path"
          ${EndIf}
          ${If} $R1 == ""
            ReadRegStr $R1 HKCU "SOFTWARE\Microsoft\EdgeUpdate" "path"
          ${EndIf}
          ${If} $R1 != ""
            ; Chromium updater docs: https://source.chromium.org/chromium/chromium/src/+/main:docs/updater/user_manual.md
            ; Modified from "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Microsoft EdgeWebView\ModifyPath"
            ExecWait `"$R1" /install appguid=${WEBVIEW2APPGUID}&needsadmin=true` $1
            ${If} $1 = 0
              DetailPrint "$(webview2InstallSuccess)"
            ${Else}
              MessageBox MB_ICONEXCLAMATION|MB_ABORTRETRYIGNORE "$(webview2InstallError)" IDIGNORE ignore IDRETRY update_webview
              Quit
              ignore:
            ${EndIf}
          ${EndIf}
      ${EndIf}
    !endif
  ${EndIf}
SectionEnd

Section Install
  SetOutPath $INSTDIR

  !ifmacrodef NSIS_HOOK_PREINSTALL
    !insertmacro NSIS_HOOK_PREINSTALL
  !endif

  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; Copy main executable
  File "${MAINBINARYSRCPATH}"

  ; Copy resources
  {{#each resources_dirs}}
    CreateDirectory "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources}}
    File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
  {{/each}}

  ; Copy external binaries
  {{#each binaries}}
    File /a "/oname={{this}}" "{{no-escape @key}}"
  {{/each}}

  ; Create file associations
  {{#each file_associations as |association| ~}}
    {{#each association.ext as |ext| ~}}
       !insertmacro APP_ASSOCIATE "{{ext}}" "{{or association.name ext}}" "{{association-description association.description ext}}" "$INSTDIR\${MAINBINARYNAME}.exe,0" "Open with ${PRODUCTNAME}" "$INSTDIR\${MAINBINARYNAME}.exe $\"%1$\""
    {{/each}}
  {{/each}}

  ; Register deep links
  {{#each deep_link_protocols as |protocol| ~}}
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}" "URL Protocol" ""
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}" "" "URL:${BUNDLEID} protocol"
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}\DefaultIcon" "" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\",0"
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}\shell\open\command" "" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\""
  {{/each}}

  ; Create uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Save $INSTDIR in registry for future installations
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "" $INSTDIR

  !if "${INSTALLMODE}" == "both"
    ; Save install mode to be selected by default for the next installation such as updating
    ; or when uninstalling
    WriteRegStr SHCTX "${UNINSTKEY}" $MultiUser.InstallMode 1
  !endif

  ; Remove old main binary if it doesn't match new main binary name
  ReadRegStr $OldMainBinaryName SHCTX "${UNINSTKEY}" "MainBinaryName"
  ${If} $OldMainBinaryName != ""
  ${AndIf} $OldMainBinaryName != "${MAINBINARYNAME}.exe"
    Delete "$INSTDIR\$OldMainBinaryName"
  ${EndIf}

  ; Save current MAINBINARYNAME for future updates
  WriteRegStr SHCTX "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"

  ; Registry information for add/remove programs
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayIcon" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "${MANUFACTURER}"
  WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoModify" "1"
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoRepair" "1"

  ${GetSize} "$INSTDIR" "/M=uninstall.exe /S=0K /G=0" $0 $1 $2
  IntOp $0 $0 + ${ESTIMATEDSIZE}
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD SHCTX "${UNINSTKEY}" "EstimatedSize" "$0"

  !if "${HOMEPAGE}" != ""
    WriteRegStr SHCTX "${UNINSTKEY}" "URLInfoAbout" "${HOMEPAGE}"
    WriteRegStr SHCTX "${UNINSTKEY}" "URLUpdateInfo" "${HOMEPAGE}"
    WriteRegStr SHCTX "${UNINSTKEY}" "HelpLink" "${HOMEPAGE}"
  !endif

  ; Create start menu shortcut
  !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    Call CreateOrUpdateStartMenuShortcut
  !insertmacro MUI_STARTMENU_WRITE_END

  ; Create desktop shortcut for silent and passive installers
  ; because finish page will be skipped
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    Call CreateOrUpdateDesktopShortcut
  ${EndIf}

  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif

  ; Auto close this page for passive mode
  ${If} $PassiveMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

Function .onInstSuccess
  ; Check for `/R` flag only in silent and passive installers because
  ; GUI installer has a toggle for the user to (re)start the app
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    ${GetOptions} $CMDLINE "/R" $R0
    ${IfNot} ${Errors}
      ${GetOptions} $CMDLINE "/ARGS" $R0
      nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" "$R0"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function un.onInit
  !insertmacro SetContext

  !if "${INSTALLMODE}" == "both"
    !insertmacro MULTIUSER_UNINIT
  !endif

  !insertmacro MUI_UNGETLANGUAGE

  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}
FunctionEnd

Section Uninstall

  !ifmacrodef NSIS_HOOK_PREUNINSTALL
    !insertmacro NSIS_HOOK_PREUNINSTALL
  !endif

  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; Delete the app directory and its content from disk
  ; Copy main executable
  Delete "$INSTDIR\${MAINBINARYNAME}.exe"

  ; Delete resources
  {{#each resources}}
    Delete "$INSTDIR\\{{this.[1]}}"
  {{/each}}

  ; Delete external binaries
  {{#each binaries}}
    Delete "$INSTDIR\\{{this}}"
  {{/each}}

  ; Delete app associations
  {{#each file_associations as |association| ~}}
    {{#each association.ext as |ext| ~}}
      !insertmacro APP_UNASSOCIATE "{{ext}}" "{{or association.name ext}}"
    {{/each}}
  {{/each}}

  ; Delete deep links
  {{#each deep_link_protocols as |protocol| ~}}
    ReadRegStr $R7 SHCTX "Software\Classes\\{{protocol}}\shell\open\command" ""
    ${If} $R7 == "$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\""
      DeleteRegKey SHCTX "Software\Classes\\{{protocol}}"
    ${EndIf}
  {{/each}}


  ; Delete uninstaller
  Delete "$INSTDIR\uninstall.exe"

  {{#each resources_ancestors}}
  RMDir /REBOOTOK "$INSTDIR\\{{this}}"
  {{/each}}
  RMDir "$INSTDIR"

  ; Remove shortcuts if not updating
  ${If} $UpdateMode <> 1
    !insertmacro DeleteAppUserModelId

    ; Remove start menu shortcut
    !insertmacro MUI_STARTMENU_GETFOLDER Application $AppStartMenuFolder
    !insertmacro IsShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
      Delete "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
      RMDir "$SMPROGRAMS\$AppStartMenuFolder"
    ${EndIf}
    !insertmacro IsShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk"
      Delete "$SMPROGRAMS\${PRODUCTNAME}.lnk"
    ${EndIf}

    ; Remove desktop shortcuts
    !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$DESKTOP\${PRODUCTNAME}.lnk"
      Delete "$DESKTOP\${PRODUCTNAME}.lnk"
    ${EndIf}
  ${EndIf}

  ; Remove registry information for add/remove programs
  !if "${INSTALLMODE}" == "both"
    DeleteRegKey SHCTX "${UNINSTKEY}"
  !else if "${INSTALLMODE}" == "perMachine"
    DeleteRegKey HKLM "${UNINSTKEY}"
  !else
    DeleteRegKey HKCU "${UNINSTKEY}"
  !endif

  ; Removes the Autostart entry for ${PRODUCTNAME} from the HKCU Run key if it exists.
  ; This ensures the program does not launch automatically after uninstallation if it exists.
  ; If it doesn't exist, it does nothing.
  ; We do this when not updating (to preserve the registry value on updates)
  ${If} $UpdateMode <> 1
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${PRODUCTNAME}"
  ${EndIf}

  ; Delete app data if the checkbox is selected
  ; and if not updating
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    ; Clear the install location $INSTDIR from registry
    DeleteRegKey SHCTX "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty SHCTX "${MANUKEY}"

    ; Clear the install language from registry
    DeleteRegValue HKCU "${MANUPRODUCTKEY}" "Installer Language"
    DeleteRegKey /ifempty HKCU "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty HKCU "${MANUKEY}"
    ; SHINSEKAI MSI->NSIS COMPAT BEGIN
    ; An explicit delete-app-data uninstall also consumes the one-time legacy
    ; MSI app-root recovery hint.
    DeleteRegKey HKCU "${LEGACY_MIGRATION_KEY}"
    DeleteRegKey /ifempty HKCU "Software\${BUNDLEID}"
    ; SHINSEKAI MSI->NSIS COMPAT END

    SetShellVarContext current
    RmDir /r "$APPDATA\${BUNDLEID}"
    RmDir /r "$LOCALAPPDATA\${BUNDLEID}"
  ${EndIf}

  !ifmacrodef NSIS_HOOK_POSTUNINSTALL
    !insertmacro NSIS_HOOK_POSTUNINSTALL
  !endif

  ; Auto close if passive mode or updating
  ${If} $PassiveMode = 1
  ${OrIf} $UpdateMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd

; SHINSEKAI MSI->NSIS COMPAT BEGIN
; Validate the matched MSI product code before using it as a command argument.
; Only the canonical `{8-4-4-4-12}` hexadecimal representation is accepted.
Function ValidateLegacyMsiProductCode
  Push $0
  Push $1
  Push $2
  Push $3

  StrCpy $LegacyMsiProductCodeValid 0
  StrLen $0 "$LegacyMsiProductCode"
  ${If} $0 != 38
    Goto legacy_msi_product_code_done
  ${EndIf}

  StrCpy $1 0
  legacy_msi_product_code_loop:
    StrCpy $2 "$LegacyMsiProductCode" 1 $1
    ${If} $1 = 0
      StrCmp $2 "{" 0 legacy_msi_product_code_done
    ${ElseIf} $1 = 37
      StrCmp $2 "}" 0 legacy_msi_product_code_done
    ${ElseIf} $1 = 9
    ${OrIf} $1 = 14
    ${OrIf} $1 = 19
    ${OrIf} $1 = 24
      StrCmp $2 "-" 0 legacy_msi_product_code_done
    ${Else}
      ${StrLoc} $3 "0123456789abcdefABCDEF" "$2" ">"
      StrCmp $3 "" legacy_msi_product_code_done
    ${EndIf}
    IntOp $1 $1 + 1
    ${If} $1 < 38
      Goto legacy_msi_product_code_loop
    ${EndIf}

  StrCpy $LegacyMsiProductCodeValid 1

  legacy_msi_product_code_done:
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

; Validate an app-root hint without trusting registry content. This is an
; identity/readability check, not an installation-permission check: the old
; per-machine root is expected to be under protected Program Files and must
; never become the current-user NSIS `$INSTDIR`.
;
; Input/output: $LegacyMsiCandidate; result: $LegacyMsiCandidateValid (0/1).
Function ValidateLegacyMsiAppRoot
  Push $0
  Push $1
  Push $2
  Push $3

  StrCpy $LegacyMsiCandidateValid 0
  StrCpy $0 "$LegacyMsiCandidate"
  StrCmp $0 "" legacy_msi_app_root_done

  ; ARP values may have one matching pair of surrounding quotes.
  StrCpy $1 "$0" 1
  StrCmp $1 "$\"" 0 legacy_msi_app_root_unquoted
    StrLen $2 "$0"
    ${If} $2 <= 2
      Goto legacy_msi_app_root_done
    ${EndIf}
    IntOp $3 $2 - 1
    StrCpy $1 "$0" 1 $3
    StrCmp $1 "$\"" 0 legacy_msi_app_root_done
    IntOp $2 $2 - 2
    StrCpy $0 "$0" $2 1

  legacy_msi_app_root_unquoted:
  ; Require `X:\...` before canonicalizing. This rejects UNC, device paths and
  ; drive-relative values such as `X:folder`.
  StrCpy $1 "$0" 1 1
  StrCmp $1 ":" 0 legacy_msi_app_root_done
  StrCpy $1 "$0" 1 2
  StrCmp $1 "\" 0 legacy_msi_app_root_done
  StrCpy $1 "$0" 1
  StrCmp $1 "\" legacy_msi_app_root_done

  GetFullPathName $0 "$0"
  StrLen $1 "$0"
  ${If} $1 <= 3
    Goto legacy_msi_app_root_done
  ${EndIf}
  StrCpy $1 "$0" 3
  System::Call 'kernel32::GetDriveTypeW(w r1) i .r2'
  ${If} $2 = 0
  ${OrIf} $2 = 1
  ${OrIf} $2 = 4
  ${OrIf} $2 = 5
    Goto legacy_msi_app_root_done
  ${EndIf}

  IfFileExists "$0\." 0 legacy_msi_app_root_done
  IfFileExists "$0\${MAINBINARYNAME}.exe" 0 legacy_msi_app_root_done

  StrCpy $LegacyMsiCandidate "$0"
  StrCpy $LegacyMsiCandidateValid 1

  legacy_msi_app_root_done:
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

; Called only after DisplayName, Publisher, WindowsInstaller and msiexec checks
; identify a matching MSI. Exact ARP InstallLocation wins, followed by both
; real historical and compatibility HKCU product keys. Persisting before
; msiexec is mandatory because WiX removes its owned InstallDir value. This is
; an app-root candidate, not proof that project data exists there.
Function PersistLegacyMsiAppRootHint
  StrCpy $LegacyMsiCandidate ""
  ReadRegStr $LegacyMsiCandidate HKLM "$R6" "InstallLocation"
  Call ValidateLegacyMsiAppRoot
  ${If} $LegacyMsiCandidateValid = 1
    Goto legacy_msi_app_root_ready
  ${EndIf}

  ReadRegStr $LegacyMsiCandidate HKCU "Software\shinsekai\Shinsekai" "InstallDir"
  Call ValidateLegacyMsiAppRoot
  ${If} $LegacyMsiCandidateValid = 1
    Goto legacy_msi_app_root_ready
  ${EndIf}

  ReadRegStr $LegacyMsiCandidate HKCU "Software\Shinsekai Contributors\Shinsekai" "InstallDir"
  Call ValidateLegacyMsiAppRoot
  ${If} $LegacyMsiCandidateValid != 1
    Call AbortLegacyMsiMigration
  ${EndIf}

  legacy_msi_app_root_ready:
  ClearErrors
  WriteRegStr HKCU "${LEGACY_MIGRATION_KEY}" "LegacyMsiAppRoot" "$LegacyMsiCandidate"
  IfErrors 0 legacy_msi_app_root_persisted
    Call AbortLegacyMsiMigration
  legacy_msi_app_root_persisted:
FunctionEnd

; An explicit NSIS `/D` target could alias the old MSI path. If Windows
; Installer returns 3010, its reboot-time delete could then remove newly
; installed files, even across installer restarts. Require the safe LocalAppData
; transition first rather than trying to compare paths or junction aliases.
Function AbortExplicitLegacyMsiTarget
  ${If} $PassiveMode = 1
    System::Call 'kernel32::AttachConsole(i -1) i .r0'
    ${If} $0 <> 0
      System::Call 'kernel32::GetStdHandle(i -12) p .r0'
      FileWrite $0 "Shinsekai: MSI-to-NSIS migration cannot use an explicit /D target; rerun without /D.$\r$\n"
    ${EndIf}
  ${Else}
    MessageBox MB_OK|MB_ICONSTOP "MSI-to-NSIS migration cannot use an explicit installation target.$\r$\n$\r$\nNothing was uninstalled. Rerun this installer without /D so it can safely install in LocalAppData."
  ${EndIf}
  SetErrorLevel 3
  Quit
FunctionEnd

; Stop before PageLeaveReinstall invokes msiexec if identity validation or hint
; persistence failed. The old MSI remains untouched and no NSIS files install.
Function AbortLegacyMsiMigration
  ${If} $PassiveMode = 1
    System::Call 'kernel32::AttachConsole(i -1) i .r0'
    ${If} $0 <> 0
      System::Call 'kernel32::GetStdHandle(i -12) p .r0'
      FileWrite $0 "Shinsekai: the previous MSI install could not be validated or its app-root hint could not be saved; migration stopped before uninstalling it.$\r$\n"
    ${EndIf}
  ${Else}
    MessageBox MB_OK|MB_ICONSTOP "The previous Shinsekai MSI install could not be validated, or its app-root recovery hint could not be saved.$\r$\n$\r$\nNothing was uninstalled. Restore access to the old installation and try again."
  ${EndIf}
  SetErrorLevel 3
  Quit
FunctionEnd

; A true NSIS `/S` run skips PageReinstall entirely. Quietly invoking an
; arbitrary MSI UninstallString is not equivalent to Tauri's confirmed UI flow
; and may repair instead of uninstalling, so matching legacy MSI installs fail
; closed with a non-zero exit. Tauri updater installs use `/P` + `/UPDATE`, not
; `/S`, and continue through the normal migration page callback.
Function AbortSilentLegacyWixMigration
  Push $0
  Push $1
  Push $R0
  Push $R1

  ; An existing NSIS install is authoritative even if a stale MSI ARP entry
  ; remains. `/D=...` alone does not bypass this guard because a silent custom
  ; page cannot safely remove the matching MSI and would create a double install.
  ${If} $HasAuthoritativeNsisInstallDir = 1
    Goto silent_wix_done
  ${EndIf}

  StrCpy $0 0
  silent_wix_loop:
    EnumRegKey $1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" $0
    StrCmp $1 "" silent_wix_done
    IntOp $0 $0 + 1
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "DisplayName"
    ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "Publisher"
    StrCmp "$R0" "${PRODUCTNAME}" 0 silent_wix_loop
    StrCmp "$R1" "${MANUFACTURER}" silent_wix_publisher_match
    StrCmp "$R1" "shinsekai" silent_wix_publisher_match silent_wix_loop
    silent_wix_publisher_match:
    ReadRegDWORD $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "WindowsInstaller"
    StrCmp $R0 1 silent_wix_identity_match silent_wix_loop
    silent_wix_identity_match:
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "UninstallString"
    ${StrCase} $R1 $R0 "L"
    ${StrLoc} $R0 $R1 "msiexec" ">"
    StrCmp $R0 0 0 silent_wix_done

    System::Call 'kernel32::AttachConsole(i -1) i .r0'
    ${If} $0 <> 0
      System::Call 'kernel32::GetStdHandle(i -12) p .r0'
      FileWrite $0 "Shinsekai: MSI-to-NSIS migration cannot run with /S; rerun without /S.$\r$\n"
    ${EndIf}
    SetErrorLevel 3
    Quit

  silent_wix_done:
  Pop $R1
  Pop $R0
  Pop $1
  Pop $0
FunctionEnd
; SHINSEKAI MSI->NSIS COMPAT END
Function Skip
  Abort
FunctionEnd

Function SkipIfPassive
  ; SHINSEKAI MSI->NSIS COMPAT BEGIN
  ; Once a matching MSI is removed, keep the first NSIS install fixed to its
  ; preselected LocalAppData destination. Skipping the later directory/start
  ; menu/finish pages prevents an interactive user from selecting a pathname
  ; that Windows Installer may have scheduled for reboot-time deletion.
  ${IfThen} $WixMode = 1 ${|} Abort ${|}
  ; SHINSEKAI MSI->NSIS COMPAT END
  ${IfThen} $PassiveMode = 1  ${|} Abort ${|}
FunctionEnd
Function un.SkipIfPassive
  ${IfThen} $PassiveMode = 1  ${|} Abort ${|}
FunctionEnd

Function CreateOrUpdateStartMenuShortcut
  ; We used to use product name as MAINBINARYNAME
  ; migrate old shortcuts to target the new MAINBINARYNAME
  StrCpy $R0 0

  !insertmacro IsShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    StrCpy $R0 1
  ${EndIf}

  !insertmacro IsShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    StrCpy $R0 1
  ${EndIf}

  ${If} $R0 = 1
    Return
  ${EndIf}

  ; Skip creating shortcut if in update mode or no shortcut mode
  ; but always create if migrating from wix
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Return
    ${EndIf}
  ${EndIf}

  !if "${STARTMENUFOLDER}" != ""
    CreateDirectory "$SMPROGRAMS\$AppStartMenuFolder"
    CreateShortcut "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    !insertmacro SetLnkAppUserModelId "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
  !else
    CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    !insertmacro SetLnkAppUserModelId "$SMPROGRAMS\${PRODUCTNAME}.lnk"
  !endif
FunctionEnd

Function CreateOrUpdateDesktopShortcut
  ; We used to use product name as MAINBINARYNAME
  ; migrate old shortcuts to target the new MAINBINARYNAME
  !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Return
  ${EndIf}

  ; Skip creating shortcut if in update mode or no shortcut mode
  ; but always create if migrating from wix
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Return
    ${EndIf}
  ${EndIf}

  CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  !insertmacro SetLnkAppUserModelId "$DESKTOP\${PRODUCTNAME}.lnk"
FunctionEnd
