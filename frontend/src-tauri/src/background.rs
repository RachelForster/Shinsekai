//! Native tray and daily reminders, independent of WebView timers and visibility.
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

use chrono::{Local, NaiveDate, NaiveDateTime, NaiveTime};
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
    preferences: BackgroundPreferences,
) -> Result<BackgroundStatus, String> {
    preferences.validate()?;
    let mut saved = state.saved.lock().map_err(|error| error.to_string())?;
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

#[tauri::command]
pub async fn desktop_background_test(app: AppHandle, language: String) -> Result<(), String> {
    let preferences = BackgroundPreferences {
        language,
        ..Default::default()
    };
    preferences.validate()?;
    tauri::async_runtime::spawn_blocking(move || {
        send_bedtime_notification(&app, &preferences.language)
    })
    .await
    .map_err(|error| error.to_string())?
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

/// A 30-minute grace window also covers late starts and resume across midnight.
/// Record the scheduled date, not the delivery date, for restart/DST deduplication.
fn due_date(saved: &SavedBackground, now: NaiveDateTime) -> Option<NaiveDate> {
    if !saved.preferences.bedtime_enabled {
        return None;
    }
    let time = parse_bedtime(&saved.preferences.bedtime_time).ok()?;
    let today = now.date();
    for date in [Some(today), today.pred_opt()].into_iter().flatten() {
        let late = now.signed_duration_since(date.and_time(time));
        if late >= chrono::Duration::zero()
            && late <= chrono::Duration::minutes(30)
            && saved.last_delivered_date.is_none_or(|last| last < date)
        {
            return Some(date);
        }
    }
    None
}

#[derive(Deserialize)]
struct ReminderCharacter {
    name: String,
}

fn character_names(app: &AppHandle) -> Result<Vec<String>, String> {
    let desktop = app.state::<DesktopState>();
    let response = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|error| error.to_string())?
        .get(format!("{}/api/characters", desktop.bridge_url()))
        .header("X-Shinsekai-Bridge-Token", &desktop.bridge_auth_token)
        .send()
        .and_then(|response| response.error_for_status())
        .and_then(|response| response.text())
        .map_err(|error| error.to_string())?;
    let characters: Vec<ReminderCharacter> =
        serde_json::from_str(&response).map_err(|error| error.to_string())?;
    let mut names: Vec<String> = characters
        .into_iter()
        .map(|c| c.name.trim().to_owned())
        .filter(|name| !name.is_empty())
        .collect();
    names.sort();
    names.dedup();
    Ok(names)
}

fn random_index(len: usize) -> Result<usize, String> {
    if len == 0 {
        return Err("Cannot choose from an empty list".into());
    }
    let mut bytes = [0u8; 8];
    getrandom::fill(&mut bytes).map_err(|error| error.to_string())?;
    Ok((u64::from_ne_bytes(bytes) % len as u64) as usize)
}

fn send_bedtime_notification(app: &AppHandle, language: &str) -> Result<(), String> {
    let (title, body) = bedtime_message(app, language)?;
    show_notification(app, title, body)
}

fn bedtime_message(app: &AppHandle, language: &str) -> Result<(String, String), String> {
    let names = character_names(app)?;
    let name = if names.is_empty() {
        "Shinsekai"
    } else {
        &names[random_index(names.len())?]
    };
    let (title, messages) = match language {
        "en" => (format!("{name} · Time for bed"), [
            "It's getting late. Put today on pause and get some rest. Good night!",
            "Time to recharge! Put down the screen; we'll continue tomorrow. Sweet dreams.",
            "You've done enough for today. Get comfortable and sleep well. I'll see you tomorrow!",
        ]),
        "ja" => (format!("{name} · おやすみの時間"), [
            "もう遅いよ。今日はここまでにして、ゆっくり休もう。おやすみ！",
            "そろそろ充電の時間だよ。画面を閉じて、続きはまた明日。いい夢を！",
            "今日もおつかれさま。あたたかくして、ぐっすり眠ってね。また明日！",
        ]),
        _ => (format!("{name} · 该睡觉啦"), [
            "已经很晚啦，今天就先到这里吧。快去洗漱休息，晚安，做个好梦！",
            "该给自己充充电了。放下屏幕，剩下的事情明天再说，好不好？晚安。",
            "今天也辛苦了！记得早点钻进被窝，盖好被子。明天再来找我玩吧。",
        ]),
    };
    Ok((title, messages[random_index(messages.len())?].into()))
}

fn show_notification(app: &AppHandle, title: String, body: String) -> Result<(), String> {
    let (name, label) = title.rsplit_once(" · ").unwrap_or(("Shinsekai", &title));
    crate::reminders::deliver(
        app,
        crate::reminders::Notice {
            id: format!("bedtime-{}", Local::now().timestamp_millis()),
            character_name: name.into(),
            title: label.into(),
            message: body,
            due_at: Local::now().to_rfc3339(),
            audio_path: None,
            audio_volume: 1.0,
        },
    )
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
        // This runs even when the daily bedtime preset is disabled.
        // The bridge may still be booting; retry on the next tick without log spam.
        let _ = crate::reminders::poll(&app);
        let state = app.state::<BackgroundState>();
        let snapshot = {
            let Ok(saved) = state.saved.lock() else {
                continue;
            };
            if due_date(&saved, Local::now().naive_local()).is_none() {
                continue;
            }
            saved.clone()
        };
        // Fetch outside the settings lock, keeping window actions responsive when
        // the bridge is slow. Recheck after fetching so disabling cancels delivery.
        let message = bedtime_message(&app, &snapshot.preferences.language);
        let Ok(mut saved) = state.saved.lock() else {
            continue;
        };
        if saved.preferences != snapshot.preferences {
            continue;
        }
        let Some(date) = due_date(&saved, Local::now().naive_local()) else {
            continue;
        };
        match message.and_then(|(title, body)| show_notification(&app, title, body)) {
            Ok(()) => {
                saved.last_delivered_date = Some(date);
                if let Err(error) = state.persist(&saved) {
                    restart_debug_log(format!("reminder delivery persistence failed: {error}"));
                }
            }
            Err(error) => {
                restart_debug_log(format!("bedtime reminder failed: {error}"));
                drop(saved);
                thread::sleep(Duration::from_secs(45));
            }
        }
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

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
        assert_eq!(due_date(&saved, at("2026-09-12 23:00:00")), None);
    }

    #[test]
    fn daily_reminder_has_bounded_catch_up_and_survives_midnight() {
        let saved = enabled("23:50");
        let day = at("2026-09-12 23:50:00").date();
        assert_eq!(due_date(&saved, at("2026-09-12 23:49:59")), None);
        assert_eq!(due_date(&saved, at("2026-09-12 23:50:00")), Some(day));
        assert_eq!(due_date(&saved, at("2026-09-13 00:20:00")), Some(day));
        assert_eq!(due_date(&saved, at("2026-09-13 00:20:01")), None);
        assert_eq!(due_date(&saved, at("2026-09-13 09:00:00")), None);
    }

    #[test]
    fn persisted_delivery_deduplicates_restarts_clock_rollback_and_time_edits() {
        let mut saved = enabled("23:00");
        saved.last_delivered_date = Some(at("2026-09-12 23:00:00").date());
        let mut restored: SavedBackground =
            serde_json::from_slice(&serde_json::to_vec(&saved).unwrap()).unwrap();
        assert_eq!(due_date(&restored, at("2026-09-12 23:00:15")), None);
        assert_eq!(due_date(&restored, at("2026-09-11 23:00:00")), None);
        restored.preferences.bedtime_time = "23:10".into();
        assert_eq!(due_date(&restored, at("2026-09-12 23:10:00")), None);
        assert_eq!(
            due_date(&restored, at("2026-09-13 23:10:00")),
            Some(at("2026-09-13 23:10:00").date())
        );
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
            due_date(&restored.saved.lock().unwrap(), at("2026-09-12 23:45:15")),
            None
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
