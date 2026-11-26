use std::sync::{Arc, Mutex};

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};
use tauri_plugin_updater::{Update, UpdaterExt};

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

#[tauri::command]
pub(crate) async fn desktop_update_check(
    app: AppHandle,
    desktop_state: State<'_, DesktopState>,
    update_state: State<'_, DesktopUpdateState>,
) -> Result<Option<DesktopUpdate>, String> {
    restart_debug_log("desktop_update_check command received");
    if desktop_state.is_portable() {
        restart_debug_log("desktop_update_check skipped for portable build");
        return Ok(None);
    }
    let update = app
        .updater()
        .map_err(desktop_update_error)?
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
    if desktop_state.is_portable() {
        restart_debug_log("desktop_update_install blocked for portable build");
        return Err("Desktop auto-update is disabled for portable builds.".to_string());
    }
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

    update
        .download_and_install(
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

    restart_debug_log("desktop_update_install completed; restarting app");
    app.restart()
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
