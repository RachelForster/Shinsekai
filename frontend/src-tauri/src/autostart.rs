//! Use the OS login registration as the source of truth, without a second preference.
use tauri::{AppHandle, WebviewWindow};
use tauri_plugin_autostart::ManagerExt;

fn require_main(window: &WebviewWindow) -> Result<(), String> {
    if window.label() == "main" {
        Ok(())
    } else {
        Err("Autostart settings are only available in the main window".into())
    }
}

#[tauri::command]
pub fn desktop_autostart_get(window: WebviewWindow, app: AppHandle) -> Result<bool, String> {
    require_main(&window)?;
    app.autolaunch().is_enabled().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn desktop_autostart_set(
    window: WebviewWindow,
    app: AppHandle,
    enabled: bool,
) -> Result<bool, String> {
    require_main(&window)?;
    let manager = app.autolaunch();
    if enabled {
        manager.enable()
    } else {
        manager.disable()
    }
    .map_err(|e| e.to_string())?;
    manager.is_enabled().map_err(|e| e.to_string())
}
