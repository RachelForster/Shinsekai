use std::path::Path;

use tauri::{AppHandle, Emitter, Manager, State};

use crate::{
    bridge::start_bridge_for_state,
    frontend_protocol::navigate_main_window_to_live_frontend,
    runtime,
    state::{
        restart_debug_log, DesktopRuntimePhase, DesktopRuntimeProgress, DesktopRuntimeView,
        DesktopState,
    },
};

const BRIDGE_RESTART_STATE_EVENT: &str = "shinsekai:bridge-restart-state";
const RUNTIME_PROGRESS_EVENT: &str = "shinsekai:runtime-progress";

pub(crate) fn should_bootstrap_runtime(project_root_requires_selection: bool) -> bool {
    !project_root_requires_selection
}

pub(crate) fn project_root_setup_log_event(project_root_requires_selection: bool) -> &'static str {
    if project_root_requires_selection {
        "setup awaiting project-root selection"
    } else {
        "setup resolved"
    }
}

#[tauri::command]
pub(crate) fn desktop_runtime_state(state: State<'_, DesktopState>) -> DesktopRuntimeView {
    state.runtime_view()
}

async fn run_runtime_blocking<T, F>(
    label: &'static str,
    app: AppHandle,
    task: F,
) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce(&AppHandle, &DesktopState) -> Result<T, String> + Send + 'static,
{
    restart_debug_log(format!("{label} command received"));
    let join = tauri::async_runtime::spawn_blocking(move || {
        restart_debug_log(format!("{label} background start"));
        let state = app.state::<DesktopState>();
        let result = task(&app, state.inner());
        match &result {
            Ok(_) => restart_debug_log(format!("{label} background completed")),
            Err(error) => restart_debug_log(format!("{label} background failed error={error}")),
        }
        result
    });
    match join.await {
        Ok(result) => result,
        Err(error) => Err(format!("{label} background task failed: {error}")),
    }
}

pub(crate) fn phase_after_runtime_scan(
    has_bridge: bool,
    view: runtime::RuntimeScanView,
) -> DesktopRuntimePhase {
    if has_bridge && view.selected_candidate_id.is_some() {
        DesktopRuntimePhase::Ready { view: Some(view) }
    } else {
        DesktopRuntimePhase::NeedsAction { view }
    }
}

#[tauri::command]
pub(crate) async fn desktop_runtime_repair(
    app: AppHandle,
    candidate_id: String,
    action: runtime::RuntimeRepairActionKind,
) -> Result<DesktopRuntimeView, String> {
    run_runtime_blocking("desktop_runtime_repair", app, move |app, state| {
        desktop_runtime_repair_blocking(app, state, candidate_id, action)
    })
    .await
}

fn desktop_runtime_repair_blocking(
    app: &AppHandle,
    state: &DesktopState,
    candidate_id: String,
    action: runtime::RuntimeRepairActionKind,
) -> Result<DesktopRuntimeView, String> {
    emit_runtime_progress(
        app,
        "installingDeps",
        Some(candidate_id.clone()),
        None,
        Some("Repairing runtime candidate"),
    );
    restart_debug_log(format!(
        "desktop_runtime_repair action={action:?} candidate_id={candidate_id}"
    ));
    let scan = runtime::scan_runtime_view(app, &state.source_root);
    state.set_runtime(DesktopRuntimePhase::Updating { view: Some(scan) });
    let dependency_install_attempted =
        action == runtime::RuntimeRepairActionKind::InstallRuntimeDeps;
    let repaired_path =
        runtime::repair_runtime_candidate(app, &state.source_root, &candidate_id, action).map_err(
            |error| {
                set_runtime_error_state(app, state, error.to_string(), dependency_install_attempted)
            },
        )?;
    emit_runtime_progress(
        app,
        "checkingBridge",
        Some(candidate_id),
        None,
        Some("Checking repaired runtime"),
    );
    start_repaired_runtime_for_state(
        app,
        state,
        repaired_path.as_deref(),
        dependency_install_attempted,
    )
}

#[tauri::command]
pub(crate) async fn desktop_runtime_install_profile(
    app: AppHandle,
    profile: String,
) -> Result<DesktopRuntimeView, String> {
    run_runtime_blocking("desktop_runtime_install_profile", app, move |app, state| {
        desktop_runtime_install_profile_blocking(app, state, profile)
    })
    .await
}

fn desktop_runtime_install_profile_blocking(
    app: &AppHandle,
    state: &DesktopState,
    profile: String,
) -> Result<DesktopRuntimeView, String> {
    let profile = profile.trim().to_string();
    restart_debug_log(format!("desktop_runtime_install_profile profile={profile}"));
    emit_runtime_progress(
        app,
        "installingDeps",
        Some(profile.clone()),
        None,
        Some("Installing optional runtime dependencies"),
    );
    let scan = runtime::scan_runtime_view(app, &state.source_root);
    state.set_runtime(DesktopRuntimePhase::Updating { view: Some(scan) });
    let Some(candidate_id) = state.bridge_candidate_id() else {
        let message =
            "Shinsekai managed Python runtime must be running before installing optional runtime dependencies"
                .to_string();
        restart_debug_log(format!(
            "desktop_runtime_install_profile skipped profile={profile} message={message}"
        ));
        state.set_runtime(phase_after_runtime_scan(
            state.has_bridge(),
            runtime::scan_runtime_view(app, &state.source_root),
        ));
        return Err(message);
    };
    match runtime::install_runtime_profile(app, &state.source_root, &profile, Some(&candidate_id)) {
        Ok(python) => {
            restart_debug_log(format!(
                "desktop_runtime_install_profile ready profile={profile} candidate_id={candidate_id} python={}",
                python.display()
            ));
            let view = runtime::scan_runtime_view(app, &state.source_root);
            state.set_runtime(phase_after_runtime_scan(state.has_bridge(), view));
            Ok(state.runtime_view())
        }
        Err(error) => {
            let message = error.to_string();
            restart_debug_log(format!(
                "desktop_runtime_install_profile failed profile={profile} message={message}"
            ));
            let view = runtime::scan_runtime_view(app, &state.source_root);
            state.set_runtime(phase_after_runtime_scan(state.has_bridge(), view));
            Err(message)
        }
    }
}

fn emit_runtime_progress(
    app: &AppHandle,
    phase: &'static str,
    candidate_id: Option<String>,
    source: Option<String>,
    message: Option<&str>,
) {
    let _ = app.emit(
        RUNTIME_PROGRESS_EVENT,
        DesktopRuntimeProgress {
            phase,
            candidate_id,
            source,
            downloaded: None,
            total: None,
            speed_bytes_per_sec: None,
            message: message.map(ToString::to_string),
        },
    );
}

fn emit_bridge_restart_state(app: &AppHandle, restarting: bool) {
    let _ = app.emit(BRIDGE_RESTART_STATE_EVENT, restarting);
}

#[tauri::command]
pub(crate) async fn desktop_bridge_restart(app: AppHandle) -> Result<DesktopRuntimeView, String> {
    emit_bridge_restart_state(&app, true);
    let result = run_runtime_blocking("desktop_bridge_restart", app.clone(), |app, state| {
        restart_bridge_for_state(app, state)
    })
    .await;
    emit_bridge_restart_state(&app, false);
    result
}

fn restart_bridge_for_state(
    app: &AppHandle,
    state: &DesktopState,
) -> Result<DesktopRuntimeView, String> {
    state.set_runtime(DesktopRuntimePhase::Checking { view: None });
    if let Some(bridge) = state.take_bridge() {
        restart_debug_log("desktop_bridge_restart stopping existing bridge");
        bridge.stop();
    } else {
        restart_debug_log("desktop_bridge_restart no existing bridge to stop");
    }

    start_runtime_candidate_for_state(app, state, None)
}

fn start_runtime_candidate_for_state(
    app: &AppHandle,
    state: &DesktopState,
    candidate_id: Option<&str>,
) -> Result<DesktopRuntimeView, String> {
    restart_debug_log(format!(
        "start_runtime_candidate begin candidate_id={}",
        candidate_id.unwrap_or("")
    ));
    if candidate_id.is_some_and(|id| id != runtime::INSTALL_DIR_RUNTIME_ID) {
        return Err(set_runtime_error_state(
            app,
            state,
            "Shinsekai only starts the managed Python runtime under runtime/.".to_string(),
            false,
        ));
    }
    let scan = runtime::scan_runtime_view(app, &state.source_root);
    restart_debug_log(format!(
        "start_runtime_candidate validated runtime candidates={} selected={:?}",
        scan.candidates.len(),
        scan.selected_candidate_id
    ));
    emit_runtime_progress(
        app,
        "probing",
        candidate_id.map(ToString::to_string),
        None,
        Some("Selecting runtime candidate"),
    );
    state.set_runtime(DesktopRuntimePhase::Checking {
        view: Some(scan.clone()),
    });
    if let Some(bridge) = state.take_bridge() {
        restart_debug_log("start_runtime_candidate stopping existing bridge");
        bridge.stop();
    }

    if scan.selected_candidate_id.is_none() {
        let message = scan
            .message
            .clone()
            .unwrap_or_else(|| "Shinsekai managed Python runtime is not ready.".to_string());
        state.set_runtime(DesktopRuntimePhase::NeedsAction { view: scan });
        return Err(message);
    }

    let result = runtime::find_install_dir_python_runtime(&state.source_root)
        .map_err(|error| error.to_string())
        .and_then(|runtime| {
            restart_debug_log(format!(
                "start_runtime_candidate launching bridge runtime={} candidate_id={}",
                runtime.description,
                runtime.candidate_id.as_deref().unwrap_or("")
            ));
            start_bridge_for_state(state, runtime).map_err(|error| error.to_string())
        });

    match result {
        Ok(()) => {
            let view = runtime::install_dir_runtime_view(&state.source_root);
            restart_debug_log("start_runtime_candidate ready");
            emit_runtime_progress(app, "ready", None, None, Some("Runtime is ready"));
            state.set_runtime(DesktopRuntimePhase::Ready { view: Some(view) });
            Ok(state.runtime_view())
        }
        Err(message) => {
            let view = runtime::scan_runtime_view(app, &state.source_root);
            restart_debug_log(format!("start_runtime_candidate failed message={message}"));
            state.set_runtime(DesktopRuntimePhase::Error {
                message: message.clone(),
                view: Some(view),
                dependency_install_failed: false,
            });
            Err(message)
        }
    }
}

fn start_repaired_runtime_for_state(
    app: &AppHandle,
    state: &DesktopState,
    repaired_path: Option<&Path>,
    dependency_install_attempted: bool,
) -> Result<DesktopRuntimeView, String> {
    let repaired_candidate_id = repaired_path
        .and_then(|path| runtime::ready_candidate_id_for_path(app, &state.source_root, path));
    if repaired_path.is_some() && repaired_candidate_id.is_none() {
        return Err(set_runtime_error_state(
            app,
            state,
            "repaired runtime did not produce a ready candidate".to_string(),
            dependency_install_attempted,
        ));
    }
    match start_runtime_candidate_for_state(app, state, repaired_candidate_id.as_deref()) {
        Err(message) if dependency_install_attempted => {
            Err(set_runtime_error_state(app, state, message, true))
        }
        result => result,
    }
}

fn set_runtime_error_state(
    app: &AppHandle,
    state: &DesktopState,
    message: String,
    dependency_install_failed: bool,
) -> String {
    let view = runtime::scan_runtime_view(app, &state.source_root);
    state.set_runtime(DesktopRuntimePhase::Error {
        message: message.clone(),
        view: Some(view),
        dependency_install_failed,
    });
    message
}

pub(crate) fn bootstrap_runtime(app: AppHandle) {
    restart_debug_log("bootstrap_runtime start");
    let state = app.state::<DesktopState>();
    restart_debug_log("bootstrap_runtime starting fixed managed runtime");
    match start_runtime_candidate_for_state(&app, &state, None) {
        Ok(_) => {
            restart_debug_log("bootstrap_runtime ready");
            if let Err(error) = navigate_main_window_to_live_frontend(
                &app,
                state.bridge_port,
                &state.bridge_auth_token,
            ) {
                restart_debug_log(format!(
                    "bootstrap_runtime frontend navigate failed error={error}"
                ));
            }
        }
        Err(message) => {
            restart_debug_log(format!("bootstrap_runtime missing/error message={message}"));
        }
    }
}
