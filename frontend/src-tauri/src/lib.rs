use std::{
    env,
    error::Error,
    ffi::OsString,
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Component, Path, PathBuf},
    process::{Child, Command},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use desktop_files::{browse_desktop_files, DesktopFileBrowserSnapshot};
use serde::Serialize;
use tauri::{
    http::{header, Response, StatusCode},
    AppHandle, Emitter, Manager, State, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
    Window, WindowEvent,
};
#[cfg(desktop)]
use tauri_plugin_updater::{Update, UpdaterExt};
use tauri_runtime::ResizeDirection;

#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

mod desktop_files;
mod runtime;

type DesktopResult<T> = Result<T, Box<dyn Error>>;

const BRIDGE_HOST: &str = "127.0.0.1";
const DEFAULT_BRIDGE_PORT: u16 = 8787;
const RESTART_DEBUG_LOG_FILE: &str = "shinsekai-restart-debug.log";
const LIVE_FRONTEND_SCHEME: &str = "shinsekai";
const FRONTEND_DIST_MARKER: &str = ".dist-current";
const FRONTEND_DIST_RELEASES: &str = ".dist-releases";
#[cfg(desktop)]
const UPDATE_PROGRESS_EVENT: &str = "shinsekai:update-progress";
const BRIDGE_RESTART_STATE_EVENT: &str = "shinsekai:bridge-restart-state";
const RUNTIME_PROGRESS_EVENT: &str = "shinsekai:runtime-progress";
const BRIDGE_STOP_TIMEOUT: Duration = Duration::from_secs(5);
const BRIDGE_CHAT_CLOSE_TIMEOUT: Duration = Duration::from_secs(3);

#[cfg(unix)]
unsafe extern "C" {
    fn setsid() -> i32;
}

struct BridgeProcess {
    child: Mutex<Option<Child>>,
    candidate_id: Option<String>,
}

impl BridgeProcess {
    fn new(child: Child, candidate_id: Option<String>) -> Self {
        Self {
            child: Mutex::new(Some(child)),
            candidate_id,
        }
    }

    fn stop(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut child) = child.take() {
                restart_debug_log(format!("bridge stop requested child_pid={}", child.id()));
                match child.try_wait() {
                    Ok(Some(status)) => {
                        restart_debug_log(format!(
                            "bridge stop skipped; child already exited status={status}"
                        ));
                        return;
                    }
                    Ok(None) => {}
                    Err(error) => {
                        restart_debug_log(format!(
                            "bridge stop initial status failed error={error}"
                        ));
                    }
                }
                if let Err(error) = child.kill() {
                    restart_debug_log(format!("bridge stop kill failed error={error}"));
                }
                let started = Instant::now();
                loop {
                    match child.try_wait() {
                        Ok(Some(status)) => {
                            restart_debug_log(format!("bridge stop completed status={status}"));
                            break;
                        }
                        Ok(None) if started.elapsed() < BRIDGE_STOP_TIMEOUT => {
                            thread::sleep(Duration::from_millis(50));
                        }
                        Ok(None) => {
                            restart_debug_log(format!(
                                "bridge stop timed out child_pid={} elapsed_ms={}",
                                child.id(),
                                started.elapsed().as_millis()
                            ));
                            break;
                        }
                        Err(error) => {
                            restart_debug_log(format!("bridge stop wait failed error={error}"));
                            break;
                        }
                    }
                }
            }
        }
    }
}

impl Drop for BridgeProcess {
    fn drop(&mut self) {
        self.stop();
    }
}

struct BridgeLaunch {
    child: Child,
}

#[derive(Clone)]
enum DesktopRuntimePhase {
    Checking {
        view: Option<runtime::RuntimeScanView>,
    },
    NeedsAction {
        view: runtime::RuntimeScanView,
    },
    Updating {
        view: Option<runtime::RuntimeScanView>,
    },
    Ready {
        view: Option<runtime::RuntimeScanView>,
    },
    Error {
        message: String,
        view: Option<runtime::RuntimeScanView>,
    },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntimeView {
    status: &'static str,
    message: Option<String>,
    bridge_url: String,
    selected_candidate_id: Option<String>,
    recommended_action: Option<runtime::RuntimeRepairActionKind>,
    candidates: Vec<runtime::RuntimeCandidateView>,
}

struct DesktopState {
    source_root: PathBuf,
    project_root: PathBuf,
    app_root: PathBuf,
    frontend_dist: PathBuf,
    bridge_port: u16,
    bridge_auth_token: String,
    bridge: Mutex<Option<BridgeProcess>>,
    runtime: Mutex<DesktopRuntimePhase>,
}

#[cfg(desktop)]
struct DesktopUpdateState {
    pending: Mutex<Option<Update>>,
}

#[cfg(desktop)]
impl DesktopUpdateState {
    fn new() -> Self {
        Self {
            pending: Mutex::new(None),
        }
    }
}

impl DesktopState {
    fn new(
        source_root: PathBuf,
        project_root: PathBuf,
        app_root: PathBuf,
        frontend_dist: PathBuf,
        bridge_port: u16,
        bridge_auth_token: String,
    ) -> Self {
        Self {
            source_root,
            project_root,
            app_root,
            frontend_dist,
            bridge_port,
            bridge_auth_token,
            bridge: Mutex::new(None),
            runtime: Mutex::new(DesktopRuntimePhase::Checking { view: None }),
        }
    }

    fn bridge_url(&self) -> String {
        format!("http://{BRIDGE_HOST}:{}", self.bridge_port)
    }

    fn set_runtime(&self, phase: DesktopRuntimePhase) {
        if let Ok(mut runtime) = self.runtime.lock() {
            *runtime = phase;
        }
    }

    fn take_bridge(&self) -> Option<BridgeProcess> {
        self.bridge.lock().ok()?.take()
    }

    fn has_bridge(&self) -> bool {
        self.bridge
            .lock()
            .map(|bridge| bridge.is_some())
            .unwrap_or(false)
    }

    fn bridge_candidate_id(&self) -> Option<String> {
        self.bridge
            .lock()
            .ok()?
            .as_ref()
            .and_then(|bridge| bridge.candidate_id.clone())
    }

    fn runtime_view(&self) -> DesktopRuntimeView {
        let phase = self
            .runtime
            .lock()
            .map(|runtime| runtime.clone())
            .unwrap_or_else(|_| DesktopRuntimePhase::Error {
                message: "runtime state lock is poisoned".to_string(),
                view: None,
            });
        let (status, message, scan_view) = match phase {
            DesktopRuntimePhase::Checking { view } => ("checking", None, view),
            DesktopRuntimePhase::NeedsAction { view } => {
                ("needsAction", view.message.clone(), Some(view))
            }
            DesktopRuntimePhase::Updating { view } => ("updating", None, view),
            DesktopRuntimePhase::Ready { view } => ("ready", None, view),
            DesktopRuntimePhase::Error { message, view } => ("error", Some(message), view),
        };
        let scanned_selected_candidate_id = scan_view
            .as_ref()
            .and_then(|view| view.selected_candidate_id.clone());
        let recommended_action = scan_view.as_ref().and_then(|view| view.recommended_action);
        let mut candidates = scan_view
            .map(|view| view.candidates)
            .unwrap_or_else(Vec::new);
        let bridge_candidate_id = self.bridge_candidate_id();
        let selected_candidate_id = bridge_candidate_id
            .filter(|id| candidates.iter().any(|candidate| candidate.id == *id))
            .or(scanned_selected_candidate_id);
        for candidate in &mut candidates {
            candidate.selected = Some(&candidate.id) == selected_candidate_id.as_ref();
        }
        DesktopRuntimeView {
            status,
            message,
            bridge_url: self.bridge_url(),
            selected_candidate_id,
            recommended_action,
            candidates,
        }
    }
}

#[cfg(desktop)]
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopUpdate {
    version: String,
    date: Option<String>,
    body: Option<String>,
}

#[cfg(desktop)]
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopUpdateProgress {
    event: &'static str,
    downloaded: u64,
    content_length: Option<u64>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntimeProgress {
    phase: &'static str,
    candidate_id: Option<String>,
    source: Option<String>,
    downloaded: Option<u64>,
    total: Option<u64>,
    speed_bytes_per_sec: Option<f64>,
    message: Option<String>,
}

#[cfg(desktop)]
#[derive(Default)]
struct DesktopUpdateDownloadProgress {
    downloaded: u64,
    content_length: Option<u64>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopWindowCursorPosition {
    x: f64,
    y: f64,
}

pub fn run() {
    restart_debug_log("run enter");
    let protocol_frontend_dist = Arc::new(Mutex::new(None::<PathBuf>));
    let protocol_frontend_dist_for_handler = Arc::clone(&protocol_frontend_dist);
    tauri::Builder::default()
        .register_uri_scheme_protocol(LIVE_FRONTEND_SCHEME, move |_ctx, request| {
            serve_live_frontend_protocol(&protocol_frontend_dist_for_handler, request.uri().path())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_runtime_state,
            desktop_runtime_repair,
            desktop_runtime_install_profile,
            desktop_files_browse,
            desktop_restart_debug_log,
            desktop_app_restart,
            desktop_bridge_restart,
            desktop_frontend_reload,
            desktop_window_minimize,
            desktop_window_toggle_maximize,
            desktop_window_start_drag,
            desktop_window_start_resize,
            desktop_window_set_ignore_cursor_events,
            desktop_window_cursor_position,
            desktop_window_close,
            desktop_open_chat_window,
            desktop_open_external_url,
            #[cfg(desktop)]
            desktop_update_check,
            #[cfg(desktop)]
            desktop_update_install
        ])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                match window.label() {
                    "main" => {
                        api.prevent_close();
                        let app = window.app_handle().clone();
                        let state = app.state::<DesktopState>();
                        shutdown_desktop_app(&app, state.inner(), "main window close requested");
                    }
                    "chat" => {
                        api.prevent_close();
                        let app = window.app_handle().clone();
                        let state = app.state::<DesktopState>();
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
                app.manage(DesktopUpdateState::new());
            }

            let source_root = resolve_source_root(app)?;
            let app_root = resolve_app_root(app, &source_root)?;
            let project_root = resolve_project_root(app, &app_root)?;
            let frontend_dist = resolve_frontend_dist(&source_root)?;
            let bridge_port = choose_bridge_port()?;
            let bridge_auth_token = generate_bridge_auth_token()?;
            let url = app_window_url(bridge_port, &bridge_auth_token);
            restart_debug_log(format!(
                "setup resolved source_root={} project_root={} app_root={} frontend_dist={} bridge_port={} url={}",
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
                app_root,
                frontend_dist,
                bridge_port,
                bridge_auth_token,
            ));

            WebviewWindowBuilder::new(app, "main", WebviewUrl::App(url.into()))
                .title("Shinsekai")
                .inner_size(1180.0, 780.0)
                .min_inner_size(860.0, 620.0)
                .decorations(false)
                .shadow(true)
                .center()
                .build()?;

            let app_handle = app.handle().clone();
            thread::spawn(move || bootstrap_runtime(app_handle));
            restart_debug_log("setup complete; runtime bootstrap spawned");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Shinsekai desktop shell");
}

fn restart_debug_log_path() -> PathBuf {
    env::var_os("SHINSEKAI_RESTART_LOG")
        .map(PathBuf::from)
        .unwrap_or_else(|| env::temp_dir().join(RESTART_DEBUG_LOG_FILE))
}

fn restart_debug_log(message: impl AsRef<str>) {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| format!("{}.{:03}", duration.as_secs(), duration.subsec_millis()))
        .unwrap_or_else(|_| "time-error".to_string());
    let line = format!(
        "ts={} pid={} component=desktop {}\n",
        timestamp,
        std::process::id(),
        message.as_ref()
    );
    eprint!("[restart-debug] {}", line);
    if let Ok(mut file) = OpenOptions::new()
        .append(true)
        .create(true)
        .open(restart_debug_log_path())
    {
        let _ = file.write_all(line.as_bytes());
    }
}

fn bytes_to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 0x0f) as usize] as char);
    }
    result
}

fn generate_bridge_auth_token() -> DesktopResult<String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes)
        .map_err(|error| format!("failed to generate bridge auth token: {error}"))?;
    Ok(bytes_to_hex(&bytes))
}

#[tauri::command]
fn desktop_runtime_state(state: State<'_, DesktopState>) -> DesktopRuntimeView {
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

fn phase_after_runtime_scan(
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
async fn desktop_runtime_repair(
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
    let repaired_path =
        runtime::repair_runtime_candidate(app, &state.source_root, &candidate_id, action)
            .map_err(|error| set_runtime_error_state(app, state, error.to_string()))?;
    emit_runtime_progress(
        app,
        "checkingBridge",
        Some(candidate_id),
        None,
        Some("Checking repaired runtime"),
    );
    start_repaired_runtime_for_state(app, state, repaired_path.as_deref())
}

#[tauri::command]
async fn desktop_runtime_install_profile(
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

#[tauri::command]
fn desktop_restart_debug_log(message: String) {
    restart_debug_log(format!("frontend {}", message));
}

#[tauri::command]
fn desktop_files_browse(
    state: State<'_, DesktopState>,
    path: Option<String>,
    show_hidden: Option<bool>,
) -> Result<DesktopFileBrowserSnapshot, String> {
    browse_desktop_files(
        &state.project_root,
        &state.app_root,
        path.as_deref(),
        show_hidden.unwrap_or(false),
    )
    .map_err(|error| error.to_string())
}

#[cfg(desktop)]
#[tauri::command]
async fn desktop_update_check(
    app: AppHandle,
    update_state: State<'_, DesktopUpdateState>,
) -> Result<Option<DesktopUpdate>, String> {
    restart_debug_log("desktop_update_check command received");
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

#[cfg(desktop)]
#[tauri::command]
async fn desktop_update_install(
    app: AppHandle,
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

#[cfg(desktop)]
fn desktop_update_view(update: &Update) -> DesktopUpdate {
    DesktopUpdate {
        version: update.version.clone(),
        date: update.date.map(|date| date.to_string()),
        body: update.body.clone(),
    }
}

#[cfg(desktop)]
fn emit_update_progress(app: &AppHandle, payload: DesktopUpdateProgress) {
    let _ = app.emit(UPDATE_PROGRESS_EVENT, payload);
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

#[cfg(desktop)]
fn desktop_update_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[tauri::command]
fn desktop_app_restart(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
    restart_debug_log("desktop_app_restart command received");
    restart_desktop_app(&app, &state)
}

#[tauri::command]
async fn desktop_bridge_restart(app: AppHandle) -> Result<DesktopRuntimeView, String> {
    emit_bridge_restart_state(&app, true);
    let result = run_runtime_blocking("desktop_bridge_restart", app.clone(), |app, state| {
        restart_bridge_for_state(app, state)
    })
    .await;
    emit_bridge_restart_state(&app, false);
    result
}

#[tauri::command]
fn desktop_frontend_reload(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
    restart_debug_log("desktop_frontend_reload command received");
    reload_live_frontend_windows(&app, state.bridge_port, &state.bridge_auth_token)
}

fn restart_bridge_for_state(
    app: &AppHandle,
    state: &DesktopState,
) -> Result<DesktopRuntimeView, String> {
    state.set_runtime(DesktopRuntimePhase::Checking { view: None });
    request_bridge_chat_close(state, "desktop bridge restart");
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
        ));
    }
    let scan = runtime::install_dir_runtime_view(&state.source_root);
    restart_debug_log(format!(
        "start_runtime_candidate fixed runtime candidates={} selected={:?}",
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
    request_bridge_chat_close(state, "runtime candidate restart");
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
            });
            Err(message)
        }
    }
}

fn start_repaired_runtime_for_state(
    app: &AppHandle,
    state: &DesktopState,
    repaired_path: Option<&Path>,
) -> Result<DesktopRuntimeView, String> {
    let repaired_candidate_id = repaired_path
        .and_then(|path| runtime::ready_candidate_id_for_path(app, &state.source_root, path));
    if repaired_path.is_some() && repaired_candidate_id.is_none() {
        return Err(set_runtime_error_state(
            app,
            state,
            "repaired runtime did not produce a ready candidate".to_string(),
        ));
    }
    start_runtime_candidate_for_state(app, state, repaired_candidate_id.as_deref())
}

fn set_runtime_error_state(app: &AppHandle, state: &DesktopState, message: String) -> String {
    let view = runtime::scan_runtime_view(app, &state.source_root);
    state.set_runtime(DesktopRuntimePhase::Error {
        message: message.clone(),
        view: Some(view),
    });
    message
}

fn restart_desktop_app(app: &AppHandle, state: &DesktopState) -> Result<(), String> {
    let env = app.env();
    let exe = tauri::process::current_binary(&env).map_err(|error| error.to_string())?;
    let args = env.args_os.iter().skip(1).cloned().collect::<Vec<_>>();
    restart_debug_log(format!(
        "restart begin exe={} args_count={} bridge_port={}",
        exe.display(),
        args.len(),
        state.bridge_port
    ));
    spawn_delayed_restart(&exe, &args, std::process::id(), state.bridge_port)?;
    restart_debug_log("restart helper spawned; hiding and destroying main window");
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
        let _ = window.destroy();
    }
    request_bridge_chat_close(state, "desktop app restart");
    if let Some(bridge) = state.take_bridge() {
        restart_debug_log("restart stopping bridge before app exit");
        bridge.stop();
    }
    restart_debug_log("restart requested app.exit(0)");
    app.exit(0);
    Ok(())
}

fn shutdown_desktop_app(app: &AppHandle, state: &DesktopState, reason: &str) {
    restart_debug_log(format!("shutdown requested reason={reason}"));
    request_bridge_chat_close(state, reason);
    if let Some(bridge) = state.take_bridge() {
        restart_debug_log("shutdown stopping bridge");
        bridge.stop();
    } else {
        restart_debug_log("shutdown no bridge to stop");
    }
    restart_debug_log("shutdown requested app.exit(0)");
    app.exit(0);
}

fn request_bridge_chat_close(state: &DesktopState, reason: &str) {
    if !state.has_bridge() {
        restart_debug_log(format!(
            "request_bridge_chat_close skipped reason={reason} bridge_running=false"
        ));
        return;
    }
    match send_bridge_chat_close(state.bridge_port, &state.bridge_auth_token) {
        Ok(()) => restart_debug_log(format!(
            "request_bridge_chat_close dispatched reason={reason} port={}",
            state.bridge_port
        )),
        Err(error) => restart_debug_log(format!(
            "request_bridge_chat_close failed reason={reason} port={} error={error}",
            state.bridge_port
        )),
    }
}

fn send_bridge_chat_close(port: u16, auth_token: &str) -> Result<(), String> {
    let addr: SocketAddr = format!("{BRIDGE_HOST}:{port}")
        .parse::<SocketAddr>()
        .map_err(|error| error.to_string())?;
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(200))
        .map_err(|error| error.to_string())?;
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_read_timeout(Some(BRIDGE_CHAT_CLOSE_TIMEOUT));
    let request = format!(
        "POST /api/chat/close HTTP/1.1\r\nHost: {BRIDGE_HOST}\r\nContent-Type: application/json\r\nX-Shinsekai-Bridge-Token: {auth_token}\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    stream.flush().map_err(|error| error.to_string())?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    if response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200") {
        return Ok(());
    }
    if response.is_empty() {
        return Err("bridge closed connection before responding".to_string());
    }
    let status_line = response.lines().next().unwrap_or_default();
    Err(format!("unexpected bridge response: {status_line}"))
}

#[cfg(not(target_os = "windows"))]
fn spawn_delayed_restart(
    exe: &Path,
    args: &[OsString],
    pid: u32,
    _port: u16,
) -> Result<(), String> {
    let log_path = restart_debug_log_path();
    restart_debug_log(format!(
        "spawn_delayed_restart posix exe={} parent_pid={} port={} log={}",
        exe.display(),
        pid,
        _port,
        log_path.display()
    ));
    let mut command = Command::new("sh");
    command
        .arg("-c")
        .arg(
            r#"log="$3"; log_line() { printf 'ts=%s pid=%s component=restart-helper %s\n' "$(date +%s.%3N)" "$$" "$1" >> "$log"; }; log_line "waiting parent=$1 exe=$2"; while kill -0 "$1" 2>/dev/null; do sleep 0.1; done; log_line "parent exited; sleeping before relaunch"; sleep 0.8; exe="$2"; shift 3; log_line "launch exe=$exe cwd=$(pwd) args=$*"; "$exe" "$@" >> "$log" 2>&1 & child=$!; log_line "launched child_pid=$child"; sleep 0.2; if kill -0 "$child" 2>/dev/null; then log_line "relaunch child alive; helper exiting"; exit 0; fi; wait "$child"; status=$?; log_line "relaunch child exited early status=$status"; exit "$status""#,
        )
        .arg("shinsekai-restart")
        .arg(pid.to_string())
        .arg(exe)
        .arg(log_path)
        .args(args);
    #[cfg(unix)]
    unsafe {
        command.pre_exec(|| {
            if setsid() == -1 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(())
            }
        });
    }
    if let Ok(cwd) = env::current_dir() {
        command.current_dir(cwd);
    }
    match command.spawn() {
        Ok(child) => {
            restart_debug_log(format!(
                "spawn_delayed_restart posix spawned helper_pid={}",
                child.id()
            ));
            Ok(())
        }
        Err(error) => {
            restart_debug_log(format!("spawn_delayed_restart posix failed error={error}"));
            Err(error.to_string())
        }
    }
}

#[cfg(target_os = "windows")]
fn spawn_delayed_restart(
    exe: &Path,
    args: &[OsString],
    pid: u32,
    _port: u16,
) -> Result<(), String> {
    let log_path = restart_debug_log_path();
    restart_debug_log(format!(
        "spawn_delayed_restart windows exe={} parent_pid={} port={} log={}",
        exe.display(),
        pid,
        _port,
        log_path.display()
    ));
    let script = r#"
$parentProcessId = [int]$args[0]
$exe = $args[1]
$log = $args[2]
$argv = @()
function Write-RestartLog([string]$Message) {
  $ts = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
  Add-Content -Path $log -Value "ts=$ts pid=$PID component=restart-helper $Message"
}
Write-RestartLog "waiting parent=$parentProcessId exe=$exe"
if ($args.Length -gt 3) {
  $argv = $args[3..($args.Length - 1)]
}
try { Wait-Process -Id $parentProcessId -ErrorAction SilentlyContinue } catch {}
Write-RestartLog "parent exited; sleeping before relaunch"
Start-Sleep -Milliseconds 800
Write-RestartLog "start-process exe=$exe args=$($argv -join ' ')"
Start-Process -FilePath $exe -ArgumentList $argv
"#;
    let mut command = Command::new("powershell");
    command
        .arg("-NoProfile")
        .arg("-WindowStyle")
        .arg("Hidden")
        .arg("-Command")
        .arg(script)
        .arg(pid.to_string())
        .arg(exe)
        .arg(log_path)
        .args(args);
    command.creation_flags(0x0000_0008 | 0x0000_0200 | 0x0800_0000);
    if let Ok(cwd) = env::current_dir() {
        command.current_dir(cwd);
    }
    match command.spawn() {
        Ok(child) => {
            restart_debug_log(format!(
                "spawn_delayed_restart windows spawned helper_pid={}",
                child.id()
            ));
            Ok(())
        }
        Err(error) => {
            restart_debug_log(format!(
                "spawn_delayed_restart windows failed error={error}"
            ));
            Err(error.to_string())
        }
    }
}

#[tauri::command]
fn desktop_window_minimize(window: WebviewWindow) -> Result<(), String> {
    window.minimize().map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_window_toggle_maximize(window: WebviewWindow) -> Result<(), String> {
    if window.is_maximized().map_err(|error| error.to_string())? {
        window.unmaximize().map_err(|error| error.to_string())
    } else {
        window.maximize().map_err(|error| error.to_string())
    }
}

#[tauri::command]
fn desktop_window_start_drag(window: WebviewWindow) -> Result<(), String> {
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
fn desktop_window_start_resize(window: Window, direction: String) -> Result<(), String> {
    let direction = parse_resize_direction(direction.trim())?;
    window
        .start_resize_dragging(direction)
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_window_set_ignore_cursor_events(
    window: WebviewWindow,
    ignore: bool,
) -> Result<(), String> {
    window
        .set_ignore_cursor_events(ignore)
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_window_cursor_position(
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

#[tauri::command]
fn desktop_window_close(
    window: WebviewWindow,
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    if window.label() == "main" {
        shutdown_desktop_app(&app, state.inner(), "desktop_window_close command");
        return Ok(());
    }
    if window.label() == "chat" {
        request_bridge_chat_close(state.inner(), "desktop_window_close command");
        return window.destroy().map_err(|error| error.to_string());
    }
    window.close().map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_open_chat_window(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
    let chat_window = if let Some(window) = app.get_webview_window("chat") {
        restart_debug_log("desktop_open_chat_window reuse existing window");
        window
    } else {
        let url = chat_window_url(state.bridge_port, &state.bridge_auth_token);
        restart_debug_log(format!("desktop_open_chat_window create url={url}"));
        WebviewWindowBuilder::new(&app, "chat", WebviewUrl::App(url.into()))
            .title("Shinsekai Chat")
            .inner_size(1280.0, 820.0)
            .min_inner_size(960.0, 620.0)
            .resizable(true)
            .transparent(true)
            .decorations(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .shadow(false)
            .center()
            .build()
            .map_err(|error| error.to_string())?
    };

    navigate_chat_window_to_live_frontend(&app, state.bridge_port, &state.bridge_auth_token)?;
    let _ = chat_window.show();
    let _ = chat_window.unminimize();
    let _ = chat_window.set_focus();
    Ok(())
}

#[tauri::command]
fn desktop_open_external_url(url: String) -> Result<(), String> {
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

fn bootstrap_runtime(app: AppHandle) {
    restart_debug_log("bootstrap_runtime start");
    let state = app.state::<DesktopState>();
    restart_debug_log("bootstrap_runtime starting fixed managed runtime");
    match start_runtime_candidate_for_state(&app, &state, None) {
        Ok(_) => {
            restart_debug_log("bootstrap_runtime ready");
            if let Err(error) =
                navigate_main_window_to_live_frontend(&app, state.bridge_port, &state.bridge_auth_token)
            {
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

fn encode_query_value(value: &str) -> String {
    value
        .replace(':', "%3A")
        .replace('/', "%2F")
        .replace(' ', "%20")
        .replace('&', "%26")
        .replace('=', "%3D")
        .replace('#', "%23")
}

fn encode_bridge_url(port: u16) -> String {
    encode_query_value(&format!("http://{BRIDGE_HOST}:{port}"))
}

fn app_window_url_for_route(port: u16, auth_token: &str, route: &str) -> String {
    let encoded = encode_bridge_url(port);
    let encoded_token = encode_query_value(auth_token);
    format!("index.html?shinsekai_bridge={encoded}&shinsekai_bridge_token={encoded_token}#{route}")
}

fn app_window_url(port: u16, auth_token: &str) -> String {
    app_window_url_for_route(port, auth_token, "/settings/api")
}

fn chat_window_url(port: u16, auth_token: &str) -> String {
    app_window_url_for_route(port, auth_token, "/chat-stage")
}

fn live_frontend_url_for_route(port: u16, auth_token: &str, route: &str) -> String {
    let encoded = encode_bridge_url(port);
    let encoded_token = encode_query_value(auth_token);
    let reload_token = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().to_string())
        .unwrap_or_else(|_| "0".to_string());
    format!(
        "{LIVE_FRONTEND_SCHEME}://localhost/?shinsekai_bridge={encoded}&shinsekai_bridge_token={encoded_token}&shinsekai_reload={reload_token}#{route}"
    )
}

fn live_frontend_url(port: u16, auth_token: &str) -> String {
    live_frontend_url_for_route(port, auth_token, "/settings/api")
}

fn live_chat_frontend_url(port: u16, auth_token: &str) -> String {
    live_frontend_url_for_route(port, auth_token, "/chat-stage")
}

fn navigate_window_to_live_frontend(
    app: &AppHandle,
    label: &str,
    target_url: &str,
) -> Result<(), String> {
    let url = Url::parse(target_url).map_err(|error| error.to_string())?;
    if let Some(window) = app.get_webview_window(label) {
        restart_debug_log(format!("navigate {label} live frontend url={url}"));
        window.navigate(url).map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn navigate_main_window_to_live_frontend(
    app: &AppHandle,
    bridge_port: u16,
    auth_token: &str,
) -> Result<(), String> {
    navigate_window_to_live_frontend(app, "main", &live_frontend_url(bridge_port, auth_token))
}

fn navigate_chat_window_to_live_frontend(
    app: &AppHandle,
    bridge_port: u16,
    auth_token: &str,
) -> Result<(), String> {
    navigate_window_to_live_frontend(app, "chat", &live_chat_frontend_url(bridge_port, auth_token))
}

fn live_frontend_reload_targets(bridge_port: u16, auth_token: &str) -> [(&'static str, String); 2] {
    [
        ("main", live_frontend_url(bridge_port, auth_token)),
        ("chat", live_chat_frontend_url(bridge_port, auth_token)),
    ]
}

fn reload_live_frontend_windows(
    app: &AppHandle,
    bridge_port: u16,
    auth_token: &str,
) -> Result<(), String> {
    for (label, target_url) in live_frontend_reload_targets(bridge_port, auth_token) {
        navigate_window_to_live_frontend(app, label, &target_url)?;
    }
    Ok(())
}

fn serve_live_frontend_protocol(
    frontend_dist: &Arc<Mutex<Option<PathBuf>>>,
    request_path: &str,
) -> Response<Vec<u8>> {
    let raw_dist = match frontend_dist.lock().ok().and_then(|dist| dist.clone()) {
        Some(path) => path,
        None => {
            return protocol_text_response(
                StatusCode::SERVICE_UNAVAILABLE,
                "frontend dist is not ready",
            )
        }
    };
    let current_dist = resolve_published_frontend_dist(&raw_dist);
    let index_path = current_dist.join("index.html");
    if !index_path.is_file() {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend index.html not found");
    }

    if request_path.is_empty() || request_path == "/" || request_path == "/index.html" {
        return protocol_file_response(&index_path);
    }

    for root in frontend_dist_roots(&raw_dist) {
        if let Some(candidate) = resolve_static_request_path(&root, request_path) {
            if candidate.is_file() {
                return protocol_file_response(&candidate);
            }
        }
    }

    if request_path.starts_with("/web-assets/") {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend asset not found");
    }
    protocol_file_response(&index_path)
}

fn resolve_published_frontend_dist(raw_dist: &Path) -> PathBuf {
    let Some(frontend_dir) = raw_dist.parent() else {
        return raw_dist.to_path_buf();
    };
    let marker = frontend_dir.join(FRONTEND_DIST_MARKER);
    let Ok(marker_text) = fs::read_to_string(marker) else {
        return raw_dist.to_path_buf();
    };
    let trimmed = marker_text.trim();
    if trimmed.is_empty() {
        return raw_dist.to_path_buf();
    }
    let relative = Path::new(trimmed);
    if relative.is_absolute()
        || !relative
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
    {
        return raw_dist.to_path_buf();
    }

    let frontend_root = frontend_dir
        .canonicalize()
        .unwrap_or_else(|_| frontend_dir.to_path_buf());
    let Ok(target) = frontend_root.join(relative).canonicalize() else {
        return raw_dist.to_path_buf();
    };
    if !target.starts_with(&frontend_root) || !target.join("index.html").is_file() {
        return raw_dist.to_path_buf();
    }
    target
}

fn frontend_dist_roots(raw_dist: &Path) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    push_frontend_dist_root(&mut roots, resolve_published_frontend_dist(raw_dist));
    push_frontend_dist_root(&mut roots, raw_dist.to_path_buf());

    if let Some(frontend_dir) = raw_dist.parent() {
        let releases_dir = frontend_dir.join(FRONTEND_DIST_RELEASES);
        if let Ok(entries) = fs::read_dir(releases_dir) {
            let mut release_dirs = entries
                .filter_map(Result::ok)
                .map(|entry| entry.path())
                .filter(|path| path.is_dir())
                .collect::<Vec<_>>();
            release_dirs.sort_by_key(|path| {
                fs::metadata(path)
                    .and_then(|metadata| metadata.modified())
                    .ok()
                    .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
                    .map(|duration| duration.as_millis())
                    .unwrap_or(0)
            });
            release_dirs.reverse();
            for release_dir in release_dirs {
                push_frontend_dist_root(&mut roots, release_dir);
            }
        }
    }
    roots
}

fn push_frontend_dist_root(roots: &mut Vec<PathBuf>, root: PathBuf) {
    if !root.join("index.html").is_file() {
        return;
    }
    let resolved = root.canonicalize().unwrap_or(root);
    if !roots.iter().any(|candidate| candidate == &resolved) {
        roots.push(resolved);
    }
}

fn resolve_static_request_path(root: &Path, request_path: &str) -> Option<PathBuf> {
    let decoded = percent_decode_path(request_path)?;
    let mut target = root.to_path_buf();
    for part in decoded.trim_start_matches('/').split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." || part.contains('\\') {
            return None;
        }
        target.push(part);
    }
    Some(target)
}

fn percent_decode_path(path: &str) -> Option<String> {
    let bytes = path.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            if index + 2 >= bytes.len() {
                return None;
            }
            let high = hex_value(bytes[index + 1])?;
            let low = hex_value(bytes[index + 2])?;
            out.push((high << 4) | low);
            index += 3;
        } else {
            out.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(out).ok()
}

fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

fn protocol_file_response(path: &Path) -> Response<Vec<u8>> {
    let Ok(body) = fs::read(path) else {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend file not found");
    };
    let cache_control = if path.file_name().and_then(|name| name.to_str()) == Some("index.html") {
        "no-cache"
    } else {
        "public, max-age=31536000, immutable"
    };
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, content_type_for_path(path))
        .header(header::CACHE_CONTROL, cache_control)
        .body(body)
        .unwrap_or_else(|_| {
            protocol_text_response(StatusCode::INTERNAL_SERVER_ERROR, "response build failed")
        })
}

fn protocol_text_response(status: StatusCode, message: &str) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .body(message.as_bytes().to_vec())
        .unwrap_or_else(|_| Response::new(Vec::new()))
}

fn content_type_for_path(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| extension.to_ascii_lowercase())
        .as_deref()
    {
        Some("html") => "text/html; charset=utf-8",
        Some("js") | Some("mjs") => "text/javascript; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        Some("json") => "application/json; charset=utf-8",
        Some("svg") => "image/svg+xml",
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        Some("ico") => "image/x-icon",
        Some("woff") => "font/woff",
        Some("woff2") => "font/woff2",
        Some("ttf") => "font/ttf",
        Some("wasm") => "application/wasm",
        _ => "application/octet-stream",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_published_frontend_dist_uses_current_marker() {
        let root = temp_test_dir("published-dist");
        let raw_dist = root.join("frontend").join("dist");
        let release = root
            .join("frontend")
            .join(FRONTEND_DIST_RELEASES)
            .join("v2");
        fs::create_dir_all(&raw_dist).unwrap();
        fs::create_dir_all(&release).unwrap();
        fs::write(raw_dist.join("index.html"), "old").unwrap();
        fs::write(release.join("index.html"), "new").unwrap();
        fs::write(
            root.join("frontend").join(FRONTEND_DIST_MARKER),
            format!("{FRONTEND_DIST_RELEASES}/v2\n"),
        )
        .unwrap();

        assert_eq!(
            resolve_published_frontend_dist(&raw_dist),
            release.canonicalize().unwrap()
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn resolve_static_request_path_rejects_parent_and_backslash_segments() {
        let root = PathBuf::from("/tmp/frontend-dist");

        assert_eq!(
            resolve_static_request_path(&root, "/web-assets/app.js").unwrap(),
            root.join("web-assets").join("app.js")
        );
        assert!(resolve_static_request_path(&root, "/../secret").is_none());
        assert!(resolve_static_request_path(&root, "/web-assets\\secret.js").is_none());
    }

    #[test]
    fn app_root_from_executable_uses_executable_parent() {
        let executable = PathBuf::from("/opt/Shinsekai/shinsekai");

        assert_eq!(
            app_root_from_executable(&executable).unwrap(),
            PathBuf::from("/opt/Shinsekai")
        );
    }

    #[test]
    fn app_root_from_resource_dir_unwraps_resources_directory() {
        let resource_dir = PathBuf::from("/opt/Shinsekai/resources");

        assert_eq!(
            app_root_from_resource_dir(&resource_dir).unwrap(),
            PathBuf::from("/opt/Shinsekai")
        );
    }

    #[test]
    fn install_dir_project_root_migrates_app_data_when_install_data_is_empty() {
        let root = temp_test_dir("install-project-root-migrate");
        let app_root = root.join("Shinsekai");
        let app_data_project = root.join("app-data").join("project");
        let old_config = app_data_project.join("data").join("config");
        fs::create_dir_all(&old_config).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        fs::write(old_config.join("system_config.yaml"), "ok").unwrap();

        let selected = install_dir_project_root(&app_root, &app_data_project)
            .unwrap()
            .unwrap();

        assert_eq!(selected, app_root);
        assert!(selected
            .join("data")
            .join("config")
            .join("system_config.yaml")
            .is_file());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn install_dir_project_root_keeps_existing_install_data() {
        let root = temp_test_dir("install-project-root-existing-data");
        let app_root = root.join("Shinsekai");
        let app_data_project = root.join("app-data").join("project");
        fs::create_dir_all(app_data_project.join("data").join("config")).unwrap();
        fs::create_dir_all(app_root.join("data")).unwrap();
        fs::write(
            app_data_project
                .join("data")
                .join("config")
                .join("old.yaml"),
            "old",
        )
        .unwrap();
        fs::write(app_root.join("data").join("existing.txt"), "existing").unwrap();

        let selected = install_dir_project_root(&app_root, &app_data_project)
            .unwrap()
            .unwrap();

        assert_eq!(selected, app_root);
        assert!(selected.join("data").join("existing.txt").is_file());
        assert!(!selected
            .join("data")
            .join("config")
            .join("old.yaml")
            .is_file());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_scan_keeps_ready_state_when_bridge_is_running() {
        let phase = phase_after_runtime_scan(true, runtime_scan_view(Some("python-ready")));

        match phase {
            DesktopRuntimePhase::Ready { view: Some(view) } => {
                assert_eq!(view.selected_candidate_id.as_deref(), Some("python-ready"));
            }
            _ => panic!("running bridge with a ready candidate should stay ready"),
        }
    }

    #[test]
    fn runtime_scan_enters_guided_action_when_no_ready_candidate_exists() {
        let phase = phase_after_runtime_scan(true, runtime_scan_view(None));

        match phase {
            DesktopRuntimePhase::NeedsAction { view } => {
                assert_eq!(view.message.as_deref(), Some("needs runtime action"));
            }
            _ => panic!("scan without a ready candidate should enter runtime guidance"),
        }
    }

    #[test]
    fn window_urls_encode_bridge_and_route() {
        assert_eq!(
            app_window_url(8787, "token-1"),
            "index.html?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787&shinsekai_bridge_token=token-1#/settings/api"
        );
        assert_eq!(
            chat_window_url(8787, "token-1"),
            "index.html?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787&shinsekai_bridge_token=token-1#/chat-stage"
        );
    }

    #[test]
    fn live_frontend_urls_target_expected_routes() {
        let main = live_frontend_url(8787, "token-1");
        let chat = live_chat_frontend_url(8787, "token-1");

        assert!(main
            .starts_with("shinsekai://localhost/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787"));
        assert!(main.contains("shinsekai_bridge_token=token-1"));
        assert!(main.contains("#/settings/api"));
        assert!(chat
            .starts_with("shinsekai://localhost/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787"));
        assert!(chat.contains("shinsekai_bridge_token=token-1"));
        assert!(chat.contains("#/chat-stage"));
    }

    #[test]
    fn live_frontend_reload_targets_cover_main_and_chat_windows() {
        let targets = live_frontend_reload_targets(8787, "token-1");

        assert_eq!(targets[0].0, "main");
        assert!(targets[0].1.contains("#/settings/api"));
        assert_eq!(targets[1].0, "chat");
        assert!(targets[1].1.contains("#/chat-stage"));
    }

    #[test]
    fn send_bridge_chat_close_posts_local_close_request() {
        let listener = TcpListener::bind((BRIDGE_HOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0_u8; 1024];
            let read = stream.read(&mut buffer).unwrap();
            let request = String::from_utf8_lossy(&buffer[..read]).to_string();
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
                .unwrap();
            request
        });

        send_bridge_chat_close(port, "token-1").unwrap();

        let request = handle.join().unwrap();
        assert!(request.starts_with("POST /api/chat/close HTTP/1.1\r\n"));
        assert!(request.contains("Host: 127.0.0.1\r\n"));
        assert!(request.contains("Content-Type: application/json\r\n"));
        assert!(request.contains("X-Shinsekai-Bridge-Token: token-1\r\n"));
        assert!(request.ends_with("\r\n\r\n{}"));
    }

    fn runtime_scan_view(selected_candidate_id: Option<&str>) -> runtime::RuntimeScanView {
        runtime::RuntimeScanView {
            selected_candidate_id: selected_candidate_id.map(ToString::to_string),
            recommended_action: Some(runtime::RuntimeRepairActionKind::Start),
            candidates: Vec::new(),
            message: Some("needs runtime action".to_string()),
        }
    }

    fn temp_test_dir(label: &str) -> PathBuf {
        let token = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        env::temp_dir().join(format!(
            "shinsekai-tauri-test-{label}-{}-{token}",
            std::process::id()
        ))
    }
}

fn start_bridge_for_state(
    state: &DesktopState,
    runtime: runtime::PythonRuntime,
) -> DesktopResult<()> {
    let candidate_id = runtime.candidate_id.clone();
    if state
        .bridge
        .lock()
        .map(|bridge| bridge.is_some())
        .unwrap_or(false)
    {
        restart_debug_log("start_bridge_for_state skipped; bridge already present");
        return Ok(());
    }

    let bridge = spawn_bridge(
        &state.source_root,
        &state.project_root,
        &state.app_root,
        &state.frontend_dist,
        state.bridge_port,
        &state.bridge_auth_token,
        runtime,
    )?;
    let mut child = Some(BridgeProcess::new(bridge.child, candidate_id.clone()));
    if let Ok(mut bridge_process) = state.bridge.lock() {
        if bridge_process.is_none() {
            *bridge_process = child.take();
            restart_debug_log(format!(
                "start_bridge_for_state stored bridge process candidate_id={}",
                candidate_id.as_deref().unwrap_or("")
            ));
        }
    }
    Ok(())
}

fn spawn_bridge(
    source_root: &Path,
    project_root: &Path,
    app_root: &Path,
    frontend_dist: &Path,
    port: u16,
    auth_token: &str,
    runtime: runtime::PythonRuntime,
) -> DesktopResult<BridgeLaunch> {
    println!("Using Shinsekai Python runtime: {}", runtime.description);
    restart_debug_log(format!(
        "spawn_bridge runtime={} candidate_id={} source_root={} project_root={} app_root={} frontend_dist={} port={} parent_pid={}",
        runtime.description,
        runtime.candidate_id.as_deref().unwrap_or(""),
        source_root.display(),
        project_root.display(),
        app_root.display(),
        frontend_dist.display(),
        port,
        std::process::id()
    ));
    let mut command = runtime.command;
    sanitize_python_environment(&mut command);

    command
        .env("SHINSEKAI_RESTART_LOG", restart_debug_log_path())
        .arg(source_root.join("frontend_bridge.py"))
        .arg("--host")
        .arg(BRIDGE_HOST)
        .arg("--port")
        .arg(port.to_string())
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .arg("--auth-token")
        .arg(auth_token)
        .arg("--project-root")
        .arg(&project_root)
        .arg("--app-root")
        .arg(&app_root)
        .arg("--frontend-dist")
        .arg(&frontend_dist)
        .current_dir(&source_root);

    #[cfg(windows)]
    command.creation_flags(0x0800_0000);

    let mut child = command.spawn().map_err(|error| {
        restart_debug_log(format!("spawn_bridge failed error={error}"));
        format!(
            "failed to start Shinsekai Python bridge from {}: {error}",
            source_root.display()
        )
    })?;
    restart_debug_log(format!("spawn_bridge child_pid={}", child.id()));

    wait_for_bridge(&mut child, port)?;
    restart_debug_log(format!(
        "spawn_bridge health ready child_pid={} port={}",
        child.id(),
        port
    ));
    Ok(BridgeLaunch { child })
}

fn resolve_source_root(app: &tauri::App) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_SOURCE_ROOT") {
        if has_bridge(&root) {
            return Ok(root);
        }
        return Err(format!(
            "SHINSEKAI_SOURCE_ROOT does not contain frontend_bridge.py: {}",
            root.display()
        )
        .into());
    }

    #[cfg(debug_assertions)]
    if let Some(root) = dev_project_root() {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        if has_bridge(&resource_dir) {
            return Ok(resource_dir);
        }
    }

    if let Some(root) = dev_project_root() {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    let exe_dir = env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    if let Some(root) = exe_dir {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    Err("could not locate Shinsekai application resources; set SHINSEKAI_SOURCE_ROOT".into())
}

fn resolve_project_root(app: &tauri::App, app_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_PROJECT_ROOT") {
        fs::create_dir_all(&root)?;
        return Ok(root);
    }

    let app_data_project_root = app.path().app_data_dir()?.join("project");
    if let Some(root) = install_dir_project_root(app_root, &app_data_project_root)? {
        return Ok(root);
    }

    fs::create_dir_all(&app_data_project_root)?;
    Ok(app_data_project_root)
}

fn install_dir_project_root(
    app_root: &Path,
    app_data_project_root: &Path,
) -> DesktopResult<Option<PathBuf>> {
    let data_root = app_root.join("data");
    if fs::create_dir_all(&data_root).is_err() || !can_write_directory(&data_root) {
        return Ok(None);
    }
    migrate_project_data_if_empty(app_data_project_root, app_root)?;
    Ok(Some(app_root.to_path_buf()))
}

fn can_write_directory(path: &Path) -> bool {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let probe = path.join(format!(
        ".shinsekai-write-test-{}-{nonce}",
        std::process::id()
    ));
    let ok = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&probe)
        .and_then(|mut file| file.write_all(b"ok"))
        .is_ok();
    let _ = fs::remove_file(probe);
    ok
}

fn migrate_project_data_if_empty(
    app_data_project_root: &Path,
    install_project_root: &Path,
) -> DesktopResult<()> {
    let old_data = app_data_project_root.join("data");
    let new_data = install_project_root.join("data");
    if !old_data.is_dir() || !directory_is_empty(&new_data)? {
        return Ok(());
    }
    copy_dir_missing(&old_data, &new_data)?;
    Ok(())
}

fn directory_is_empty(path: &Path) -> DesktopResult<bool> {
    if !path.is_dir() {
        return Ok(true);
    }
    Ok(fs::read_dir(path)?.next().is_none())
}

fn copy_dir_missing(src: &Path, dst: &Path) -> DesktopResult<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if dst_path.exists() {
            continue;
        }
        let file_type = entry.file_type()?;
        if file_type.is_dir() {
            copy_dir_missing(&src_path, &dst_path)?;
        } else if file_type.is_file() {
            fs::copy(&src_path, &dst_path)?;
        }
    }
    Ok(())
}

fn resolve_app_root(app: &tauri::App, source_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_APP_ROOT") {
        if root.is_dir() {
            return Ok(root);
        }
        return Err(format!("SHINSEKAI_APP_ROOT is not a directory: {}", root.display()).into());
    }

    if let Some(root) = appimage_app_root() {
        return Ok(root);
    }

    if dev_project_root().as_deref() == Some(source_root) {
        return Ok(source_root.to_path_buf());
    }

    if let Some(root) = app_root_from_current_exe() {
        return Ok(root);
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        if let Some(root) = app_root_from_resource_dir(&resource_dir) {
            return Ok(root);
        }
    }

    Ok(source_root.to_path_buf())
}

fn appimage_app_root() -> Option<PathBuf> {
    env_path("APPIMAGE")
        .and_then(|path| path.parent().map(Path::to_path_buf))
        .filter(|path| path.is_dir())
}

fn app_root_from_current_exe() -> Option<PathBuf> {
    env::current_exe()
        .ok()
        .and_then(|path| app_root_from_executable(&path))
}

fn app_root_from_executable(executable: &Path) -> Option<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        if let Some(app_bundle) = executable.ancestors().find(|ancestor| {
            ancestor
                .extension()
                .and_then(|extension| extension.to_str())
                .is_some_and(|extension| extension.eq_ignore_ascii_case("app"))
        }) {
            return app_bundle.parent().map(Path::to_path_buf);
        }
    }

    executable.parent().map(Path::to_path_buf)
}

fn app_root_from_resource_dir(resource_dir: &Path) -> Option<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        if let Some(app_bundle) = resource_dir.ancestors().find(|ancestor| {
            ancestor
                .extension()
                .and_then(|extension| extension.to_str())
                .is_some_and(|extension| extension.eq_ignore_ascii_case("app"))
        }) {
            return app_bundle.parent().map(Path::to_path_buf);
        }
    }

    if resource_dir.file_name().and_then(|name| name.to_str()) == Some("resources") {
        return resource_dir.parent().map(Path::to_path_buf);
    }
    Some(resource_dir.to_path_buf())
}

fn dev_project_root() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent()?.parent().map(Path::to_path_buf)
}

fn has_bridge(root: &Path) -> bool {
    root.join("frontend_bridge.py").is_file()
}

fn resolve_frontend_dist(project_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(dist) = env_path("SHINSEKAI_FRONTEND_DIST") {
        if dist.join("index.html").is_file() {
            return Ok(dist);
        }
        return Err(format!(
            "SHINSEKAI_FRONTEND_DIST does not contain index.html: {}",
            dist.display()
        )
        .into());
    }

    let dist = project_root.join("frontend").join("dist");
    if dist.join("index.html").is_file() {
        return Ok(dist);
    }

    Err(format!(
        "built frontend not found at {}; run `pnpm build` in frontend first",
        dist.display()
    )
    .into())
}

fn env_path(name: &str) -> Option<PathBuf> {
    env::var_os(name)
        .map(PathBuf::from)
        .map(|path| path.expand_home())
        .map(|path| path.canonicalize().unwrap_or(path))
}

fn sanitize_python_environment(command: &mut Command) {
    command.env_remove("PYTHONHOME").env_remove("PYTHONPATH");

    if env::var_os("APPIMAGE").is_some() || env::var_os("APPDIR").is_some() {
        command.env_remove("LD_LIBRARY_PATH");
    }
}

fn choose_bridge_port() -> DesktopResult<u16> {
    if let Ok(raw) = env::var("SHINSEKAI_BRIDGE_PORT") {
        let port = raw
            .parse::<u16>()
            .map_err(|_| format!("SHINSEKAI_BRIDGE_PORT is not a valid port: {raw}"))?;
        restart_debug_log(format!("choose_bridge_port env port={port}"));
        return Ok(port);
    }

    if TcpListener::bind((BRIDGE_HOST, DEFAULT_BRIDGE_PORT)).is_ok() {
        restart_debug_log(format!(
            "choose_bridge_port default port={DEFAULT_BRIDGE_PORT}"
        ));
        return Ok(DEFAULT_BRIDGE_PORT);
    }

    let listener = TcpListener::bind((BRIDGE_HOST, 0))?;
    let port = listener.local_addr()?.port();
    restart_debug_log(format!(
        "choose_bridge_port default_busy fallback_port={port}"
    ));
    Ok(port)
}

fn wait_for_bridge(child: &mut Child, port: u16) -> DesktopResult<()> {
    let addr: SocketAddr = format!("{BRIDGE_HOST}:{port}").parse()?;
    let started = Instant::now();
    let timeout = Duration::from_secs(45);
    restart_debug_log(format!(
        "wait_for_bridge start child_pid={} port={port}",
        child.id()
    ));

    while started.elapsed() < timeout {
        if let Some(status) = child.try_wait()? {
            restart_debug_log(format!(
                "wait_for_bridge child exited before ready child_pid={} status={status}",
                child.id()
            ));
            return Err(format!("Python bridge exited before startup completed: {status}").into());
        }

        if bridge_health_ok(&addr) {
            restart_debug_log(format!(
                "wait_for_bridge health ok child_pid={} port={port} elapsed_ms={}",
                child.id(),
                started.elapsed().as_millis()
            ));
            return Ok(());
        }

        thread::sleep(Duration::from_millis(120));
    }

    restart_debug_log(format!(
        "wait_for_bridge timeout child_pid={} port={port} elapsed_ms={}",
        child.id(),
        started.elapsed().as_millis()
    ));
    Err(format!("timed out waiting for Python bridge on http://{BRIDGE_HOST}:{port}").into())
}

fn bridge_health_ok(addr: &SocketAddr) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(addr, Duration::from_millis(200)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    let request =
        format!("GET /api/health HTTP/1.1\r\nHost: {BRIDGE_HOST}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

trait ExpandHome {
    fn expand_home(self) -> Self;
}

impl ExpandHome for PathBuf {
    fn expand_home(self) -> Self {
        let raw = self.as_os_str().to_string_lossy();
        if raw == "~" {
            return home_dir().unwrap_or(self);
        }
        if let Some(rest) = raw.strip_prefix("~/") {
            if let Some(home) = home_dir() {
                return home.join(rest);
            }
        }
        self
    }
}

fn home_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        env::var_os("USERPROFILE").map(PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        env::var_os("HOME").map(PathBuf::from)
    }
}
