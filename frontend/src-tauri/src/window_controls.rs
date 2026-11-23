use std::process::Command;
#[cfg(target_os = "windows")]
use std::{thread, time::Duration};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde::Serialize;
#[cfg(desktop)]
use tauri::Emitter;
use tauri::{AppHandle, Manager, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder, Window};
use tauri_runtime::ResizeDirection;

use crate::{
    background,
    bridge::request_bridge_chat_close,
    frontend_protocol::chat_window_url,
    state::{
        restart_debug_log, DesktopMiniInputShortcutStatus, DesktopMiniWindowLayout, DesktopState,
        SavedChatWindowBounds,
    },
};

#[cfg(desktop)]
const MINI_AVATAR_INPUT_SHORTCUT_EVENT: &str = "shinsekai:mini-avatar-input-shortcut";
const CHAT_WINDOW_DEFAULT_WIDTH: f64 = 1280.0;
const CHAT_WINDOW_DEFAULT_HEIGHT: f64 = 820.0;
const CHAT_WINDOW_MIN_WIDTH: f64 = 960.0;
const CHAT_WINDOW_MIN_HEIGHT: f64 = 620.0;
const CHAT_MINI_WINDOW_WIDTH: f64 = 760.0;
const CHAT_MINI_WINDOW_HEIGHT: f64 = 420.0;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopWindowCursorPosition {
    x: f64,
    y: f64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct ChatWindowOpenPlan {
    pub(crate) defer_command: bool,
    pub(crate) navigate_after_create: bool,
    pub(crate) focus_after_show: bool,
}

#[tauri::command]
pub(crate) fn desktop_window_hide(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn desktop_chat_window_destroy(
    window: WebviewWindow,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    if window.label() != "chat" {
        return Err("desktop_chat_window_destroy is only available to the chat window".to_string());
    }
    state.reset_chat_window_session_bounds();
    schedule_mini_input_global_shortcut_sync(window.app_handle());
    window.destroy().map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn desktop_window_minimize(window: WebviewWindow) -> Result<(), String> {
    if window.label() == "main"
        && window
            .app_handle()
            .state::<background::BackgroundState>()
            .minimize_to_tray()
    {
        return window.hide().map_err(|error| error.to_string());
    }
    window.minimize().map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn desktop_window_set_always_on_top(
    window: WebviewWindow,
    always_on_top: bool,
) -> Result<(), String> {
    window
        .set_always_on_top(always_on_top)
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn desktop_window_toggle_maximize(window: WebviewWindow) -> Result<(), String> {
    if window.is_maximized().map_err(|error| error.to_string())? {
        window.unmaximize().map_err(|error| error.to_string())
    } else {
        window.maximize().map_err(|error| error.to_string())
    }
}

#[tauri::command]
pub(crate) fn desktop_window_start_drag(window: WebviewWindow) -> Result<(), String> {
    window.start_dragging().map_err(|error| error.to_string())
}

fn parse_resize_direction(direction: &str) -> Result<ResizeDirection, String> {
    match direction {
        "East" => Ok(ResizeDirection::East),
        "North" => Ok(ResizeDirection::North),
        "NorthEast" => Ok(ResizeDirection::NorthEast),
        "NorthWest" => Ok(ResizeDirection::NorthWest),
        "South" => Ok(ResizeDirection::South),
        "SouthEast" => Ok(ResizeDirection::SouthEast),
        "SouthWest" => Ok(ResizeDirection::SouthWest),
        "West" => Ok(ResizeDirection::West),
        _ => Err(format!("unknown resize direction: {direction}")),
    }
}

#[tauri::command]
pub(crate) fn desktop_window_start_resize(
    window: Window,
    direction: String,
) -> Result<(), String> {
    let direction = parse_resize_direction(direction.trim())?;
    window
        .start_resize_dragging(direction)
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn desktop_window_set_ignore_cursor_events(
    window: WebviewWindow,
    ignore: bool,
) -> Result<(), String> {
    window
        .set_ignore_cursor_events(ignore)
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn desktop_window_cursor_position(
    window: WebviewWindow,
) -> Result<DesktopWindowCursorPosition, String> {
    let cursor = window
        .cursor_position()
        .map_err(|error| error.to_string())?;
    let origin = window.outer_position().map_err(|error| error.to_string())?;
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let scale = if scale > 0.0 { scale } else { 1.0 };
    Ok(DesktopWindowCursorPosition {
        x: (cursor.x - f64::from(origin.x)) / scale,
        y: (cursor.y - f64::from(origin.y)) / scale,
    })
}

pub(crate) fn compute_mini_dock_side(
    window_center_x: f64,
    monitor_left: f64,
    monitor_width: f64,
) -> &'static str {
    if monitor_width > 0.0 && (window_center_x - monitor_left) / monitor_width >= 0.62 {
        "right"
    } else {
        "left"
    }
}

pub(crate) fn default_mini_window_position(
    monitor_pos: (i32, i32),
    monitor_size: (u32, u32),
    mini_size: (u32, u32),
) -> tauri::PhysicalPosition<i32> {
    let mon_w = f64::from(monitor_size.0);
    let mon_h = f64::from(monitor_size.1);
    let mini_w = f64::from(mini_size.0);
    let mini_h = f64::from(mini_size.1);
    let target_x = f64::from(monitor_pos.0) + mon_w * 0.84 - mini_w * 0.5;
    let target_y = f64::from(monitor_pos.1) + (mon_h * 0.24 - mini_h * 0.5).max(16.0);
    tauri::PhysicalPosition::new(target_x.round() as i32, target_y.round() as i32)
}

fn current_window_mini_dock_side(window: &WebviewWindow) -> &'static str {
    let Ok(origin) = window.outer_position() else {
        return "left";
    };
    let Ok(size) = window.outer_size() else {
        return "left";
    };
    let monitor = window
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| window.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else {
        return "left";
    };
    let center_x = f64::from(origin.x) + f64::from(size.width) * 0.5;
    compute_mini_dock_side(
        center_x,
        f64::from(monitor.position().x),
        f64::from(monitor.size().width),
    )
}

#[tauri::command]
pub(crate) fn desktop_chat_window_set_mini_mode(
    window: WebviewWindow,
    state: State<'_, DesktopState>,
    mini: bool,
    restore_always_on_top: bool,
) -> Result<DesktopMiniWindowLayout, String> {
    if window.label() != "chat" {
        return Ok(DesktopMiniWindowLayout { dock_side: "left" });
    }
    let mut mode = state
        .chat_window_mode
        .lock()
        .map_err(|error| error.to_string())?;
    if mini {
        if !mode.mini_active {
            let maximized = window.is_maximized().unwrap_or(false);
            if maximized {
                let _ = window.unmaximize();
            }
            if let (Ok(position), Ok(size)) = (window.outer_position(), window.inner_size()) {
                mode.normal_bounds = Some(SavedChatWindowBounds {
                    position,
                    size,
                    maximized,
                });
            }
            mode.mini_active = true;
        }
        let mini_logical = tauri::LogicalSize::new(CHAT_MINI_WINDOW_WIDTH, CHAT_MINI_WINDOW_HEIGHT);
        let _ = window.set_always_on_top(true);
        let _ = window.set_min_size(Some(mini_logical));
        let _ = window.set_size(mini_logical);
        let _ = window.set_resizable(false);
        let target_pos = mode.mini_position.or_else(|| {
            let monitor = window
                .current_monitor()
                .ok()
                .flatten()
                .or_else(|| window.primary_monitor().ok().flatten())?;
            let scale = window.scale_factor().unwrap_or(1.0).max(0.5);
            let mini_phys = (
                (CHAT_MINI_WINDOW_WIDTH * scale).round() as u32,
                (CHAT_MINI_WINDOW_HEIGHT * scale).round() as u32,
            );
            let computed = default_mini_window_position(
                (monitor.position().x, monitor.position().y),
                (monitor.size().width, monitor.size().height),
                mini_phys,
            );
            mode.mini_position = Some(computed);
            Some(computed)
        });
        if let Some(pos) = target_pos {
            let _ = window.set_position(pos);
        }
        drop(mode);
        schedule_mini_input_global_shortcut_sync(window.app_handle());
        Ok(DesktopMiniWindowLayout {
            dock_side: current_window_mini_dock_side(&window),
        })
    } else {
        if mode.mini_active {
            if let Ok(pos) = window.outer_position() {
                mode.mini_position = Some(pos);
            }
            mode.mini_active = false;
            let saved = mode.normal_bounds.take();
            let _ = window.set_resizable(true);
            let _ = window.set_always_on_top(restore_always_on_top);
            let normal_min = tauri::LogicalSize::new(CHAT_WINDOW_MIN_WIDTH, CHAT_WINDOW_MIN_HEIGHT);
            if let Some(bounds) = saved {
                let _ = window.set_size(bounds.size);
                let _ = window.set_position(bounds.position);
                let _ = window.set_min_size(Some(normal_min));
                if bounds.maximized {
                    let _ = window.maximize();
                }
            } else {
                let _ = window.set_size(tauri::LogicalSize::new(
                    CHAT_WINDOW_DEFAULT_WIDTH,
                    CHAT_WINDOW_DEFAULT_HEIGHT,
                ));
                let _ = window.set_min_size(Some(normal_min));
                let _ = window.center();
            }
        }
        drop(mode);
        schedule_mini_input_global_shortcut_sync(window.app_handle());
        Ok(DesktopMiniWindowLayout { dock_side: "left" })
    }
}

pub(crate) fn desired_mini_input_global_shortcut(
    mini_active: bool,
    chat_window_present: bool,
    configured: Option<&str>,
) -> Option<String> {
    if !mini_active || !chat_window_present {
        return None;
    }
    configured
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

#[cfg(desktop)]
fn activate_mini_avatar_input_from_shortcut(app: &AppHandle) {
    let mini_active = app
        .try_state::<DesktopState>()
        .and_then(|state| state.chat_window_mode.lock().ok().map(|mode| mode.mini_active))
        .unwrap_or(false);
    if !mini_active {
        return;
    }
    let Some(chat_window) = app.get_webview_window("chat") else {
        return;
    };
    let _ = chat_window.set_ignore_cursor_events(false);
    let _ = chat_window.show();
    let _ = chat_window.unminimize();
    let _ = chat_window.set_focus();
    let _ = chat_window.emit_to("chat", MINI_AVATAR_INPUT_SHORTCUT_EVENT, ());
}

#[cfg(desktop)]
fn apply_mini_input_global_shortcut_blocking(app: &AppHandle) -> DesktopMiniInputShortcutStatus {
    use tauri_plugin_global_shortcut::ShortcutState;

    let Some(global_shortcut) =
        app.try_state::<tauri_plugin_global_shortcut::GlobalShortcut<tauri::Wry>>()
    else {
        return DesktopMiniInputShortcutStatus {
            registered: false,
            error: Some("global shortcut plugin is unavailable".to_string()),
        };
    };

    let Some(state) = app.try_state::<DesktopState>() else {
        return DesktopMiniInputShortcutStatus {
            registered: false,
            error: None,
        };
    };

    let _sync_guard = match state.mini_shortcut_sync_lock.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };

    let desired = state
        .chat_window_mode
        .lock()
        .ok()
        .and_then(|mode| {
            desired_mini_input_global_shortcut(
                mode.mini_active,
                app.get_webview_window("chat").is_some(),
                mode.mini_input_shortcut.as_deref(),
            )
        });

    if let Err(error) = global_shortcut.unregister_all() {
        restart_debug_log(format!("mini shortcut unregister_all failed: {error}"));
    }

    let Some(shortcut) = desired else {
        return DesktopMiniInputShortcutStatus {
            registered: false,
            error: None,
        };
    };

    match global_shortcut.on_shortcut(shortcut.as_str(), |app_handle, _shortcut, event| {
        if event.state == ShortcutState::Pressed {
            activate_mini_avatar_input_from_shortcut(app_handle);
        }
    }) {
        Ok(()) => DesktopMiniInputShortcutStatus {
            registered: true,
            error: None,
        },
        Err(error) => {
            let message = error.to_string();
            restart_debug_log(format!(
                "mini shortcut register failed shortcut={shortcut} error={message}"
            ));
            DesktopMiniInputShortcutStatus {
                registered: false,
                error: Some(message),
            }
        }
    }
}

#[cfg(not(desktop))]
fn apply_mini_input_global_shortcut_blocking(_app: &AppHandle) -> DesktopMiniInputShortcutStatus {
    DesktopMiniInputShortcutStatus {
        registered: false,
        error: None,
    }
}

pub(crate) fn schedule_mini_input_global_shortcut_sync(app: &AppHandle) {
    let app_handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let _ = apply_mini_input_global_shortcut_blocking(&app_handle);
    });
}

#[tauri::command]
pub(crate) async fn desktop_chat_window_set_mini_input_shortcut(
    app: AppHandle,
    window: WebviewWindow,
    shortcut: Option<String>,
) -> Result<DesktopMiniInputShortcutStatus, String> {
    if window.label() != "chat" {
        return Ok(DesktopMiniInputShortcutStatus {
            registered: false,
            error: None,
        });
    }
    let normalized = shortcut
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    {
        let state = app.state::<DesktopState>();
        let mut mode = state
            .chat_window_mode
            .lock()
            .map_err(|error| error.to_string())?;
        mode.mini_input_shortcut = normalized;
    }
    tauri::async_runtime::spawn_blocking(move || apply_mini_input_global_shortcut_blocking(&app))
        .await
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn desktop_chat_window_sync_mini_layout(
    window: WebviewWindow,
    state: State<'_, DesktopState>,
) -> Result<DesktopMiniWindowLayout, String> {
    if window.label() != "chat" {
        return Ok(DesktopMiniWindowLayout { dock_side: "left" });
    }
    if let Ok(mut mode) = state.chat_window_mode.lock() {
        if mode.mini_active {
            if let Ok(pos) = window.outer_position() {
                mode.mini_position = Some(pos);
            }
        }
    }
    Ok(DesktopMiniWindowLayout {
        dock_side: current_window_mini_dock_side(&window),
    })
}

#[tauri::command]
pub(crate) fn desktop_window_close(
    window: WebviewWindow,
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    if window.label() == "main" {
        return background::request_main_close(&app);
    }
    if window.label() == "chat" {
        state.reset_chat_window_session_bounds();
        schedule_mini_input_global_shortcut_sync(&app);
        request_bridge_chat_close(state.inner(), "desktop_window_close command");
        return window.destroy().map_err(|error| error.to_string());
    }
    window.close().map_err(|error| error.to_string())
}

#[tauri::command]
#[cfg(target_os = "windows")]
pub(crate) fn desktop_open_chat_window(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    debug_assert!(current_chat_window_open_plan().defer_command);
    let thread_app = app.clone();
    let bridge_port = state.bridge_port;
    let auth_token = state.bridge_auth_token.clone();
    restart_debug_log("desktop_open_chat_window windows schedule requested");
    thread::spawn(move || {
        restart_debug_log("desktop_open_chat_window windows thread start");
        thread::sleep(Duration::from_millis(100));
        let scheduled_app = thread_app.clone();
        match thread_app.run_on_main_thread(move || {
            restart_debug_log("desktop_open_chat_window windows scheduled start");
            match open_chat_window(&scheduled_app, bridge_port, &auth_token) {
                Ok(()) => restart_debug_log("desktop_open_chat_window windows scheduled completed"),
                Err(error) => restart_debug_log(format!(
                    "desktop_open_chat_window windows scheduled failed error={error}"
                )),
            }
        }) {
            Ok(()) => restart_debug_log("desktop_open_chat_window windows run_on_main_thread ok"),
            Err(error) => restart_debug_log(format!(
                "desktop_open_chat_window windows run_on_main_thread failed error={error}"
            )),
        }
    });
    restart_debug_log("desktop_open_chat_window windows command returned after spawn");
    Ok(())
}

#[tauri::command]
#[cfg(not(target_os = "windows"))]
pub(crate) fn desktop_open_chat_window(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    debug_assert!(!current_chat_window_open_plan().defer_command);
    open_chat_window(&app, state.bridge_port, &state.bridge_auth_token)
}

fn open_chat_window(app: &AppHandle, bridge_port: u16, auth_token: &str) -> Result<(), String> {
    let open_plan = current_chat_window_open_plan();
    let chat_window = if let Some(window) = app.get_webview_window("chat") {
        restart_debug_log("desktop_open_chat_window reuse existing window");
        window
    } else {
        let url = chat_window_url(bridge_port, auth_token);
        restart_debug_log(format!("desktop_open_chat_window create url={url}"));
        WebviewWindowBuilder::new(app, "chat", WebviewUrl::App(url.into()))
            .title("Shinsekai Chat")
            .inner_size(1280.0, 820.0)
            .min_inner_size(960.0, 620.0)
            .resizable(true)
            .transparent(true)
            .decorations(false)
            .always_on_top(true)
            // Keep the chat window in the taskbar so it can be restored after
            // minimizing (a frameless + skip_taskbar window vanishes with no way back).
            // Disable Tauri's native drag-drop handler so HTML5 file drops reach the
            // webview (InputLayer relies on the DOM `drop` event for attachments).
            .disable_drag_drop_handler()
            .shadow(false)
            .center()
            .build()
            .map_err(|error| error.to_string())?
    };

    #[cfg(not(target_os = "windows"))]
    if open_plan.navigate_after_create {
        crate::frontend_protocol::navigate_chat_window_to_live_frontend(
            app,
            bridge_port,
            auth_token,
        )?;
    }
    let _ = chat_window.show();
    let _ = chat_window.unminimize();

    if open_plan.focus_after_show {
        let _ = chat_window.set_focus();
    } else {
        restart_debug_log("desktop_open_chat_window windows focus skipped");
    }

    Ok(())
}

fn current_chat_window_open_plan() -> ChatWindowOpenPlan {
    chat_window_open_plan_for_windows(cfg!(target_os = "windows"))
}

pub(crate) fn chat_window_open_plan_for_windows(is_windows: bool) -> ChatWindowOpenPlan {
    if is_windows {
        ChatWindowOpenPlan {
            defer_command: true,
            focus_after_show: false,
            navigate_after_create: false,
        }
    } else {
        ChatWindowOpenPlan {
            defer_command: false,
            focus_after_show: true,
            navigate_after_create: true,
        }
    }
}

#[tauri::command]
pub(crate) fn desktop_open_external_url(url: String) -> Result<(), String> {
    let url = url.trim();
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err("only http(s) URLs can be opened externally".to_string());
    }
    open_external_url(url)
}

#[cfg(target_os = "macos")]
fn open_external_url(url: &str) -> Result<(), String> {
    Command::new("open")
        .arg(url)
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[cfg(target_os = "windows")]
fn open_external_url(url: &str) -> Result<(), String> {
    let mut command = Command::new("rundll32");
    command.args(["url.dll,FileProtocolHandler", url]);
    command.creation_flags(0x0800_0000);
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
fn open_external_url(url: &str) -> Result<(), String> {
    Command::new("xdg-open")
        .arg(url)
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}
