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

use serde::Serialize;
use tauri::{
    http::{header, Response, StatusCode},
    AppHandle, Emitter, Manager, State, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
    WindowEvent,
};
#[cfg(desktop)]
use tauri_plugin_updater::{Update, UpdaterExt};

#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

mod runtime;

type DesktopResult<T> = Result<T, Box<dyn Error>>;

const BRIDGE_HOST: &str = "127.0.0.1";
const DEFAULT_BRIDGE_PORT: u16 = 8787;
const RESTART_DEBUG_LOG_FILE: &str = "shinsekai-restart-debug.log";
const LIVE_FRONTEND_SCHEME: &str = "shinsekai";
const FRONTEND_DIST_MARKER: &str = ".dist-current";
const FRONTEND_DIST_RELEASES: &str = ".dist-releases";
const MAX_DESKTOP_FILE_BROWSER_ENTRIES: usize = 2000;
#[cfg(desktop)]
const UPDATE_PROGRESS_EVENT: &str = "shinsekai:update-progress";
const RUNTIME_PROGRESS_EVENT: &str = "shinsekai:runtime-progress";

#[cfg(unix)]
unsafe extern "C" {
    fn setsid() -> i32;
}

struct BridgeProcess {
    child: Mutex<Option<Child>>,
}

impl BridgeProcess {
    fn new(child: Child) -> Self {
        Self {
            child: Mutex::new(Some(child)),
        }
    }

    fn stop(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut child) = child.take() {
                restart_debug_log(format!("bridge stop requested child_pid={}", child.id()));
                let _ = child.kill();
                let _ = child.wait();
                restart_debug_log("bridge stop completed");
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
    ) -> Self {
        Self {
            source_root,
            project_root,
            app_root,
            frontend_dist,
            bridge_port,
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
        let selected_candidate_id = scan_view
            .as_ref()
            .and_then(|view| view.selected_candidate_id.clone());
        let recommended_action = scan_view.as_ref().and_then(|view| view.recommended_action);
        let candidates = scan_view
            .map(|view| view.candidates)
            .unwrap_or_else(Vec::new);
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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopFileBrowserEntry {
    kind: &'static str,
    modified_at: Option<f64>,
    name: String,
    path: String,
    size: Option<u64>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopFileBrowserRoot {
    label: String,
    path: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopFileBrowserSnapshot {
    cwd: String,
    entries: Vec<DesktopFileBrowserEntry>,
    parent: String,
    roots: Vec<DesktopFileBrowserRoot>,
}

#[cfg(desktop)]
#[derive(Default)]
struct DesktopUpdateDownloadProgress {
    downloaded: u64,
    content_length: Option<u64>,
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
            desktop_runtime_scan,
            desktop_runtime_start,
            desktop_runtime_select,
            desktop_runtime_choose_python,
            desktop_runtime_repair,
            desktop_files_browse,
            desktop_restart_debug_log,
            desktop_app_restart,
            desktop_bridge_restart,
            desktop_frontend_reload,
            desktop_window_minimize,
            desktop_window_toggle_maximize,
            desktop_window_start_drag,
            desktop_window_close,
            desktop_open_external_url,
            #[cfg(desktop)]
            desktop_update_check,
            #[cfg(desktop)]
            desktop_update_install
        ])
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let app = window.app_handle().clone();
                let state = app.state::<DesktopState>();
                shutdown_desktop_app(&app, state.inner(), "main window close requested");
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
            let project_root = resolve_project_root(app)?;
            let app_root = resolve_app_root(app, &source_root)?;
            let frontend_dist = resolve_frontend_dist(&source_root)?;
            let bridge_port = choose_bridge_port()?;
            let url = app_window_url(bridge_port);
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

#[tauri::command]
fn desktop_runtime_state(state: State<'_, DesktopState>) -> DesktopRuntimeView {
    state.runtime_view()
}

#[tauri::command]
fn desktop_runtime_scan(app: AppHandle, state: State<'_, DesktopState>) -> DesktopRuntimeView {
    emit_runtime_progress(
        &app,
        "probing",
        None,
        None,
        Some("Scanning runtime candidates"),
    );
    let view = runtime::scan_runtime_view(&app, &state.source_root);
    state.set_runtime(phase_after_runtime_scan(state.has_bridge(), view));
    state.runtime_view()
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
fn desktop_runtime_start(
    app: AppHandle,
    state: State<'_, DesktopState>,
    candidate_id: Option<String>,
) -> Result<DesktopRuntimeView, String> {
    start_runtime_candidate_for_state(&app, &state, candidate_id.as_deref())
}

#[tauri::command]
fn desktop_runtime_select(
    app: AppHandle,
    state: State<'_, DesktopState>,
    candidate_id: String,
) -> Result<DesktopRuntimeView, String> {
    runtime::save_runtime_preference(&app, &state.source_root, &candidate_id)
        .map_err(|error| error.to_string())?;
    start_runtime_candidate_for_state(&app, &state, Some(&candidate_id))
}

#[tauri::command]
fn desktop_runtime_choose_python(
    app: AppHandle,
    state: State<'_, DesktopState>,
    path: String,
) -> Result<DesktopRuntimeView, String> {
    emit_runtime_progress(
        &app,
        "probing",
        None,
        Some("local".to_string()),
        Some("Checking selected Python runtime"),
    );
    let candidate_id = runtime::save_runtime_preference_for_path(&app, &PathBuf::from(path))
        .map_err(|error| set_runtime_error_state(&app, &state, error.to_string()))?;
    let scan = runtime::scan_runtime_view(&app, &state.source_root);
    let chosen_is_ready = scan
        .candidates
        .iter()
        .find(|candidate| candidate.id == candidate_id)
        .map(|candidate| candidate.status == runtime::RuntimeCandidateStatus::Ready)
        .unwrap_or(false);
    if chosen_is_ready {
        return start_runtime_candidate_for_state(&app, &state, Some(&candidate_id));
    }
    state.set_runtime(DesktopRuntimePhase::NeedsAction { view: scan });
    Ok(state.runtime_view())
}

#[tauri::command]
fn desktop_runtime_repair(
    app: AppHandle,
    state: State<'_, DesktopState>,
    candidate_id: String,
    action: runtime::RuntimeRepairActionKind,
) -> Result<DesktopRuntimeView, String> {
    emit_runtime_progress(
        &app,
        "installingDeps",
        Some(candidate_id.clone()),
        None,
        Some("Repairing runtime candidate"),
    );
    let scan = runtime::scan_runtime_view(&app, &state.source_root);
    state.set_runtime(DesktopRuntimePhase::Updating { view: Some(scan) });
    let repaired_path =
        runtime::repair_runtime_candidate(&app, &state.source_root, &candidate_id, action)
            .map_err(|error| set_runtime_error_state(&app, &state, error.to_string()))?;
    emit_runtime_progress(
        &app,
        "checkingBridge",
        Some(candidate_id),
        None,
        Some("Checking repaired runtime"),
    );
    start_repaired_runtime_for_state(&app, &state, repaired_path.as_deref())
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
    browse_desktop_files(state.inner(), path.as_deref(), show_hidden.unwrap_or(false))
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
fn desktop_bridge_restart(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<DesktopRuntimeView, String> {
    restart_debug_log("desktop_bridge_restart command received");
    restart_bridge_for_state(&app, &state)
}

#[tauri::command]
fn desktop_frontend_reload(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
    restart_debug_log("desktop_frontend_reload command received");
    navigate_main_window_to_live_frontend(&app, state.bridge_port)
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
    let scan = runtime::scan_runtime_view(app, &state.source_root);
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

    let result = runtime::find_python_runtime_for_candidate(app, &state.source_root, candidate_id)
        .map_err(|error| error.to_string())
        .and_then(|runtime| {
            start_bridge_for_state(state, runtime).map_err(|error| error.to_string())
        });

    match result {
        Ok(()) => {
            let view = runtime::scan_runtime_view(app, &state.source_root);
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
    if let Some(candidate_id) = repaired_candidate_id.as_deref() {
        runtime::save_runtime_preference(app, &state.source_root, candidate_id).map_err(
            |error| {
                set_runtime_error_state(
                    app,
                    state,
                    format!("repaired runtime is ready but could not save preference: {error}"),
                )
            },
        )?;
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
    if let Some(bridge) = state.take_bridge() {
        restart_debug_log("shutdown stopping bridge");
        bridge.stop();
    } else {
        restart_debug_log("shutdown no bridge to stop");
    }
    restart_debug_log("shutdown requested app.exit(0)");
    app.exit(0);
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

#[tauri::command]
fn desktop_window_close(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
    shutdown_desktop_app(&app, state.inner(), "desktop_window_close command");
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

fn browse_desktop_files(
    state: &DesktopState,
    raw_path: Option<&str>,
    show_hidden: bool,
) -> DesktopResult<DesktopFileBrowserSnapshot> {
    let mut target = desktop_browse_target(&state.project_root, &state.app_root, raw_path)?;
    if target.is_file() {
        target = target
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| state.app_root.clone());
    }
    if !target.exists() {
        return Err(format!("path does not exist: {}", target.display()).into());
    }
    if !target.is_dir() {
        return Err(format!("path is not a directory: {}", target.display()).into());
    }

    let mut entries = Vec::new();
    for child in fs::read_dir(&target)? {
        if entries.len() >= MAX_DESKTOP_FILE_BROWSER_ENTRIES {
            break;
        }
        let child = child?;
        let name = child.file_name().to_string_lossy().to_string();
        if !show_hidden && name.starts_with('.') {
            continue;
        }
        let file_type = match child.file_type() {
            Ok(file_type) => file_type,
            Err(_) => continue,
        };
        let metadata = match child.metadata() {
            Ok(metadata) => metadata,
            Err(_) => continue,
        };
        let is_dir = file_type.is_dir();
        entries.push(DesktopFileBrowserEntry {
            kind: if is_dir { "directory" } else { "file" },
            modified_at: metadata.modified().ok().and_then(system_time_secs),
            name,
            path: child.path().display().to_string(),
            size: if is_dir { None } else { Some(metadata.len()) },
        });
    }
    entries.sort_by(|left, right| {
        (left.kind != "directory")
            .cmp(&(right.kind != "directory"))
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });
    let parent = target
        .parent()
        .filter(|parent| *parent != target)
        .map(|parent| parent.display().to_string())
        .unwrap_or_default();
    Ok(DesktopFileBrowserSnapshot {
        cwd: target.display().to_string(),
        entries,
        parent,
        roots: desktop_file_browser_roots(state),
    })
}

fn desktop_browse_target(
    project_root: &Path,
    app_root: &Path,
    raw_path: Option<&str>,
) -> DesktopResult<PathBuf> {
    let trimmed = raw_path.unwrap_or("").trim();
    let mut target = if trimmed.is_empty() {
        app_root.to_path_buf()
    } else {
        expand_home_path(PathBuf::from(trimmed))
    };
    if !target.is_absolute() {
        target = project_root.join(target);
    }
    Ok(target.canonicalize().unwrap_or(target))
}

fn desktop_file_browser_roots(state: &DesktopState) -> Vec<DesktopFileBrowserRoot> {
    let mut roots = Vec::new();
    let mut seen = Vec::new();
    push_desktop_file_browser_root(&mut roots, &mut seen, "Shinsekai", state.app_root.clone());
    push_desktop_file_browser_root(&mut roots, &mut seen, "Data", state.app_root.join("data"));
    if let Some(home) = desktop_home_dir() {
        push_desktop_file_browser_root(&mut roots, &mut seen, "Home", home);
    }
    for root in [&state.app_root, &state.project_root] {
        if let Some(anchor) = root
            .canonicalize()
            .unwrap_or_else(|_| root.to_path_buf())
            .ancestors()
            .last()
            .map(Path::to_path_buf)
        {
            let label = anchor.display().to_string();
            push_desktop_file_browser_root(&mut roots, &mut seen, &label, anchor);
        }
    }
    #[cfg(windows)]
    {
        for letter in b'A'..=b'Z' {
            let label = format!("{}:", letter as char);
            push_desktop_file_browser_root(
                &mut roots,
                &mut seen,
                &label,
                PathBuf::from(format!("{label}/")),
            );
        }
    }
    roots
}

fn push_desktop_file_browser_root(
    roots: &mut Vec<DesktopFileBrowserRoot>,
    seen: &mut Vec<String>,
    label: &str,
    path: PathBuf,
) {
    let resolved = path.canonicalize().unwrap_or(path);
    if !resolved.exists() {
        return;
    }
    let value = resolved.display().to_string();
    let key = desktop_file_browser_root_key(&value);
    if seen.iter().any(|item| item == &key) {
        return;
    }
    seen.push(key);
    roots.push(DesktopFileBrowserRoot {
        label: desktop_file_browser_root_label(label, &value),
        path: value,
    });
}

fn desktop_file_browser_root_key(value: &str) -> String {
    #[cfg(windows)]
    {
        value.to_ascii_lowercase().replace('\\', "/")
    }
    #[cfg(not(windows))]
    {
        value.to_string()
    }
}

fn desktop_file_browser_root_label(label: &str, path: &str) -> String {
    if label == "Home" {
        return "Home".to_string();
    }
    if label == "Data" {
        return "Data".to_string();
    }
    if label == "Shinsekai" {
        return "Shinsekai".to_string();
    }
    if label.trim().is_empty() {
        path.to_string()
    } else {
        label.to_string()
    }
}

fn expand_home_path(path: PathBuf) -> PathBuf {
    let raw = path.as_os_str().to_string_lossy();
    if raw == "~" {
        return desktop_home_dir().unwrap_or(path);
    }
    if let Some(rest) = raw.strip_prefix("~/") {
        if let Some(home) = desktop_home_dir() {
            return home.join(rest);
        }
    }
    path
}

fn desktop_home_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        env::var_os("USERPROFILE").map(PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        env::var_os("HOME").map(PathBuf::from)
    }
}

fn system_time_secs(value: SystemTime) -> Option<f64> {
    value
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_secs_f64())
}

fn bootstrap_runtime(app: AppHandle) {
    restart_debug_log("bootstrap_runtime start");
    let state = app.state::<DesktopState>();
    let scan = runtime::scan_runtime_view(&app, &state.source_root);
    state.set_runtime(DesktopRuntimePhase::Checking {
        view: Some(scan.clone()),
    });
    if scan.selected_candidate_id.is_none() {
        restart_debug_log("bootstrap_runtime needs action; no ready runtime candidate");
        state.set_runtime(DesktopRuntimePhase::NeedsAction { view: scan });
        return;
    }

    let result = runtime::find_python_runtime_for_candidate(
        &app,
        &state.source_root,
        scan.selected_candidate_id.as_deref(),
    )
    .map_err(|error| error.to_string())
    .and_then(|runtime| start_bridge_for_state(&state, runtime).map_err(|error| error.to_string()));

    match result {
        Ok(()) => {
            let view = runtime::scan_runtime_view(&app, &state.source_root);
            restart_debug_log("bootstrap_runtime ready");
            state.set_runtime(DesktopRuntimePhase::Ready { view: Some(view) });
            if let Err(error) = navigate_main_window_to_live_frontend(&app, state.bridge_port) {
                restart_debug_log(format!(
                    "bootstrap_runtime frontend navigate failed error={error}"
                ));
            }
        }
        Err(message) => {
            let view = runtime::scan_runtime_view(&app, &state.source_root);
            restart_debug_log(format!("bootstrap_runtime missing/error message={message}"));
            state.set_runtime(DesktopRuntimePhase::Error {
                message,
                view: Some(view),
            })
        }
    }
}

fn app_window_url(port: u16) -> String {
    let bridge_url = format!("http://{BRIDGE_HOST}:{port}");
    let encoded = bridge_url.replace(':', "%3A").replace('/', "%2F");
    format!("index.html?shinsekai_bridge={encoded}#/settings/api")
}

fn live_frontend_url(port: u16) -> String {
    let bridge_url = format!("http://{BRIDGE_HOST}:{port}");
    let encoded = bridge_url.replace(':', "%3A").replace('/', "%2F");
    let reload_token = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().to_string())
        .unwrap_or_else(|_| "0".to_string());
    format!(
        "{LIVE_FRONTEND_SCHEME}://localhost/?shinsekai_bridge={encoded}&shinsekai_reload={reload_token}#/settings/api"
    )
}

fn navigate_main_window_to_live_frontend(app: &AppHandle, bridge_port: u16) -> Result<(), String> {
    let url = Url::parse(&live_frontend_url(bridge_port)).map_err(|error| error.to_string())?;
    if let Some(window) = app.get_webview_window("main") {
        restart_debug_log(format!("navigate live frontend url={url}"));
        window.navigate(url).map_err(|error| error.to_string())?;
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
        runtime,
    )?;
    let mut child = Some(BridgeProcess::new(bridge.child));
    if let Ok(mut bridge_process) = state.bridge.lock() {
        if bridge_process.is_none() {
            *bridge_process = child.take();
            restart_debug_log("start_bridge_for_state stored bridge process");
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
        .arg("--project-root")
        .arg(&project_root)
        .arg("--app-root")
        .arg(&app_root)
        .arg("--frontend-dist")
        .arg(&frontend_dist)
        .current_dir(&source_root);

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

fn resolve_project_root(app: &tauri::App) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_PROJECT_ROOT") {
        fs::create_dir_all(&root)?;
        return Ok(root);
    }

    let data_dir = app.path().app_data_dir()?.join("project");
    fs::create_dir_all(&data_dir)?;
    Ok(data_dir)
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
