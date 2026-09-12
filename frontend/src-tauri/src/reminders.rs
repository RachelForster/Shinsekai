//! Custom character reminder surface and native delivery of persistent schedules.
use std::{collections::VecDeque, sync::Mutex, thread, time::Duration};

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
    #[serde(default)]
    pub audio_path: Option<String>,
    #[serde(default = "default_audio_volume")]
    pub audio_volume: f64,
}

fn default_audio_volume() -> f64 {
    1.0
}

#[derive(Default)]
struct EnrichmentQueue {
    running: bool,
    notices: VecDeque<Notice>,
}

#[derive(Default)]
pub struct ReminderState {
    notices: Mutex<VecDeque<Notice>>,
    delivered: Mutex<VecDeque<String>>,
    enrichment: Mutex<EnrichmentQueue>,
}

pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    app.manage(ReminderState::default());
    let desktop = app.state::<DesktopState>();
    let url = app_window_url_for_route(
        desktop.bridge_port,
        &desktop.bridge_auth_token,
        "/reminders",
    );
    // Wry already enables autoplay. Keep the shared WebView environment's default arguments.
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
            let _ = hidden.emit_to("reminders", "shinsekai:reminders-hidden", ());
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
    let _ = window.emit_to("reminders", "shinsekai:reminders-changed", ());
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
    drop(delivered);
    enqueue_enrichment(app, notice);
    Ok(())
}

fn bridge(app: &AppHandle, route: &str, body: Option<Value>) -> Result<Value, String> {
    bridge_with_timeout(app, route, body, 5)
}

fn bridge_with_timeout(
    app: &AppHandle,
    route: &str,
    body: Option<Value>,
    seconds: u64,
) -> Result<Value, String> {
    let desktop = app.state::<DesktopState>();
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(seconds))
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

fn enqueue_enrichment(app: &AppHandle, notice: Notice) {
    let state = app.state::<ReminderState>();
    let Ok(mut queue) = state.enrichment.lock() else {
        return;
    };
    if queue.notices.len() >= 30 {
        queue.notices.pop_front();
    }
    queue.notices.push_back(notice);
    if queue.running {
        return;
    }
    queue.running = true;
    let app = app.clone();
    thread::spawn(move || loop {
        let next = {
            let state = app.state::<ReminderState>();
            let Ok(mut queue) = state.enrichment.lock() else {
                return;
            };
            match queue.notices.pop_front() {
                Some(notice) => notice,
                None => {
                    queue.running = false;
                    return;
                }
            }
        };
        if let Err(error) = enrich_notice(&app, next) {
            restart_debug_log(format!(
                "reminder enrichment failed; retaining text: {error}"
            ));
        }
    });
}

fn is_pending(app: &AppHandle, notice: &Notice) -> bool {
    app.state::<ReminderState>()
        .notices
        .lock()
        .map(|notices| {
            notices
                .iter()
                .any(|item| item.id == notice.id && item.due_at == notice.due_at)
        })
        .unwrap_or(false)
}

fn update_notice(app: &AppHandle, notice: &Notice) -> Result<(), String> {
    let state = app.state::<ReminderState>();
    let mut notices = state.notices.lock().map_err(|e| e.to_string())?;
    if let Some(item) = notices
        .iter_mut()
        .find(|item| item.id == notice.id && item.due_at == notice.due_at)
    {
        *item = notice.clone();
        // Updating text/audio must not reopen a dismissed or manually hidden panel.
        app.emit_to("reminders", "shinsekai:reminders-updated", ())
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn enrich_notice(app: &AppHandle, mut notice: Notice) -> Result<(), String> {
    if !is_pending(app, &notice) {
        return Ok(());
    }
    let result = bridge_with_timeout(
        app,
        "/presentation",
        Some(json!({
            "character_name": notice.character_name, "title": notice.title,
            "message": notice.message, "due_at": notice.due_at,
        })),
        35,
    )?;
    if let Some(message) = result["message"].as_str() {
        notice.message = message.to_string();
    }
    update_notice(app, &notice)?;
    if !is_pending(app, &notice) {
        return Ok(());
    }
    let speech = bridge_with_timeout(
        app,
        "/speech",
        Some(json!({
            "dialog": result["dialog"],
        })),
        120,
    )?;
    notice.audio_path = speech["audio_path"].as_str().map(str::to_string);
    notice.audio_volume = speech["audio_volume"]
        .as_f64()
        .unwrap_or(1.0)
        .clamp(0.0, 1.0);
    update_notice(app, &notice)
}

#[tauri::command]
pub fn desktop_reminders_visible(app: AppHandle) -> bool {
    app.get_webview_window("reminders")
        .and_then(|window| window.is_visible().ok())
        .unwrap_or(false)
}

pub fn poll(app: &AppHandle) -> Result<(), String> {
    poll_with(
        |route, body| bridge(app, route, body),
        |notice| deliver(app, notice),
    )
}

fn poll_with(
    mut request: impl FnMut(&str, Option<Value>) -> Result<Value, String>,
    mut deliver: impl FnMut(Notice) -> Result<(), String>,
) -> Result<(), String> {
    let claims = request("/claim", Some(json!({})))?;
    for claim in claims.as_array().ok_or("Invalid reminder response")? {
        let notice: Notice = serde_json::from_value(claim.clone()).map_err(|e| e.to_string())?;
        // Cancellation, editing or a newer lease can invalidate this snapshot.
        // Commit its claim before exposing it to the inbox, UI or voice worker.
        let acknowledgement = request(
            "/ack",
            Some(json!({"reminder_id": claim["id"], "claim_token": claim["claim_token"]})),
        )?;
        match acknowledgement["ok"].as_bool() {
            Some(true) => deliver(notice)?,
            Some(false) => continue,
            None => return Err("Invalid reminder acknowledgement".into()),
        }
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
        "hide" => {
            app.get_webview_window("reminders")
                .ok_or("Reminder panel is unavailable")?
                .hide()
                .map_err(|e| e.to_string())?;
            app.emit_to("reminders", "shinsekai:reminders-hidden", ())
                .map_err(|e| e.to_string())
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn claimed(id: &str) -> Value {
        json!({
            "id": id, "character_name": "澪", "title": "休息",
            "message": "该睡觉了", "due_at": "2026-09-12T23:00:00+08:00",
            "claim_token": format!("lease-{id}")
        })
    }

    #[test]
    fn invalidated_claim_is_skipped_before_inbox_and_valid_claim_follows_ack() {
        use std::cell::RefCell;
        let events = RefCell::new(Vec::new());
        poll_with(
            |route, body| match route {
                "/claim" => Ok(json!([
                    claimed("cancelled"),
                    claimed("updated"),
                    claimed("valid")
                ])),
                "/ack" => {
                    let body = body.unwrap();
                    let id = body["reminder_id"].as_str().unwrap();
                    assert_eq!(body["claim_token"], format!("lease-{id}"));
                    events.borrow_mut().push(format!("ack:{id}"));
                    Ok(json!({"ok": id == "valid"}))
                }
                _ => panic!("Unexpected route: {route}"),
            },
            |notice| {
                events.borrow_mut().push(format!("show:{}", notice.id));
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(
            *events.borrow(),
            ["ack:cancelled", "ack:updated", "ack:valid", "show:valid"]
        );
    }

    #[test]
    fn failed_or_malformed_acknowledgement_never_displays_a_claim() {
        for response in [
            Err("bridge disconnected".to_string()),
            Ok(json!({})),
            Ok(json!({"ok": "true"})),
        ] {
            let result = poll_with(
                |route, _| {
                    if route == "/claim" {
                        Ok(json!([claimed("pending")]))
                    } else {
                        response.clone()
                    }
                },
                |_| panic!("Unvalidated reminder must not be delivered"),
            );
            assert!(result.is_err());
        }
    }

    #[test]
    fn persisted_schedule_claims_are_deliverable_before_voice_is_generated() {
        let notice: Notice = serde_json::from_value(json!({
            "id": "schedule-1", "character_name": "澪", "title": "休息",
            "message": "该睡觉了", "due_at": "2026-09-12T23:00:00+08:00",
            "claim_token": "lease"
        }))
        .unwrap();
        assert!(notice.audio_path.is_none());
        assert_eq!(notice.audio_volume, 1.0);
        assert_eq!(notice.message, "该睡觉了");
    }
}
