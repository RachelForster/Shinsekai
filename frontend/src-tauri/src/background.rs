//! Native tray preferences and polling, independent of WebView visibility.
use std::{
    fs,
    io::Write,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    thread,
    time::Duration,
};

#[cfg(test)]
use chrono::NaiveDateTime;
use chrono::{NaiveDate, NaiveTime};
use serde::{Deserialize, Serialize};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, State, WebviewWindow,
};

use crate::{restart_debug_log, shutdown_desktop_app, DesktopState};

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(default, rename_all = "camelCase")]
pub struct BackgroundPreferences {
    close_to_tray: bool,
    remember_close_action: bool,
    minimize_to_tray: bool,
    bedtime_enabled: bool,
    bedtime_time: String,
    language: String,
}

impl Default for BackgroundPreferences {
    fn default() -> Self {
        Self {
            close_to_tray: false,
            remember_close_action: false,
            minimize_to_tray: false,
            bedtime_enabled: false,
            bedtime_time: "23:00".into(),
            language: "zh_CN".into(),
        }
    }
}

impl BackgroundPreferences {
    fn validate(&self) -> Result<(), String> {
        parse_bedtime(&self.bedtime_time)?;
        if !matches!(self.language.as_str(), "zh_CN" | "en" | "ja") {
            return Err("Unsupported reminder language".into());
        }
        Ok(())
    }
}

#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(default, rename_all = "camelCase")]
struct SavedBackground {
    preferences: BackgroundPreferences,
    last_delivered_date: Option<NaiveDate>,
}

pub struct BackgroundState {
    path: PathBuf,
    saved: Mutex<SavedBackground>,
    tray_available: AtomicBool,
    close_requested: AtomicBool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackgroundStatus {
    preferences: BackgroundPreferences,
    tray_available: bool,
}

impl BackgroundState {
    fn load(path: PathBuf) -> Self {
        let saved = match fs::read(&path) {
            Ok(bytes) => serde_json::from_slice::<SavedBackground>(&bytes)
                .map_err(|error| error.to_string())
                .and_then(|saved| {
                    saved.preferences.validate()?;
                    Ok(saved)
                }),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                Ok(SavedBackground::default())
            }
            Err(error) => Err(error.to_string()),
        }
        .unwrap_or_else(|error| {
            // Preserve the original file until the user explicitly saves new preferences.
            restart_debug_log(format!("background preferences load failed: {error}"));
            SavedBackground::default()
        });
        Self {
            path,
            saved: Mutex::new(saved),
            tray_available: AtomicBool::new(false),
            close_requested: AtomicBool::new(false),
        }
    }

    fn persist(&self, saved: &SavedBackground) -> Result<(), String> {
        let parent = self
            .path
            .parent()
            .ok_or("Invalid background settings path")?;
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        let temp = self
            .path
            .with_extension(format!("{}.tmp", std::process::id()));
        let result = (|| {
            let mut file = fs::File::create(&temp).map_err(|error| error.to_string())?;
            file.write_all(&serde_json::to_vec_pretty(saved).map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?;
            file.sync_all().map_err(|error| error.to_string())?;
            drop(file);
            crate::atomic_file::commit(&temp, &self.path).map_err(|error| error.to_string())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temp);
        }
        result
    }

    fn remembered_close_action(&self) -> Option<CloseAction> {
        let saved = self.saved.lock().ok()?;
        if !saved.preferences.remember_close_action {
            return None;
        }
        if saved.preferences.close_to_tray {
            self.tray_available
                .load(Ordering::Relaxed)
                .then_some(CloseAction::Tray)
        } else {
            Some(CloseAction::Exit)
        }
    }

    fn remember_close_action(&self, action: CloseAction) -> Result<(), String> {
        if action == CloseAction::Cancel {
            return Ok(());
        }
        let mut saved = self.saved.lock().map_err(|error| error.to_string())?;
        let mut updated = saved.clone();
        updated.preferences.remember_close_action = true;
        updated.preferences.close_to_tray = action == CloseAction::Tray;
        self.persist(&updated)?;
        *saved = updated;
        Ok(())
    }

    pub fn minimize_to_tray(&self) -> bool {
        self.tray_available.load(Ordering::Relaxed)
            && self
                .saved
                .lock()
                .map(|s| s.preferences.minimize_to_tray)
                .unwrap_or(false)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum CloseAction {
    Exit,
    Tray,
    Cancel,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CloseRequestStatus {
    requested: bool,
    tray_available: bool,
}

#[tauri::command]
pub fn desktop_window_close_status(
    window: WebviewWindow,
    state: State<'_, BackgroundState>,
) -> CloseRequestStatus {
    CloseRequestStatus {
        requested: window.label() == "main" && state.close_requested.load(Ordering::Relaxed),
        tray_available: state.tray_available.load(Ordering::Relaxed),
    }
}

/// Both the title-bar command and native close events share this entry point.
pub fn request_main_close(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<BackgroundState>();
    if let Some(action) = state.remembered_close_action() {
        return finish_main_close(app, action);
    }
    // Keep a pending request so closing during WebView startup is not lost.
    state.close_requested.store(true, Ordering::Relaxed);
    let window = app
        .get_webview_window("main")
        .ok_or("Main window is unavailable")?;
    window
        .emit_to(
            "main",
            "shinsekai:close-requested",
            CloseRequestStatus {
                requested: true,
                tray_available: state.tray_available.load(Ordering::Relaxed),
            },
        )
        .map_err(|error| error.to_string())
}

fn finish_main_close(app: &AppHandle, action: CloseAction) -> Result<(), String> {
    match action {
        CloseAction::Tray => app
            .get_webview_window("main")
            .ok_or("Main window is unavailable")?
            .hide()
            .map_err(|error| error.to_string())?,
        CloseAction::Exit => {
            let desktop = app.state::<DesktopState>();
            shutdown_desktop_app(app, desktop.inner(), "main window close confirmed");
        }
        CloseAction::Cancel => {}
    }
    app.state::<BackgroundState>()
        .close_requested
        .store(false, Ordering::Relaxed);
    Ok(())
}

#[tauri::command]
pub fn desktop_window_resolve_close(
    window: WebviewWindow,
    app: AppHandle,
    state: State<'_, BackgroundState>,
    action: CloseAction,
    remember: bool,
) -> Result<(), String> {
    if window.label() != "main" || !state.close_requested.load(Ordering::Relaxed) {
        return Err("No pending main-window close request".into());
    }
    if action == CloseAction::Tray && !state.tray_available.load(Ordering::Relaxed) {
        return Err("System tray is unavailable".into());
    }
    if remember {
        state.remember_close_action(action)?;
    }
    finish_main_close(&app, action)
}

#[tauri::command]
pub fn desktop_background_get(
    state: State<'_, BackgroundState>,
) -> Result<BackgroundStatus, String> {
    let saved = state.saved.lock().map_err(|error| error.to_string())?;
    Ok(BackgroundStatus {
        preferences: saved.preferences.clone(),
        tray_available: state.tray_available.load(Ordering::Relaxed),
    })
}

#[tauri::command]
pub fn desktop_background_save(
    state: State<'_, BackgroundState>,
    mut preferences: BackgroundPreferences,
) -> Result<BackgroundStatus, String> {
    preferences.validate()?;
    let mut saved = state.saved.lock().map_err(|error| error.to_string())?;
    // Legacy fields are owned by migration, never by a stale settings draft.
    preferences.bedtime_enabled = saved.preferences.bedtime_enabled;
    preferences.bedtime_time = saved.preferences.bedtime_time.clone();
    let updated = SavedBackground {
        preferences,
        ..saved.clone()
    };
    // Publish before changing live settings; a failed save must not enable a reminder.
    state.persist(&updated)?;
    *saved = updated;
    Ok(BackgroundStatus {
        preferences: saved.preferences.clone(),
        tray_available: state.tray_available.load(Ordering::Relaxed),
    })
}

fn parse_bedtime(time: &str) -> Result<NaiveTime, String> {
    let bytes = time.as_bytes();
    if bytes.len() != 5
        || bytes[2] != b':'
        || ![0, 1, 3, 4].iter().all(|&i| bytes[i].is_ascii_digit())
    {
        return Err("Bedtime must be HH:MM (00:00–23:59)".into());
    }
    NaiveTime::parse_from_str(time, "%H:%M")
        .map_err(|_| "Bedtime must be HH:MM (00:00–23:59)".into())
}

pub(crate) fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn create_tray(app: &AppHandle) -> tauri::Result<()> {
    let language = app
        .state::<BackgroundState>()
        .saved
        .lock()
        .map(|s| s.preferences.language.clone())
        .unwrap_or_default();
    let labels = match language.as_str() {
        "en" => ["Open Shinsekai", "Hide to tray", "Quit Shinsekai"],
        "ja" => ["Shinsekai を開く", "トレイに格納", "Shinsekai を終了"],
        _ => ["打开 Shinsekai", "收起到托盘", "退出 Shinsekai"],
    };
    let open = MenuItem::with_id(app, "background-open", labels[0], true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "background-hide", labels[1], true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "background-quit", labels[2], true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &hide, &quit])?;
    let mut tray = TrayIconBuilder::with_id("shinsekai-background")
        .tooltip("Shinsekai")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "background-open" => show_main(app),
            "background-hide" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            "background-quit" => {
                let app = app.clone();
                thread::spawn(move || {
                    let state = app.state::<DesktopState>();
                    shutdown_desktop_app(&app, state.inner(), "tray quit");
                });
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                }
            ) {
                if crate::reminders::show_panel(tray.app_handle(), true).is_err() {
                    show_main(tray.app_handle());
                }
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

pub fn setup(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    app.manage(BackgroundState::load(
        app.path().app_config_dir()?.join("background.json"),
    ));
    match create_tray(app) {
        Ok(()) => app
            .state::<BackgroundState>()
            .tray_available
            .store(true, Ordering::Relaxed),
        Err(error) => restart_debug_log(format!(
            "tray unavailable; keep normal window behavior: {error}"
        )),
    }
    let app = app.clone();
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(15));
        // Retry migration after bridge startup or transient failure. Its database
        // marker prevents duplicates if the native settings commit is interrupted.
        let state = app.state::<BackgroundState>();
        let snapshot = state.saved.lock().ok().map(|saved| saved.clone());
        if let Some(snapshot) = snapshot.filter(|saved| saved.preferences.bedtime_enabled) {
            if crate::reminders::migrate_bedtime(
                &app,
                &snapshot.preferences.bedtime_time,
                snapshot.last_delivered_date.map(|date| date.to_string()),
                &snapshot.preferences.language,
            )
            .is_ok()
            {
                if let Ok(mut saved) = state.saved.lock() {
                    let mut updated = saved.clone();
                    updated.preferences.bedtime_enabled = false;
                    if state.persist(&updated).is_ok() {
                        *saved = updated;
                    }
                }
            }
        }
        // The bridge may still be booting; retry on the next tick.
        let _ = crate::reminders::poll(&app);
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn random_index(len: usize) -> Result<usize, String> {
        let mut bytes = [0u8; 8];
        getrandom::fill(&mut bytes).map_err(|error| error.to_string())?;
        Ok((u64::from_ne_bytes(bytes) % len as u64) as usize)
    }

    fn at(value: &str) -> NaiveDateTime {
        NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S").unwrap()
    }

    fn enabled(time: &str) -> SavedBackground {
        SavedBackground {
            preferences: BackgroundPreferences {
                bedtime_enabled: true,
                bedtime_time: time.into(),
                ..Default::default()
            },
            ..Default::default()
        }
    }

    #[test]
    fn validates_time_and_defaults_to_no_background_behavior() {
        for value in ["00:00", "23:59", "08:30"] {
            assert!(parse_bedtime(value).is_ok());
        }
        for value in ["24:00", "23:60", "8:30", "", "aa:bb", "12:34:00", "１２:00"] {
            assert!(parse_bedtime(value).is_err(), "{value}");
        }
        let saved = SavedBackground::default();
        assert!(!saved.preferences.close_to_tray);
        assert!(!saved.preferences.minimize_to_tray);
        assert!(!saved.preferences.bedtime_enabled);
    }

    #[test]
    fn settings_replace_atomically_and_reload() {
        let dir = std::env::temp_dir().join(format!(
            "shinsekai-background-{}-{}",
            std::process::id(),
            random_index(usize::MAX).unwrap()
        ));
        let state = BackgroundState::load(dir.join("background.json"));
        state.persist(&enabled("22:30")).unwrap();
        let mut saved = enabled("23:45");
        saved.preferences.close_to_tray = true;
        saved.preferences.remember_close_action = true;
        saved.preferences.minimize_to_tray = true;
        saved.last_delivered_date = Some(at("2026-09-12 23:45:00").date());
        state.persist(&saved).unwrap();
        let restored = BackgroundState::load(state.path.clone());
        assert_eq!(
            restored.saved.lock().unwrap().last_delivered_date,
            saved.last_delivered_date
        );
        assert_eq!(
            restored.saved.lock().unwrap().preferences.bedtime_time,
            "23:45"
        );
        assert_eq!(restored.remembered_close_action(), None);
        assert!(!restored.minimize_to_tray());
        restored.tray_available.store(true, Ordering::Relaxed);
        assert_eq!(restored.remembered_close_action(), Some(CloseAction::Tray));
        assert!(restored.minimize_to_tray());
        fs::remove_file(&state.path).unwrap();
        fs::remove_dir(&dir).unwrap();
    }

    #[test]
    fn close_defaults_ask_and_legacy_preferences_do_not_imply_remembering() {
        let legacy: SavedBackground =
            serde_json::from_str(r#"{"preferences":{"closeToTray":true,"bedtimeEnabled":true}}"#)
                .unwrap();
        assert!(!legacy.preferences.remember_close_action);
        assert!(legacy.preferences.bedtime_enabled);
        let state = BackgroundState::load(PathBuf::new());
        assert_eq!(state.remembered_close_action(), None);
        assert!(!state.close_requested.load(Ordering::Relaxed));
    }

    #[test]
    fn remembered_exit_and_tray_can_be_reset_without_touching_reminders() {
        let dir = std::env::temp_dir().join(format!(
            "shinsekai-close-{}",
            random_index(usize::MAX).unwrap()
        ));
        let state = BackgroundState::load(dir.join("background.json"));
        *state.saved.lock().unwrap() = enabled("22:30");
        state.remember_close_action(CloseAction::Cancel).unwrap();
        assert!(!state.path.exists());
        state.remember_close_action(CloseAction::Exit).unwrap();
        assert_eq!(
            BackgroundState::load(state.path.clone()).remembered_close_action(),
            Some(CloseAction::Exit)
        );
        state.remember_close_action(CloseAction::Tray).unwrap();
        assert_eq!(state.remembered_close_action(), None); // Tray unavailable: ask again.
        state.tray_available.store(true, Ordering::Relaxed);
        assert_eq!(state.remembered_close_action(), Some(CloseAction::Tray));
        {
            let mut saved = state.saved.lock().unwrap();
            assert!(saved.preferences.bedtime_enabled);
            assert_eq!(saved.preferences.bedtime_time, "22:30");
            saved.preferences.remember_close_action = false;
            state.persist(&saved).unwrap();
        }
        assert_eq!(
            BackgroundState::load(state.path.clone()).remembered_close_action(),
            None
        );
        fs::remove_file(&state.path).unwrap();
        fs::remove_dir(&dir).unwrap();
    }

    #[test]
    fn failed_choice_save_keeps_asking() {
        let dir = std::env::temp_dir().join(format!(
            "shinsekai-close-fail-{}",
            random_index(usize::MAX).unwrap()
        ));
        fs::write(&dir, "not a directory").unwrap();
        let state = BackgroundState::load(dir.join("background.json"));
        assert!(state.remember_close_action(CloseAction::Exit).is_err());
        assert_eq!(state.remembered_close_action(), None);
        fs::remove_file(&dir).unwrap();
    }

    #[test]
    fn failed_settings_replacement_cleans_temporary_file_and_keeps_memory_unchanged() {
        let dir = std::env::temp_dir().join(format!(
            "shinsekai-background-fail-{}",
            random_index(usize::MAX).unwrap()
        ));
        let path = dir.join("background.json");
        fs::create_dir_all(&path).unwrap();
        let state = BackgroundState::load(path.clone());
        assert!(state.remember_close_action(CloseAction::Exit).is_err());
        assert_eq!(state.remembered_close_action(), None);
        assert!(path.is_dir());
        assert_eq!(fs::read_dir(&dir).unwrap().count(), 1);
        fs::remove_dir(path).unwrap();
        fs::remove_dir(dir).unwrap();
    }
}
