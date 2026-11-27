use std::{
    env,
    path::PathBuf,
    sync::{Arc, Mutex},
    thread,
};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};

mod atomic_file;
mod autostart;
mod background;
mod bridge;
mod bridge_restart;
mod desktop_files;
mod frontend_protocol;
mod paths;
mod process_guard;
mod project_root;
mod reminders;
mod runtime;
mod runtime_commands;
mod state;
#[cfg(test)]
mod tests;
#[cfg(desktop)]
mod updater;
mod window_controls;

pub(crate) use bridge::shutdown_desktop_app;
pub(crate) use frontend_protocol::app_window_url_for_route;
pub(crate) use state::{restart_debug_log, show_backend_console, DesktopResult, DesktopState};

use bridge::{choose_bridge_port, request_bridge_chat_close};
use frontend_protocol::{
    app_window_url, serve_live_frontend_protocol, LIVE_FRONTEND_SCHEME,
};
use paths::{
    resolve_app_root, resolve_frontend_dist, resolve_project_root, resolve_source_root,
};
use runtime_commands::{
    bootstrap_runtime, project_root_setup_log_event, should_bootstrap_runtime,
};
use state::{generate_bridge_auth_token, plugin_chat_wake_argument, PluginChatWake};
use window_controls::schedule_mini_input_global_shortcut_sync;

pub(crate) const MAIN_WINDOW_DEFAULT_WIDTH: f64 = 1416.0;
pub(crate) const MAIN_WINDOW_DEFAULT_HEIGHT: f64 = 936.0;
pub(crate) const MAIN_WINDOW_MIN_WIDTH: f64 = 860.0;
pub(crate) const MAIN_WINDOW_MIN_HEIGHT: f64 = 620.0;
const MAIN_WINDOW_WORK_AREA_RATIO: f64 = 0.96;

pub(crate) fn resolve_main_window_initial_size(
    work_area_logical: Option<(f64, f64)>,
) -> (f64, f64) {
    let Some((area_width, area_height)) = work_area_logical else {
        return (MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT);
    };
    if !area_width.is_finite()
        || !area_height.is_finite()
        || area_width <= 0.0
        || area_height <= 0.0
    {
        return (MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT);
    }
    let scale = (area_width * MAIN_WINDOW_WORK_AREA_RATIO / MAIN_WINDOW_DEFAULT_WIDTH)
        .min(area_height * MAIN_WINDOW_WORK_AREA_RATIO / MAIN_WINDOW_DEFAULT_HEIGHT)
        .min(1.0);
    (
        (MAIN_WINDOW_DEFAULT_WIDTH * scale)
            .round()
            .max(MAIN_WINDOW_MIN_WIDTH),
        (MAIN_WINDOW_DEFAULT_HEIGHT * scale)
            .round()
            .max(MAIN_WINDOW_MIN_HEIGHT),
    )
}

pub fn run() {
    restart_debug_log("run enter");
    let protocol_frontend_dist = Arc::new(Mutex::new(None::<PathBuf>));
    let protocol_frontend_dist_for_handler = Arc::clone(&protocol_frontend_dist);
    tauri::Builder::default()
        .manage(PluginChatWake(Mutex::new(plugin_chat_wake_argument(
            env::args().skip(1),
        ))))
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            if let Some(request) = plugin_chat_wake_argument(args.into_iter().skip(1)) {
                if let Ok(mut pending) = app.state::<PluginChatWake>().0.lock() {
                    *pending = Some(request);
                }
            }
            background::show_main(app)
        }))
        .register_uri_scheme_protocol(LIVE_FRONTEND_SCHEME, move |_ctx, request| {
            serve_live_frontend_protocol(&protocol_frontend_dist_for_handler, request.uri().path())
        })
        .invoke_handler(tauri::generate_handler![
            background::desktop_background_get,
            background::desktop_background_save,
            autostart::desktop_autostart_get,
            autostart::desktop_autostart_set,
            background::desktop_window_close_status,
            background::desktop_window_resolve_close,
            reminders::desktop_reminders_inbox,
            reminders::desktop_reminders_visible,
            reminders::desktop_reminders_dismiss,
            reminders::desktop_reminders_window,
            reminders::desktop_reminders_list,
            reminders::desktop_reminders_cancel,
            reminders::desktop_reminders_update,
            reminders::desktop_reminders_delete,
            reminders::desktop_reminders_view,
            runtime_commands::desktop_runtime_state,
            runtime_commands::desktop_runtime_repair,
            runtime_commands::desktop_runtime_install_profile,
            state::desktop_project_root_status,
            state::desktop_project_root_select,
            state::desktop_files_browse,
            desktop_files::desktop_files_save_history_export,
            state::desktop_restart_debug_log,
            bridge::desktop_app_restart,
            runtime_commands::desktop_bridge_restart,
            frontend_protocol::desktop_frontend_reload,
            window_controls::desktop_window_hide,
            window_controls::desktop_chat_window_destroy,
            window_controls::desktop_window_minimize,
            window_controls::desktop_window_set_always_on_top,
            window_controls::desktop_window_toggle_maximize,
            window_controls::desktop_window_start_drag,
            window_controls::desktop_window_start_resize,
            window_controls::desktop_window_set_ignore_cursor_events,
            window_controls::desktop_window_cursor_position,
            window_controls::desktop_chat_window_set_mini_mode,
            window_controls::desktop_chat_window_set_mini_input_shortcut,
            window_controls::desktop_chat_window_sync_mini_layout,
            window_controls::desktop_window_close,
            window_controls::desktop_open_chat_window,
            state::desktop_take_plugin_chat_wake,
            window_controls::desktop_open_external_url,
            #[cfg(desktop)]
            updater::desktop_update_check,
            #[cfg(desktop)]
            updater::desktop_update_install
        ])
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::Resized(_)) && window.label() == "main" {
                if let Some(background) = window
                    .app_handle()
                    .try_state::<background::BackgroundState>()
                {
                    if background.minimize_to_tray() && window.is_minimized().unwrap_or(false) {
                        let _ = window.hide();
                    }
                }
            }
            if let WindowEvent::CloseRequested { api, .. } = event {
                match window.label() {
                    "main" => {
                        api.prevent_close();
                        let app = window.app_handle().clone();
                        if let Err(error) = background::request_main_close(&app) {
                            restart_debug_log(format!("main close request failed: {error}"));
                        }
                    }
                    "chat" => {
                        api.prevent_close();
                        let app = window.app_handle().clone();
                        let state = app.state::<DesktopState>();
                        state.reset_chat_window_session_bounds();
                        schedule_mini_input_global_shortcut_sync(&app);
                        request_bridge_chat_close(
                            state.inner(),
                            "chat window close requested",
                        );
                        let _ = window.destroy();
                    }
                    _ => {}
                }
            }
        })
        .setup(move |app| {
            #[cfg(desktop)]
            {
                app.handle()
                    .plugin(tauri_plugin_updater::Builder::new().build())?;
                app.manage(updater::DesktopUpdateState::new());
                if let Err(error) = app
                    .handle()
                    .plugin(tauri_plugin_global_shortcut::Builder::new().build())
                {
                    restart_debug_log(format!("global shortcut plugin setup failed: {error}"));
                }
            }
            app.handle().plugin(tauri_plugin_dialog::init())?;
            app.handle().plugin(tauri_plugin_notification::init())?;
            app.handle().plugin(tauri_plugin_autostart::Builder::new().build())?;

            let source_root = resolve_source_root(app)?;
            let app_root = resolve_app_root(app, &source_root)?;
            let project_root::ResolvedProjectRoot {
                path: project_root,
                controller: project_root_controller,
            } = resolve_project_root(app, &source_root, &app_root)?;
            let project_root_requires_selection = project_root_controller
                .status()
                .requires_selection;
            let frontend_dist = resolve_frontend_dist(&source_root)?;
            let bridge_port = choose_bridge_port()?;
            let bridge_auth_token = generate_bridge_auth_token()?;
            let url = app_window_url(bridge_port, &bridge_auth_token);
            restart_debug_log(format!(
                "{} source_root={} project_root={} app_root={} frontend_dist={} bridge_port={} url={}",
                project_root_setup_log_event(project_root_requires_selection),
                source_root.display(),
                project_root.display(),
                app_root.display(),
                frontend_dist.display(),
                bridge_port,
                url
            ));
            if let Ok(mut dist) = protocol_frontend_dist.lock() {
                *dist = Some(frontend_dist.clone());
            }
            app.manage(DesktopState::new(
                source_root,
                project_root,
                project_root_controller,
                app_root,
                frontend_dist,
                bridge_port,
                bridge_auth_token,
            ));

            let primary_work_area = app.primary_monitor().ok().flatten().and_then(|monitor| {
                let scale = monitor.scale_factor();
                if scale.is_finite() && scale > 0.0 {
                    let area = monitor.work_area();
                    Some((
                        f64::from(area.size.width) / scale,
                        f64::from(area.size.height) / scale,
                    ))
                } else {
                    None
                }
            });
            let (initial_width, initial_height) =
                resolve_main_window_initial_size(primary_work_area);

            WebviewWindowBuilder::new(app, "main", WebviewUrl::App(url.into()))
                .title("Shinsekai")
                .inner_size(initial_width, initial_height)
                .min_inner_size(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
                .decorations(false)
                .shadow(true)
                .center()
                .build()?;

            if let Err(error) = reminders::setup(app.handle()) {
                restart_debug_log(format!("reminder panel setup failed: {error}"));
            }
            background::setup(app.handle())?;

            if should_bootstrap_runtime(project_root_requires_selection) {
                let app_handle = app.handle().clone();
                thread::spawn(move || bootstrap_runtime(app_handle));
                restart_debug_log("setup complete; runtime bootstrap spawned");
            } else {
                restart_debug_log(
                    "setup complete; runtime bootstrap deferred for project-root selection",
                );
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Shinsekai desktop shell");
}
