//! Custom character reminder surface and native delivery of persistent schedules.
use std::{collections::VecDeque, sync::Mutex, time::Duration};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{
    AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, State, WebviewUrl,
    WebviewWindowBuilder,
};
use tauri_plugin_notification::NotificationExt;

use crate::{app_window_url_for_route, background, restart_debug_log, DesktopState};

const CARD_WIDTH: f64 = 420.0;
const CARD_HEIGHT: f64 = 184.0;

#[derive(Clone, Deserialize, Serialize)]
pub struct Notice {
    pub id: String,
    pub character_name: String,
    pub title: String,
    pub message: String,
    pub due_at: String,
}

#[derive(Default)]
pub struct ReminderState {
    notices: Mutex<VecDeque<Notice>>,
    delivered: Mutex<VecDeque<String>>,
}

pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    app.manage(ReminderState::default());
    let desktop = app.state::<DesktopState>();
    let url = app_window_url_for_route(
        desktop.bridge_port,
        &desktop.bridge_auth_token,
        "/reminders",
    );
    let window = WebviewWindowBuilder::new(app, "reminders", WebviewUrl::App(url.into()))
        .title("Shinsekai · 提醒")
        .inner_size(CARD_WIDTH, CARD_HEIGHT)
        .decorations(false)
        .transparent(true)
        .shadow(false)
        .resizable(false)
        .skip_taskbar(true)
        .always_on_top(true)
        .visible(false)
        .focused(false)
        .disable_drag_drop_handler()
        .build()?;
    let hidden = window.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = hidden.hide();
        }
    });
    Ok(())
}

fn resize_panel(app: &AppHandle, expanded: bool) -> Result<(), String> {
    let window = app
        .get_webview_window("reminders")
        .ok_or("Reminder panel is unavailable")?;
    let size = if expanded {
        LogicalSize::new(500.0, 500.0)
    } else {
        LogicalSize::new(CARD_WIDTH, CARD_HEIGHT)
    };
    window.set_size(size).map_err(|e| e.to_string())?;
    let monitor = app
        .get_webview_window("main")
        .and_then(|main| main.current_monitor().ok().flatten())
        .or_else(|| window.primary_monitor().ok().flatten());
    if let Some(monitor) = monitor {
        let area = monitor.work_area();
        let size = window.outer_size().map_err(|e| e.to_string())?;
        let margin = (16.0 * monitor.scale_factor()) as i32;
        let x = area.position.x + (area.size.width as i32 - size.width as i32 - margin).max(0);
        let y = area.position.y + (area.size.height as i32 - size.height as i32 - margin).max(0);
        window
            .set_position(PhysicalPosition::new(x, y))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn show_panel(app: &AppHandle, focus: bool) -> Result<(), String> {
    resize_panel(app, false)?;
    let window = app
        .get_webview_window("reminders")
        .ok_or("Reminder panel is unavailable")?;
    window.show().map_err(|e| e.to_string())?;
    if focus {
        window.set_focus().map_err(|e| e.to_string())?;
    }
    let _ = window.emit("shinsekai:reminders-changed", ());
    Ok(())
}

pub fn deliver(app: &AppHandle, notice: Notice) -> Result<(), String> {
    let state = app.state::<ReminderState>();
    let key = format!("{}:{}", notice.id, notice.due_at);
    if state
        .delivered
        .lock()
        .map_err(|e| e.to_string())?
        .contains(&key)
    {
        return Ok(());
    }
    {
        let mut notices = state.notices.lock().map_err(|e| e.to_string())?;
        notices.retain(|item| item.id != notice.id || item.due_at != notice.due_at);
        notices.push_front(notice.clone());
        notices.truncate(30);
    }
    if let Err(error) = show_panel(app, false) {
        restart_debug_log(format!(
            "reminder panel failed, using system notification: {error}"
        ));
        app.notification()
            .builder()
            .title(format!("{} · {}", notice.character_name, notice.title))
            .body(&notice.message)
            .show()
            .map_err(|e| e.to_string())?;
    }
    let mut delivered = state.delivered.lock().map_err(|e| e.to_string())?;
    delivered.push_front(key);
    delivered.truncate(512);
    Ok(())
}

fn bridge(app: &AppHandle, route: &str, body: Option<Value>) -> Result<Value, String> {
    let desktop = app.state::<DesktopState>();
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;
    let url = format!("{}/api/reminders{route}", desktop.bridge_url());
    let request = match body {
        Some(body) => client
            .post(url)
            .header("Content-Type", "application/json")
            .body(body.to_string()),
        None => client.get(url),
    };
    let response = request
        .header("X-Shinsekai-Bridge-Token", &desktop.bridge_auth_token)
        .send()
        .and_then(|r| r.error_for_status())
        .and_then(|r| r.text())
        .map_err(|e| e.to_string())?;
    serde_json::from_str(&response).map_err(|e| e.to_string())
}

pub fn poll(app: &AppHandle) -> Result<(), String> {
    let claims = bridge(app, "/claim", Some(json!({})))?;
    for claim in claims.as_array().ok_or("Invalid reminder response")? {
        let notice: Notice = serde_json::from_value(claim.clone()).map_err(|e| e.to_string())?;
        deliver(app, notice)?;
        bridge(
            app,
            "/ack",
            Some(json!({"reminder_id": claim["id"], "claim_token": claim["claim_token"]})),
        )?;
    }
    Ok(())
}

#[tauri::command]
pub fn desktop_reminders_inbox(state: State<'_, ReminderState>) -> Result<Vec<Notice>, String> {
    Ok(state
        .notices
        .lock()
        .map_err(|e| e.to_string())?
        .iter()
        .cloned()
        .collect())
}

#[tauri::command]
pub fn desktop_reminders_dismiss(
    state: State<'_, ReminderState>,
    id: String,
    due_at: String,
) -> Result<(), String> {
    state
        .notices
        .lock()
        .map_err(|e| e.to_string())?
        .retain(|notice| notice.id != id || notice.due_at != due_at);
    Ok(())
}

#[tauri::command]
pub fn desktop_reminders_window(app: AppHandle, action: String) -> Result<(), String> {
    match action.as_str() {
        "open" => show_panel(&app, true),
        "manage" => resize_panel(&app, true),
        "compact" => resize_panel(&app, false),
        "hide" => app
            .get_webview_window("reminders")
            .ok_or("Reminder panel is unavailable")?
            .hide()
            .map_err(|e| e.to_string()),
        "main" => {
            background::show_main(&app);
            Ok(())
        }
        _ => Err("Unknown reminder window action".into()),
    }
}

#[tauri::command]
pub async fn desktop_reminders_list(app: AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || bridge(&app, "", None))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn desktop_reminders_cancel(app: AppHandle, id: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        bridge(&app, "", Some(json!({"action":"cancel","reminder_id":id})))
    })
    .await
    .map_err(|e| e.to_string())?
}
