#[cfg(any(target_os = "macos", test))]
use std::{fs, path::PathBuf};
use std::{
    ffi::OsString,
    path::Path,
    sync::{Arc, Mutex},
};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::{Update, Updater, UpdaterExt};

use crate::state::{restart_debug_log, DesktopState};

const UPDATE_PROGRESS_EVENT: &str = "shinsekai:update-progress";

pub(crate) struct DesktopUpdateState {
    pending: Mutex<Option<Update>>,
}

impl DesktopUpdateState {
    pub(crate) fn new() -> Self {
        Self {
            pending: Mutex::new(None),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopUpdate {
    version: String,
    date: Option<String>,
    body: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopUpdateProgress {
    event: &'static str,
    downloaded: u64,
    content_length: Option<u64>,
}

#[derive(Default)]
struct DesktopUpdateDownloadProgress {
    downloaded: u64,
    content_length: Option<u64>,
}

#[cfg(any(target_os = "macos", test))]
#[derive(Debug)]
struct PortableSitePackagesBackup {
    python_version_dir: String,
    original_path: PathBuf,
    backup_dir: PathBuf,
}

#[tauri::command]
pub(crate) async fn desktop_update_check(
    app: AppHandle,
    desktop_state: State<'_, DesktopState>,
    update_state: State<'_, DesktopUpdateState>,
) -> Result<Option<DesktopUpdate>, String> {
    restart_debug_log("desktop_update_check command received");
    let update = build_updater(&app, &desktop_state)?
        .check()
        .await
        .map_err(desktop_update_error)?;
    let view = update.as_ref().map(desktop_update_view);
    let mut pending = update_state
        .pending
        .lock()
        .map_err(|_| "desktop update state lock is poisoned".to_string())?;
    *pending = update;
    restart_debug_log(format!(
        "desktop_update_check result={}",
        if view.is_some() { "available" } else { "none" }
    ));
    Ok(view)
}

#[tauri::command]
pub(crate) async fn desktop_update_install(
    app: AppHandle,
    desktop_state: State<'_, DesktopState>,
    update_state: State<'_, DesktopUpdateState>,
) -> Result<(), String> {
    restart_debug_log("desktop_update_install command received");
    let update = update_state
        .pending
        .lock()
        .map_err(|_| "desktop update state lock is poisoned".to_string())?
        .take()
        .ok_or_else(|| "there is no pending desktop update".to_string())?;

    emit_update_progress(
        &app,
        DesktopUpdateProgress {
            event: "started",
            downloaded: 0,
            content_length: None,
        },
    );

    let progress = Arc::new(Mutex::new(DesktopUpdateDownloadProgress::default()));
    let chunk_progress = Arc::clone(&progress);
    let chunk_app = app.clone();
    let finish_progress = Arc::clone(&progress);
    let finish_app = app.clone();

    let bytes = update
        .download(
            move |chunk_length, content_length| {
                let payload = {
                    let mut progress = match chunk_progress.lock() {
                        Ok(progress) => progress,
                        Err(_) => return,
                    };
                    progress.downloaded = progress.downloaded.saturating_add(chunk_length as u64);
                    if content_length.is_some() {
                        progress.content_length = content_length;
                    }
                    DesktopUpdateProgress {
                        event: "progress",
                        downloaded: progress.downloaded,
                        content_length: progress.content_length,
                    }
                };
                emit_update_progress(&chunk_app, payload);
            },
            move || {
                let payload = {
                    let progress = match finish_progress.lock() {
                        Ok(progress) => progress,
                        Err(_) => return,
                    };
                    DesktopUpdateProgress {
                        event: "finished",
                        downloaded: progress.downloaded,
                        content_length: progress.content_length,
                    }
                };
                emit_update_progress(&finish_app, payload);
            },
        )
        .await
        .map_err(desktop_update_error)?;

    install_downloaded_update(update, &bytes, &desktop_state)?;

    restart_debug_log("desktop_update_install completed; restarting app");
    app.restart()
}

fn build_updater(app: &AppHandle, _desktop_state: &DesktopState) -> Result<Updater, String> {
    let stop_app = app.clone();
    let mut builder = app.updater_builder().on_before_exit(move || {
        if let Some(state) = stop_app.try_state::<DesktopState>() {
            if let Some(bridge) = state.take_bridge() {
                restart_debug_log("updater on_before_exit stopping bridge");
                bridge.stop();
            }
        }
    });
    #[cfg(windows)]
    if _desktop_state.is_portable() {
        let args = portable_nsis_installer_args(&_desktop_state.app_root);
        restart_debug_log(format!(
            "updater configured for windows portable build target={}",
            crate::runtime::display_path(&_desktop_state.app_root)
        ));
        builder = builder.installer_args(args);
    }
    builder.build().map_err(desktop_update_error)
}

#[cfg(target_os = "macos")]
fn install_downloaded_update(
    update: Update,
    bytes: &[u8],
    desktop_state: &DesktopState,
) -> Result<(), String> {
    if let Some(bridge) = desktop_state.take_bridge() {
        restart_debug_log("desktop_update_install stopping bridge before macOS install");
        bridge.stop();
    }
    let runtime_root = desktop_state.source_root.join("runtime");
    let backup = desktop_state
        .is_portable()
        .then(|| backup_portable_site_packages(&runtime_root, &desktop_state.app_root))
        .flatten();
    match update.install(bytes) {
        Ok(()) => {
            if let Some(backup) = backup {
                merge_portable_site_packages(backup, &runtime_root);
            }
            Ok(())
        }
        Err(error) => {
            if let Some(backup) = backup {
                restore_portable_site_packages(backup);
            }
            Err(desktop_update_error(error))
        }
    }
}

#[cfg(not(target_os = "macos"))]
fn install_downloaded_update(
    update: Update,
    bytes: &[u8],
    _desktop_state: &DesktopState,
) -> Result<(), String> {
    #[cfg(not(windows))]
    if let Some(bridge) = _desktop_state.take_bridge() {
        restart_debug_log("desktop_update_install stopping bridge before install");
        bridge.stop();
    }
    update.install(bytes).map_err(desktop_update_error)
}

#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn portable_nsis_installer_args(app_root: &Path) -> Vec<OsString> {
    let display = crate::runtime::display_path(app_root);
    let target = trim_trailing_dir_separator(&display);
    vec![
        OsString::from("/PORTABLE"),
        OsString::from("/NS"),
        OsString::from(format!("/D={target}")),
    ]
}

#[cfg_attr(not(windows), allow(dead_code))]
fn trim_trailing_dir_separator(path: &str) -> &str {
    let bytes = path.as_bytes();
    let is_windows_drive_root = bytes.len() == 3
        && bytes[0].is_ascii_alphabetic()
        && bytes[1] == b':'
        && matches!(bytes[2], b'\\' | b'/');
    if is_windows_drive_root || path == "/" {
        return path;
    }
    path.trim_end_matches(['\\', '/'])
}

#[cfg(any(target_os = "macos", test))]
fn find_unix_site_packages(runtime_root: &Path) -> Option<(String, PathBuf)> {
    let lib_dir = runtime_root.join("lib");
    let mut entries: Vec<_> = fs::read_dir(&lib_dir).ok()?.flatten().collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let file_name = entry.file_name();
        let Some(name) = file_name.to_str() else {
            continue;
        };
        if !name.starts_with("python") {
            continue;
        }
        let site_packages = entry.path().join("site-packages");
        if site_packages.is_dir() {
            return Some((name.to_string(), site_packages));
        }
    }
    None
}

#[cfg(any(target_os = "macos", test))]
fn backup_portable_site_packages(
    runtime_root: &Path,
    app_root: &Path,
) -> Option<PortableSitePackagesBackup> {
    let (python_version_dir, original_path) = find_unix_site_packages(runtime_root)?;
    let backup_dir = app_root.join(format!(
        ".shinsekai-portable-site-packages-backup-{}",
        std::process::id()
    ));
    if backup_dir.exists() {
        let _ = fs::remove_dir_all(&backup_dir);
    }
    match fs::rename(&original_path, &backup_dir) {
        Ok(()) => {
            restart_debug_log(format!(
                "portable update backed up site-packages python={} backup={}",
                python_version_dir,
                backup_dir.display()
            ));
            Some(PortableSitePackagesBackup {
                python_version_dir,
                original_path,
                backup_dir,
            })
        }
        Err(error) => {
            restart_debug_log(format!(
                "portable update site-packages backup skipped error={error}"
            ));
            None
        }
    }
}

#[cfg(any(target_os = "macos", test))]
fn restore_portable_site_packages(backup: PortableSitePackagesBackup) {
    if !backup.original_path.exists() && backup.backup_dir.exists() {
        if let Err(error) = fs::rename(&backup.backup_dir, &backup.original_path) {
            restart_debug_log(format!(
                "portable update site-packages restore failed error={error}"
            ));
        }
    }
}

#[cfg(any(target_os = "macos", test))]
fn merge_portable_site_packages(backup: PortableSitePackagesBackup, new_runtime_root: &Path) {
    if let Some((new_python_dir, new_site_packages)) = find_unix_site_packages(new_runtime_root) {
        if new_python_dir == backup.python_version_dir {
            if let Ok(entries) = fs::read_dir(&backup.backup_dir) {
                for entry in entries.flatten() {
                    let src = entry.path();
                    let dest = new_site_packages.join(entry.file_name());
                    if dest.symlink_metadata().is_err() {
                        if let Err(error) = fs::rename(&src, &dest) {
                            restart_debug_log(format!(
                                "portable update merge entry skipped name={} error={error}",
                                entry.file_name().to_string_lossy()
                            ));
                        }
                    }
                }
            }
        } else {
            restart_debug_log(format!(
                "portable update skipped site-packages merge on python version change old={} new={}",
                backup.python_version_dir, new_python_dir
            ));
        }
    }
    let _ = fs::remove_dir_all(&backup.backup_dir);
}

fn desktop_update_view(update: &Update) -> DesktopUpdate {
    DesktopUpdate {
        version: update.version.clone(),
        date: update.date.map(|date| date.to_string()),
        body: update.body.clone(),
    }
}

fn emit_update_progress(app: &AppHandle, payload: DesktopUpdateProgress) {
    let _ = app.emit(UPDATE_PROGRESS_EVENT, payload);
}

fn desktop_update_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn portable_nsis_installer_args_place_unquoted_dir_last() {
        let args = portable_nsis_installer_args(Path::new(
            r"\\?\E:\Shinsekai Portable\bundle\",
        ));
        assert_eq!(
            args,
            vec![
                OsString::from("/PORTABLE"),
                OsString::from("/NS"),
                OsString::from(r"/D=E:\Shinsekai Portable\bundle"),
            ]
        );

        let drive_args = portable_nsis_installer_args(Path::new(r"\\?\E:\"));
        assert_eq!(drive_args.last().unwrap(), &OsString::from(r"/D=E:\"));
    }

    #[test]
    fn macos_portable_site_packages_backup_and_merge_preserves_custom_packages() {
        let temp_root = unique_temp_dir("updater-macos-merge");
        let runtime_root = temp_root.join("Shinsekai.app/Contents/Resources/runtime");
        let old_sp = runtime_root.join("lib/python3.11/site-packages");
        fs::create_dir_all(old_sp.join("user_plugin_pkg")).unwrap();
        fs::create_dir_all(old_sp.join("pydantic")).unwrap();
        fs::write(old_sp.join("user_plugin_pkg/__init__.py"), "custom = 1\n").unwrap();
        fs::write(old_sp.join("pydantic/__init__.py"), "version = 'old'\n").unwrap();

        let backup = backup_portable_site_packages(&runtime_root, &temp_root).unwrap();
        assert!(!old_sp.exists());

        fs::remove_dir_all(&runtime_root).unwrap();
        let new_sp = runtime_root.join("lib/python3.11/site-packages");
        fs::create_dir_all(new_sp.join("pydantic")).unwrap();
        fs::write(new_sp.join("pydantic/__init__.py"), "version = 'new'\n").unwrap();

        merge_portable_site_packages(backup, &runtime_root);

        assert_eq!(
            fs::read_to_string(new_sp.join("user_plugin_pkg/__init__.py")).unwrap(),
            "custom = 1\n"
        );
        assert_eq!(
            fs::read_to_string(new_sp.join("pydantic/__init__.py")).unwrap(),
            "version = 'new'\n"
        );
        let remaining_backups: Vec<_> = fs::read_dir(&temp_root)
            .unwrap()
            .flatten()
            .filter(|e| {
                e.file_name()
                    .to_string_lossy()
                    .starts_with(".shinsekai-portable-site-packages-backup-")
            })
            .collect();
        assert!(remaining_backups.is_empty());

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn macos_portable_site_packages_restore_on_install_failure() {
        let temp_root = unique_temp_dir("updater-macos-restore");
        let runtime_root = temp_root.join("Shinsekai.app/Contents/Resources/runtime");
        let old_sp = runtime_root.join("lib/python3.11/site-packages");
        fs::create_dir_all(old_sp.join("custom_pkg")).unwrap();
        fs::write(old_sp.join("custom_pkg/mod.py"), "ok = True\n").unwrap();

        let backup = backup_portable_site_packages(&runtime_root, &temp_root).unwrap();
        assert!(!old_sp.exists());

        restore_portable_site_packages(backup);
        assert_eq!(
            fs::read_to_string(old_sp.join("custom_pkg/mod.py")).unwrap(),
            "ok = True\n"
        );

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn macos_portable_site_packages_skips_merge_when_python_version_changes() {
        let temp_root = unique_temp_dir("updater-macos-py-bump");
        let runtime_root = temp_root.join("Shinsekai.app/Contents/Resources/runtime");
        let old_sp = runtime_root.join("lib/python3.11/site-packages");
        fs::create_dir_all(old_sp.join("old_pkg")).unwrap();

        let backup = backup_portable_site_packages(&runtime_root, &temp_root).unwrap();
        fs::remove_dir_all(&runtime_root).unwrap();
        let new_sp = runtime_root.join("lib/python3.12/site-packages");
        fs::create_dir_all(&new_sp).unwrap();

        merge_portable_site_packages(backup, &runtime_root);

        assert!(!new_sp.join("old_pkg").exists());
        let _ = fs::remove_dir_all(temp_root);
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
    }
}
