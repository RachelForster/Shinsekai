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
use path_contract::{
    canonicalize_directory_following_links_stably, canonicalize_directory_without_links,
    canonicalize_regular_file_without_links, files_have_same_identity, metadata_is_link,
    open_directory_without_links, open_regular_file_without_links, path_has_no_link_components,
    path_is_filesystem_root, path_text_is_portable, ExecutableSnapshot,
};
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
use std::os::unix::{fs::OpenOptionsExt, process::CommandExt};
#[cfg(windows)]
use std::os::windows::{fs::OpenOptionsExt, process::CommandExt};

mod desktop_files;
mod path_contract;
mod project_root;
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
#[cfg(windows)]
const SHOW_BACKEND_CONSOLE_ENV: &str = "SHINSEKAI_SHOW_BACKEND_CONSOLE";
const BRIDGE_STOP_TIMEOUT: Duration = Duration::from_secs(5);
const BRIDGE_CHAT_CLOSE_TIMEOUT: Duration = Duration::from_secs(3);
#[cfg(windows)]
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;

#[cfg(unix)]
unsafe extern "C" {
    fn setsid() -> i32;
}

struct BridgeProcess {
    child: Mutex<Option<Child>>,
    candidate_id: Option<String>,
    bridge_port: u16,
    auth_token: String,
}

impl BridgeProcess {
    fn new(
        child: Child,
        candidate_id: Option<String>,
        bridge_port: u16,
        auth_token: String,
    ) -> Self {
        Self {
            child: Mutex::new(Some(child)),
            candidate_id,
            bridge_port,
            auth_token,
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
                match send_bridge_chat_close(self.bridge_port, &self.auth_token) {
                    Ok(()) => restart_debug_log(format!(
                        "bridge stop closed active chat port={}",
                        self.bridge_port
                    )),
                    Err(error) => restart_debug_log(format!(
                        "bridge stop chat close failed port={} error={error}",
                        self.bridge_port
                    )),
                }
                let mut forced_kill_sent = match request_bridge_child_stop(&mut child) {
                    Ok(forced) => forced,
                    Err(error) => {
                        restart_debug_log(format!("bridge stop terminate failed error={error}"));
                        false
                    }
                };
                let graceful_deadline = Instant::now() + Duration::from_secs(1);
                let started = Instant::now();
                loop {
                    match child.try_wait() {
                        Ok(Some(status)) => {
                            restart_debug_log(format!("bridge stop completed status={status}"));
                            break;
                        }
                        Ok(None) if !forced_kill_sent && Instant::now() >= graceful_deadline => {
                            if let Err(error) = child.kill() {
                                restart_debug_log(format!("bridge stop kill failed error={error}"));
                            }
                            forced_kill_sent = true;
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

#[cfg(unix)]
fn request_bridge_child_stop(child: &mut Child) -> Result<bool, String> {
    let result = unsafe { libc::kill(child.id() as libc::pid_t, libc::SIGTERM) };
    if result == 0 {
        Ok(false)
    } else {
        Err(std::io::Error::last_os_error().to_string())
    }
}

#[cfg(windows)]
fn request_bridge_child_stop(child: &mut Child) -> Result<bool, String> {
    child.kill().map_err(|error| error.to_string())?;
    Ok(true)
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
        dependency_install_failed: bool,
    },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntimeView {
    status: &'static str,
    message: Option<String>,
    bridge_url: String,
    manual_install_command: Option<String>,
    selected_candidate_id: Option<String>,
    recommended_action: Option<runtime::RuntimeRepairActionKind>,
    candidates: Vec<runtime::RuntimeCandidateView>,
}

struct DesktopState {
    source_root: PathBuf,
    project_root: PathBuf,
    project_root_controller: project_root::ProjectRootController,
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
        project_root_controller: project_root::ProjectRootController,
        app_root: PathBuf,
        frontend_dist: PathBuf,
        bridge_port: u16,
        bridge_auth_token: String,
    ) -> Self {
        Self {
            source_root,
            project_root,
            project_root_controller,
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
                dependency_install_failed: false,
            });
        let (status, message, scan_view, dependency_install_failed) = match phase {
            DesktopRuntimePhase::Checking { view } => ("checking", None, view, false),
            DesktopRuntimePhase::NeedsAction { view } => {
                ("needsAction", view.message.clone(), Some(view), false)
            }
            DesktopRuntimePhase::Updating { view } => ("updating", None, view, false),
            DesktopRuntimePhase::Ready { view } => ("ready", None, view, false),
            DesktopRuntimePhase::Error {
                message,
                view,
                dependency_install_failed,
            } => ("error", Some(message), view, dependency_install_failed),
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
        let manual_install_command = dependency_install_failed
            .then(|| {
                runtime::manual_install_command(
                    &self.source_root,
                    candidates
                        .iter()
                        .find(|candidate| candidate.selected)
                        .or_else(|| candidates.first()),
                )
            })
            .flatten();
        DesktopRuntimeView {
            status,
            message,
            bridge_url: self.bridge_url(),
            manual_install_command,
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
            desktop_project_root_status,
            desktop_project_root_select,
            desktop_files_browse,
            desktop_restart_debug_log,
            desktop_app_restart,
            desktop_bridge_restart,
            desktop_frontend_reload,
            desktop_window_hide,
            desktop_chat_window_destroy,
            desktop_window_minimize,
            desktop_window_set_always_on_top,
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

            WebviewWindowBuilder::new(app, "main", WebviewUrl::App(url.into()))
                .title("Shinsekai")
                .inner_size(1180.0, 780.0)
                .min_inner_size(860.0, 620.0)
                .decorations(false)
                .shadow(true)
                .center()
                .build()?;

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

fn should_bootstrap_runtime(project_root_requires_selection: bool) -> bool {
    !project_root_requires_selection
}

fn project_root_setup_log_event(project_root_requires_selection: bool) -> &'static str {
    if project_root_requires_selection {
        "setup awaiting project-root selection"
    } else {
        "setup resolved"
    }
}

fn restart_debug_log_path() -> Option<PathBuf> {
    restart_debug_log_path_value(
        env::var_os("SHINSEKAI_RESTART_LOG"),
        env::temp_dir(),
        env::current_exe().ok().as_deref(),
    )
}

fn restart_debug_log_path_value(
    value: Option<OsString>,
    temp_dir: PathBuf,
    executable: Option<&Path>,
) -> Option<PathBuf> {
    if let Some(path) = value
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .filter(|path| restart_debug_log_path_is_valid(path))
    {
        return Some(path);
    }
    if restart_debug_log_path_is_valid(&temp_dir) {
        return Some(temp_dir.join(RESTART_DEBUG_LOG_FILE));
    }
    executable
        .filter(|path| restart_debug_log_path_is_valid(path))
        .and_then(Path::parent)
        .map(|parent| parent.join(RESTART_DEBUG_LOG_FILE))
}

fn restart_debug_log_path_is_valid(path: &Path) -> bool {
    path.is_absolute() && path_text_is_portable(path) && path_has_no_link_components(path)
}

fn restart_debug_log(message: impl AsRef<str>) {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| format!("{}.{:03}", duration.as_secs(), duration.subsec_millis()))
        .unwrap_or_else(|_| "time-error".to_string());
    let message = sanitize_restart_debug_log_message(message.as_ref());
    let line = format!(
        "ts={} pid={} component=desktop {}\n",
        timestamp,
        std::process::id(),
        message
    );
    eprint!("[restart-debug] {}", line);
    let Some(log_path) = restart_debug_log_path() else {
        return;
    };
    let _ = append_restart_debug_log(&log_path, line.as_bytes());
}

fn append_restart_debug_log(log_path: &Path, line: &[u8]) -> std::io::Result<()> {
    if !path_has_no_link_components(log_path) {
        return Err(std::io::Error::other(
            "restart log must not contain symbolic links or reparse points",
        ));
    }
    let parent_path = log_path.parent().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "restart log has no parent directory",
        )
    })?;
    let parent_identity = open_directory_without_links(parent_path)?;
    let mut options = OpenOptions::new();
    options.append(true).create(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW);
    #[cfg(windows)]
    options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    let mut file = options.open(log_path)?;
    let path_metadata = fs::symlink_metadata(log_path)?;
    if metadata_is_link(&path_metadata)
        || !file.metadata()?.is_file()
        || !path_has_no_link_components(log_path)
    {
        return Err(std::io::Error::other(
            "restart log changed to a non-regular or linked file",
        ));
    }
    let current_parent = open_directory_without_links(parent_path)?;
    if !files_have_same_identity(&parent_identity, &current_parent)? {
        return Err(std::io::Error::other(
            "restart log parent directory changed identity",
        ));
    }
    let verification = open_regular_file_without_links(log_path)?;
    if !files_have_same_identity(&file, &verification)? {
        return Err(std::io::Error::other(
            "restart log changed to a different regular file",
        ));
    }
    let final_parent = open_directory_without_links(parent_path)?;
    if !files_have_same_identity(&parent_identity, &final_parent)? {
        return Err(std::io::Error::other(
            "restart log parent directory changed identity",
        ));
    }
    file.write_all(line)
}

fn sanitize_restart_debug_log_message(message: &str) -> String {
    message
        .replace('\0', "\\0")
        .replace('\r', "\\r")
        .replace('\n', "\\n")
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

#[tauri::command]
fn desktop_project_root_status(state: State<'_, DesktopState>) -> project_root::ProjectRootStatus {
    state.project_root_controller.status()
}

#[tauri::command]
fn desktop_project_root_select(
    state: State<'_, DesktopState>,
    path: String,
) -> Result<project_root::ProjectRootStatus, String> {
    restart_debug_log(format!(
        "desktop_project_root_select command received path={path}"
    ));
    state.project_root_controller.select(&path)
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

fn restart_desktop_app(app: &AppHandle, state: &DesktopState) -> Result<(), String> {
    let env = app.env();
    let exe = tauri::process::current_binary(&env).map_err(|error| error.to_string())?;
    let working_directory = restart_working_directory(&exe)?;
    let args = env.args_os.iter().skip(1).cloned().collect::<Vec<_>>();
    restart_debug_log(format!(
        "restart begin exe={} working_directory={} args_count={} bridge_port={}",
        exe.display(),
        working_directory.display(),
        args.len(),
        state.bridge_port
    ));
    spawn_delayed_restart(
        &exe,
        &args,
        &working_directory,
        std::process::id(),
        state.bridge_port,
    )?;
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

fn restart_working_directory(exe: &Path) -> Result<PathBuf, String> {
    if !exe.is_absolute() {
        return Err(format!(
            "desktop restart executable must be absolute: {}",
            exe.display()
        ));
    }
    let executable = canonicalize_regular_file_without_links(exe).map_err(|error| {
        format!(
            "desktop restart executable is missing, linked, or changed ({}): {error}",
            exe.display()
        )
    })?;
    let parent = executable.parent().ok_or_else(|| {
        format!(
            "desktop restart executable has no parent directory: {}",
            executable.display()
        )
    })?;
    canonicalize_directory_without_links(parent).map_err(|error| {
        format!(
            "desktop restart working directory is missing, linked, or changed ({}): {error}",
            parent.display()
        )
    })
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
const POSIX_RESTART_HELPER_SCRIPT: &str = r#"while kill -0 "$1" 2>/dev/null; do sleep 0.1; done; sleep 0.8; exe="$2"; shift 2; "$exe" "$@" >/dev/null 2>&1 & child=$!; sleep 0.2; if kill -0 "$child" 2>/dev/null; then exit 0; fi; wait "$child"; exit "$?""#;

#[cfg(target_os = "windows")]
const WINDOWS_RESTART_HELPER_SCRIPT: &str = r#"
$parentProcessId = [int]$args[0]
$exe = $args[1]
$argv = @()
if ($args.Length -gt 2) {
  $argv = $args[2..($args.Length - 1)]
}
try { Wait-Process -Id $parentProcessId -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 800
Start-Process -FilePath $exe -ArgumentList $argv
"#;

fn require_restart_launch_paths(
    target: &ExecutableSnapshot,
    working_directory: &Path,
    working_directory_identity: &fs::File,
    helper: &ExecutableSnapshot,
) -> Result<(), String> {
    target
        .require_current()
        .map_err(|error| format!("desktop restart executable changed: {error}"))?;
    helper
        .require_current()
        .map_err(|error| format!("desktop restart helper changed: {error}"))?;
    let current_directory = open_directory_without_links(working_directory).map_err(|error| {
        format!(
            "desktop restart working directory changed ({}): {error}",
            working_directory.display()
        )
    })?;
    if !files_have_same_identity(working_directory_identity, &current_directory)
        .map_err(|error| error.to_string())?
    {
        return Err("desktop restart working directory changed identity".to_string());
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn spawn_delayed_restart(
    exe: &Path,
    args: &[OsString],
    working_directory: &Path,
    pid: u32,
    _port: u16,
) -> Result<(), String> {
    restart_debug_log(format!(
        "spawn_delayed_restart posix exe={} working_directory={} parent_pid={} port={}",
        exe.display(),
        working_directory.display(),
        pid,
        _port
    ));
    let target = ExecutableSnapshot::capture(
        exe.to_str()
            .ok_or_else(|| "desktop restart executable is not UTF-8".to_string())?,
    )
    .map_err(|error| format!("desktop restart executable is invalid: {error}"))?;
    let helper = ExecutableSnapshot::capture("sh")
        .map_err(|error| format!("desktop restart shell is unavailable: {error}"))?;
    let working_directory_identity = open_directory_without_links(working_directory)
        .map_err(|error| format!("desktop restart working directory is invalid: {error}"))?;
    require_restart_launch_paths(
        &target,
        working_directory,
        &working_directory_identity,
        &helper,
    )?;
    let mut command = Command::new(helper.path());
    command
        .arg("-c")
        .arg(POSIX_RESTART_HELPER_SCRIPT)
        .arg("shinsekai-restart")
        .arg(pid.to_string())
        .arg(target.path())
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
    command.current_dir(working_directory);
    match command.spawn() {
        Ok(mut child) => {
            if let Err(error) = require_restart_launch_paths(
                &target,
                working_directory,
                &working_directory_identity,
                &helper,
            ) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
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
    working_directory: &Path,
    pid: u32,
    _port: u16,
) -> Result<(), String> {
    restart_debug_log(format!(
        "spawn_delayed_restart windows exe={} working_directory={} parent_pid={} port={}",
        exe.display(),
        working_directory.display(),
        pid,
        _port
    ));
    let target = ExecutableSnapshot::capture(
        exe.to_str()
            .ok_or_else(|| "desktop restart executable is not UTF-8".to_string())?,
    )
    .map_err(|error| format!("desktop restart executable is invalid: {error}"))?;
    let helper = ExecutableSnapshot::capture("powershell")
        .map_err(|error| format!("desktop restart PowerShell is unavailable: {error}"))?;
    let working_directory_identity = open_directory_without_links(working_directory)
        .map_err(|error| format!("desktop restart working directory is invalid: {error}"))?;
    require_restart_launch_paths(
        &target,
        working_directory,
        &working_directory_identity,
        &helper,
    )?;
    let mut command = Command::new(helper.path());
    command
        .arg("-NoProfile")
        .arg("-WindowStyle")
        .arg("Hidden")
        .arg("-Command")
        .arg(WINDOWS_RESTART_HELPER_SCRIPT)
        .arg(pid.to_string())
        .arg(target.path())
        .args(args);
    command.creation_flags(0x0000_0008 | 0x0000_0200 | 0x0800_0000);
    command.current_dir(working_directory);
    match command.spawn() {
        Ok(mut child) => {
            if let Err(error) = require_restart_launch_paths(
                &target,
                working_directory,
                &working_directory_identity,
                &helper,
            ) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
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
fn desktop_window_hide(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_chat_window_destroy(window: WebviewWindow) -> Result<(), String> {
    if window.label() != "chat" {
        return Err("desktop_chat_window_destroy is only available to the chat window".to_string());
    }
    window.destroy().map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_window_minimize(window: WebviewWindow) -> Result<(), String> {
    window.minimize().map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_window_set_always_on_top(
    window: WebviewWindow,
    always_on_top: bool,
) -> Result<(), String> {
    window
        .set_always_on_top(always_on_top)
        .map_err(|error| error.to_string())
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
#[cfg(target_os = "windows")]
fn desktop_open_chat_window(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
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
fn desktop_open_chat_window(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
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
        navigate_chat_window_to_live_frontend(app, bridge_port, auth_token)?;
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct ChatWindowOpenPlan {
    defer_command: bool,
    navigate_after_create: bool,
    focus_after_show: bool,
}

fn current_chat_window_open_plan() -> ChatWindowOpenPlan {
    chat_window_open_plan_for_windows(cfg!(target_os = "windows"))
}

fn chat_window_open_plan_for_windows(is_windows: bool) -> ChatWindowOpenPlan {
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
fn desktop_open_external_url(url: String) -> Result<(), String> {
    let url = validated_external_url(&url)?;
    open_external_url(&url)
}

fn validated_external_url(raw: &str) -> Result<String, String> {
    if raw.is_empty()
        || raw != raw.trim()
        || raw.contains('\\')
        || raw.chars().any(char::is_control)
    {
        return Err("external URL contains non-portable characters".to_string());
    }
    let parsed = Url::parse(raw).map_err(|_| "external URL is invalid".to_string())?;
    if !matches!(parsed.scheme(), "http" | "https")
        || parsed.host_str().is_none()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
    {
        return Err("only credential-free http(s) URLs can be opened externally".to_string());
    }
    Ok(parsed.to_string())
}

fn spawn_with_executable_snapshot(
    mut command: Command,
    executable: &ExecutableSnapshot,
) -> Result<(), String> {
    executable
        .require_current()
        .map_err(|error| format!("system launcher changed before spawn: {error}"))?;
    if let Some(parent) = executable.path().parent() {
        command.current_dir(parent);
    }
    let mut child = command.spawn().map_err(|error| error.to_string())?;
    if let Err(error) = executable.require_current() {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!("system launcher changed during spawn: {error}"));
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn open_external_url(url: &str) -> Result<(), String> {
    let executable = ExecutableSnapshot::capture("open")
        .map_err(|error| format!("macOS URL launcher is unavailable: {error}"))?;
    let mut command = Command::new(executable.path());
    command.arg(url);
    spawn_with_executable_snapshot(command, &executable)
}

#[cfg(target_os = "windows")]
fn open_external_url(url: &str) -> Result<(), String> {
    let executable = ExecutableSnapshot::capture("rundll32")
        .map_err(|error| format!("Windows URL launcher is unavailable: {error}"))?;
    let mut command = Command::new(executable.path());
    command.args(["url.dll,FileProtocolHandler", url]);
    command.creation_flags(0x0800_0000);
    spawn_with_executable_snapshot(command, &executable)
}

#[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
fn open_external_url(url: &str) -> Result<(), String> {
    let executable = ExecutableSnapshot::capture("xdg-open")
        .map_err(|error| format!("desktop URL launcher is unavailable: {error}"))?;
    let mut command = Command::new(executable.path());
    command.arg(url);
    spawn_with_executable_snapshot(command, &executable)
}

fn bootstrap_runtime(app: AppHandle) {
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

#[cfg(not(target_os = "windows"))]
fn navigate_chat_window_to_live_frontend(
    app: &AppHandle,
    bridge_port: u16,
    auth_token: &str,
) -> Result<(), String> {
    navigate_window_to_live_frontend(
        app,
        "chat",
        &live_chat_frontend_url(bridge_port, auth_token),
    )
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
    if open_regular_file_without_links(&index_path).is_err() {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend index.html not found");
    }

    if request_path.is_empty() || request_path == "/" || request_path == "/index.html" {
        return protocol_file_response(&index_path);
    }

    for root in frontend_dist_roots(&raw_dist) {
        if let Some(candidate) = resolve_static_request_path(&root, request_path) {
            if open_regular_file_without_links(&candidate).is_ok() {
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
    if !path_has_no_link_components(raw_dist) {
        return raw_dist.to_path_buf();
    }
    let Some(frontend_dir) = raw_dist.parent() else {
        return raw_dist.to_path_buf();
    };
    let Ok(frontend_directory) = open_directory_without_links(frontend_dir) else {
        return raw_dist.to_path_buf();
    };
    let marker = frontend_dir.join(FRONTEND_DIST_MARKER);
    let Ok(mut marker_file) = open_regular_file_without_links(&marker) else {
        return raw_dist.to_path_buf();
    };
    let mut marker_text = String::new();
    if marker_file.read_to_string(&mut marker_text).is_err() {
        return raw_dist.to_path_buf();
    }
    let marker_value = marker_text
        .strip_suffix('\n')
        .and_then(|value| value.strip_suffix('\r').or(Some(value)))
        .unwrap_or(&marker_text);
    if marker_value.is_empty()
        || marker_value != marker_value.trim()
        || marker_value.contains('\\')
        || marker_value
            .split('/')
            .any(|component| component.is_empty() || matches!(component, "." | ".."))
    {
        return raw_dist.to_path_buf();
    }
    let relative = Path::new(marker_value);
    if relative.is_absolute()
        || !path_text_is_portable(relative)
        || !relative
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
    {
        return raw_dist.to_path_buf();
    }

    let Ok(frontend_root) = canonicalize_directory_without_links(frontend_dir) else {
        return raw_dist.to_path_buf();
    };
    let selected_target = frontend_root.join(relative);
    let Ok(target) = canonicalize_directory_without_links(&selected_target) else {
        return raw_dist.to_path_buf();
    };
    if !target.starts_with(&frontend_root)
        || open_regular_file_without_links(&target.join("index.html")).is_err()
    {
        return raw_dist.to_path_buf();
    }
    let Ok(current_frontend_directory) = open_directory_without_links(frontend_dir) else {
        return raw_dist.to_path_buf();
    };
    let Ok(mut current_marker_file) = open_regular_file_without_links(&marker) else {
        return raw_dist.to_path_buf();
    };
    let mut current_marker_text = String::new();
    if current_marker_file
        .read_to_string(&mut current_marker_text)
        .is_err()
        || current_marker_text != marker_text
    {
        return raw_dist.to_path_buf();
    }
    if !files_have_same_identity(&frontend_directory, &current_frontend_directory).unwrap_or(false)
        || !files_have_same_identity(&marker_file, &current_marker_file).unwrap_or(false)
    {
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
        let frontend_root = canonicalize_directory_without_links(frontend_dir).ok();
        let releases_root = canonicalize_directory_without_links(&releases_dir)
            .ok()
            .filter(|releases_root| {
                frontend_root
                    .as_ref()
                    .is_some_and(|frontend_root| releases_root.starts_with(frontend_root))
            });
        if let Some(releases_root) = releases_root {
            let Ok(releases_directory) = open_directory_without_links(&releases_root) else {
                return roots;
            };
            let Ok(entries) = fs::read_dir(&releases_root) else {
                return roots;
            };
            let mut release_dirs = entries
                .filter_map(Result::ok)
                .filter(|entry| {
                    let path = entry.path();
                    path_has_no_link_components(&path)
                        && entry.file_type().is_ok_and(|file_type| file_type.is_dir())
                })
                .filter_map(|entry| canonicalize_directory_without_links(&entry.path()).ok())
                .filter(|path| path.starts_with(&releases_root))
                .collect::<Vec<_>>();
            let Ok(current_releases_directory) = open_directory_without_links(&releases_root)
            else {
                return roots;
            };
            if !files_have_same_identity(&releases_directory, &current_releases_directory)
                .unwrap_or(false)
            {
                return roots;
            }
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
    let Ok(resolved) = canonicalize_directory_without_links(&root) else {
        return;
    };
    if open_regular_file_without_links(&resolved.join("index.html")).is_err() {
        return;
    }
    if !roots.iter().any(|candidate| candidate == &resolved) {
        roots.push(resolved);
    }
}

fn resolve_static_request_path(root: &Path, request_path: &str) -> Option<PathBuf> {
    let decoded = percent_decode_path(request_path)?;
    if !decoded.starts_with('/') || decoded.starts_with("//") {
        return None;
    }
    let relative = Path::new(&decoded[1..]);
    if !path_text_is_portable(relative) {
        return None;
    }
    let root = canonicalize_directory_without_links(root).ok()?;
    let mut target = root.clone();
    for part in decoded[1..].split('/') {
        if part.is_empty() || matches!(part, "." | "..") || part.contains('\\') {
            return None;
        }
        target.push(part);
    }
    if !target.starts_with(&root) {
        return None;
    }
    (open_regular_file_without_links(&target).is_ok()
        || open_directory_without_links(&target).is_ok())
    .then_some(target)
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
    let Ok(mut file) = open_regular_file_without_links(path) else {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend file not found");
    };
    let mut body = Vec::new();
    if file.read_to_end(&mut body).is_err() {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend file not found");
    }
    let Ok(mut verification_file) = open_regular_file_without_links(path) else {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend file not found");
    };
    if !files_have_same_identity(&file, &verification_file).unwrap_or(false) {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend file changed");
    }
    let mut verification_body = Vec::new();
    if verification_file
        .read_to_end(&mut verification_body)
        .is_err()
        || verification_body != body
    {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend file changed");
    }
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
    fn runtime_backend_console_truthy_values_are_case_insensitive() {
        for value in ["1", "true", "TRUE", "yes", "Yes", "on", "ON"] {
            assert!(
                is_truthy_env_value(value),
                "expected {value:?} to be truthy"
            );
        }
    }

    #[test]
    fn runtime_backend_console_rejects_other_values() {
        for value in ["", "0", "false", "off", "y", " true "] {
            assert!(
                !is_truthy_env_value(value),
                "expected {value:?} to be falsey"
            );
        }
    }

    #[test]
    fn external_urls_use_one_parsed_http_identity() {
        assert_eq!(
            validated_external_url("https://example.com/docs?q=path#section").unwrap(),
            "https://example.com/docs?q=path#section"
        );
        assert_eq!(
            validated_external_url("http://127.0.0.1:8787").unwrap(),
            "http://127.0.0.1:8787/"
        );
    }

    #[test]
    fn external_urls_reject_ambiguous_or_non_http_values() {
        for value in [
            "",
            " https://example.com",
            "https://example.com ",
            "https://example.com\\@attacker.test",
            "https://example.com/\nnext",
            "https://user:secret@example.com/",
            "file:///tmp/example",
            "https://",
        ] {
            assert!(
                validated_external_url(value).is_err(),
                "expected {value:?} to be rejected"
            );
        }
    }

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
    fn resolve_published_frontend_dist_rejects_nonportable_marker_components() {
        let root = temp_test_dir("published-dist-nonportable-marker");
        let frontend = root.join("frontend");
        let raw_dist = frontend.join("dist");
        fs::create_dir_all(&raw_dist).unwrap();
        fs::write(raw_dist.join("index.html"), "current").unwrap();

        for marker in [
            ".dist-releases/name:stream",
            ".dist-releases/CON",
            ".dist-releases/release ",
        ] {
            fs::write(frontend.join(FRONTEND_DIST_MARKER), marker).unwrap();
            assert_eq!(resolve_published_frontend_dist(&raw_dist), raw_dist);
        }

        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn frontend_dist_candidate_rejects_a_linked_root() {
        let root = temp_test_dir("linked-frontend-dist-root");
        let real_dist = root.join("real-dist");
        let linked_dist = root.join("dist");
        fs::create_dir_all(&real_dist).unwrap();
        fs::write(real_dist.join("index.html"), "linked").unwrap();
        std::os::unix::fs::symlink(&real_dist, &linked_dist).unwrap();

        assert!(frontend_dist_with_index(&linked_dist).is_none());
        let error = explicit_env_path_without_leaf_alias(
            "SHINSEKAI_FRONTEND_DIST",
            Some(linked_dist.into_os_string()),
        )
        .unwrap_err();
        assert!(error.contains("symbolic link"));
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn frontend_dist_environment_rejects_a_linked_parent() {
        let root = temp_test_dir("linked-frontend-dist-parent");
        let real_parent = root.join("real-parent");
        let linked_parent = root.join("linked-parent");
        let dist = real_parent.join("dist");
        fs::create_dir_all(&dist).unwrap();
        fs::write(dist.join("index.html"), "linked parent").unwrap();
        std::os::unix::fs::symlink(&real_parent, &linked_parent).unwrap();

        let error = explicit_env_path_without_leaf_alias(
            "SHINSEKAI_FRONTEND_DIST",
            Some(linked_parent.join("dist").into_os_string()),
        )
        .unwrap_err();

        assert!(error.contains("symbolic link"));
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn resolve_published_frontend_dist_rejects_a_linked_marker() {
        let root = temp_test_dir("published-dist-linked-marker");
        let frontend = root.join("frontend");
        let raw_dist = frontend.join("dist");
        let release = frontend.join(FRONTEND_DIST_RELEASES).join("v2");
        let external_marker = root.join("external-marker");
        fs::create_dir_all(&raw_dist).unwrap();
        fs::create_dir_all(&release).unwrap();
        fs::write(raw_dist.join("index.html"), "old").unwrap();
        fs::write(release.join("index.html"), "new").unwrap();
        fs::write(&external_marker, format!("{FRONTEND_DIST_RELEASES}/v2\n")).unwrap();
        std::os::unix::fs::symlink(&external_marker, frontend.join(FRONTEND_DIST_MARKER)).unwrap();

        assert_eq!(resolve_published_frontend_dist(&raw_dist), raw_dist);
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn resolve_published_frontend_dist_rejects_a_linked_release_path() {
        let root = temp_test_dir("published-dist-linked-release");
        let frontend = root.join("frontend");
        let raw_dist = frontend.join("dist");
        let releases = frontend.join(FRONTEND_DIST_RELEASES);
        let real_release = releases.join("real-v2");
        let linked_release = releases.join("current-v2");
        fs::create_dir_all(&raw_dist).unwrap();
        fs::create_dir_all(&real_release).unwrap();
        fs::write(raw_dist.join("index.html"), "old").unwrap();
        fs::write(real_release.join("index.html"), "new").unwrap();
        std::os::unix::fs::symlink(&real_release, &linked_release).unwrap();
        fs::write(
            frontend.join(FRONTEND_DIST_MARKER),
            format!("{FRONTEND_DIST_RELEASES}/current-v2\n"),
        )
        .unwrap();

        assert_eq!(resolve_published_frontend_dist(&raw_dist), raw_dist);
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn frontend_dist_roots_reject_a_linked_releases_root() {
        let root = temp_test_dir("published-dist-linked-releases-root");
        let frontend = root.join("frontend");
        let raw_dist = frontend.join("dist");
        let real_releases = frontend.join("real-releases");
        let release = real_releases.join("v2");
        fs::create_dir_all(&raw_dist).unwrap();
        fs::create_dir_all(&release).unwrap();
        fs::write(raw_dist.join("index.html"), "current").unwrap();
        fs::write(release.join("index.html"), "linked").unwrap();
        std::os::unix::fs::symlink(&real_releases, frontend.join(FRONTEND_DIST_RELEASES)).unwrap();

        assert_eq!(
            frontend_dist_roots(&raw_dist),
            vec![raw_dist.canonicalize().unwrap()]
        );
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn frontend_dist_roots_ignore_symlinked_release_directories() {
        let root = temp_test_dir("published-dist-symlink");
        let raw_dist = root.join("frontend").join("dist");
        let releases = root.join("frontend").join(FRONTEND_DIST_RELEASES);
        let outside = root.join("outside-release");
        fs::create_dir_all(&raw_dist).unwrap();
        fs::create_dir_all(&releases).unwrap();
        fs::create_dir_all(&outside).unwrap();
        fs::write(raw_dist.join("index.html"), "current").unwrap();
        fs::write(outside.join("index.html"), "outside").unwrap();
        std::os::unix::fs::symlink(&outside, releases.join("outside")).unwrap();

        assert_eq!(
            frontend_dist_roots(&raw_dist),
            vec![raw_dist.canonicalize().unwrap()]
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn resolve_static_request_path_rejects_parent_and_backslash_segments() {
        let test_root = temp_test_dir("static-request-path");
        let root = test_root.join("frontend-dist");
        let asset = root.join("web-assets").join("app.js");
        fs::create_dir_all(asset.parent().unwrap()).unwrap();
        fs::write(&asset, "asset").unwrap();

        assert_eq!(
            resolve_static_request_path(&root, "/web-assets/app.js").unwrap(),
            asset.canonicalize().unwrap()
        );
        assert!(resolve_static_request_path(&root, "/../secret").is_none());
        assert!(resolve_static_request_path(&root, "/web-assets\\secret.js").is_none());
        assert!(resolve_static_request_path(&root, "/web-assets//app.js").is_none());
        assert!(resolve_static_request_path(&root, "/web-assets/./app.js").is_none());
        assert!(resolve_static_request_path(&root, "//web-assets/app.js").is_none());
        assert!(resolve_static_request_path(&root, "/web-assets/name:stream").is_none());
        assert!(resolve_static_request_path(&root, "/web-assets/CON").is_none());
        assert!(resolve_static_request_path(&root, "/web-assets/app.js%20").is_none());
        let _ = fs::remove_dir_all(test_root);
    }

    #[cfg(unix)]
    #[test]
    fn resolve_static_request_path_rejects_symlinks_outside_frontend_root() {
        let test_root = temp_test_dir("static-request-symlink");
        let root = test_root.join("frontend-dist");
        let outside = test_root.join("outside.txt");
        fs::create_dir_all(&root).unwrap();
        fs::write(&outside, "secret").unwrap();
        std::os::unix::fs::symlink(&outside, root.join("asset.js")).unwrap();

        assert!(resolve_static_request_path(&root, "/asset.js").is_none());
        let _ = fs::remove_dir_all(test_root);
    }

    #[cfg(unix)]
    #[test]
    fn bridge_launch_snapshot_rejects_replaced_directories_and_files() {
        let root = temp_test_dir("bridge-launch-path-replacement");
        let directory = root.join("source");
        let moved_directory = root.join("moved-source");
        let bridge = root.join("frontend_bridge.py");
        let moved_bridge = root.join("moved-frontend_bridge.py");
        fs::create_dir_all(&directory).unwrap();
        fs::write(&bridge, "captured").unwrap();
        let directories = [("source root", directory.clone())];
        let files = [("frontend bridge", bridge.clone())];

        let (directory_identities, file_identities) =
            capture_bridge_launch_path_identities(&directories, &files).unwrap();
        fs::rename(&directory, &moved_directory).unwrap();
        fs::create_dir(&directory).unwrap();
        let error = revalidate_bridge_launch_path_identities(
            &directories,
            &directory_identities,
            &files,
            &file_identities,
        )
        .unwrap_err();
        assert!(error.to_string().contains("source root changed"));

        fs::remove_dir(&directory).unwrap();
        fs::rename(&moved_directory, &directory).unwrap();
        let (directory_identities, file_identities) =
            capture_bridge_launch_path_identities(&directories, &files).unwrap();
        fs::rename(&bridge, &moved_bridge).unwrap();
        fs::write(&bridge, "replacement").unwrap();
        let error = revalidate_bridge_launch_path_identities(
            &directories,
            &directory_identities,
            &files,
            &file_identities,
        )
        .unwrap_err();
        assert!(error.to_string().contains("frontend bridge changed"));

        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn resolve_static_request_path_rejects_internal_symlink_aliases() {
        let test_root = temp_test_dir("static-request-internal-symlink");
        let root = test_root.join("frontend-dist");
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("real.js"), "asset").unwrap();
        std::os::unix::fs::symlink(root.join("real.js"), root.join("asset.js")).unwrap();

        assert!(resolve_static_request_path(&root, "/asset.js").is_none());
        let _ = fs::remove_dir_all(test_root);
    }

    #[cfg(unix)]
    #[test]
    fn resolve_static_request_path_rejects_a_linked_root() {
        let test_root = temp_test_dir("static-request-linked-root");
        let real_root = test_root.join("real-frontend-dist");
        let linked_root = test_root.join("frontend-dist");
        fs::create_dir_all(&real_root).unwrap();
        fs::write(real_root.join("asset.js"), "asset").unwrap();
        std::os::unix::fs::symlink(&real_root, &linked_root).unwrap();

        assert!(resolve_static_request_path(&linked_root, "/asset.js").is_none());
        let _ = fs::remove_dir_all(test_root);
    }

    #[cfg(unix)]
    #[test]
    fn live_frontend_protocol_rejects_a_linked_index() {
        let test_root = temp_test_dir("static-linked-index");
        let root = test_root.join("frontend-dist");
        let outside = test_root.join("outside.html");
        fs::create_dir_all(&root).unwrap();
        fs::write(&outside, "secret").unwrap();
        std::os::unix::fs::symlink(&outside, root.join("index.html")).unwrap();
        let frontend_dist = Arc::new(Mutex::new(Some(root)));

        let response = serve_live_frontend_protocol(&frontend_dist, "/");

        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        assert_ne!(response.body(), b"secret");
        let _ = fs::remove_dir_all(test_root);
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
    fn canonical_existing_app_root_rejects_nonportable_resolved_paths() {
        let root = temp_test_dir("canonical-app-root");
        let target = root.join("target:with-colon");
        fs::create_dir_all(&target).unwrap();

        assert!(canonical_existing_app_root(&target).is_none());

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn explicit_runtime_roots_reject_relative_environment_values() {
        let error = explicit_env_path_value(
            "SHINSEKAI_APP_ROOT",
            Some(OsString::from("relative-app-root")),
        )
        .unwrap_err();

        assert!(error.contains("SHINSEKAI_APP_ROOT must be an absolute path"));
    }

    #[test]
    fn explicit_runtime_roots_reject_user_home_aliases() {
        let error =
            explicit_env_path_value("SHINSEKAI_APP_ROOT", Some(OsString::from("~/application")))
                .unwrap_err();

        assert!(error.contains("SHINSEKAI_APP_ROOT must be an absolute path"));
    }

    #[test]
    fn explicit_runtime_roots_reject_present_but_empty_environment_values() {
        let error =
            explicit_env_path_value("SHINSEKAI_APP_ROOT", Some(OsString::new())).unwrap_err();

        assert!(error.contains("SHINSEKAI_APP_ROOT must not be empty"));
    }

    #[test]
    fn explicit_runtime_roots_reject_filesystem_root() {
        let current = std::env::current_dir().unwrap();
        let filesystem_root = current.ancestors().last().unwrap().to_path_buf();

        let error = explicit_env_path_value(
            "SHINSEKAI_APP_ROOT",
            Some(filesystem_root.clone().into_os_string()),
        )
        .unwrap_err();

        assert!(error.contains("must not be a filesystem root"));
        assert!(app_root_from_executable(&filesystem_root.join("shinsekai")).is_none());
    }

    #[test]
    fn explicit_runtime_roots_preserve_absolute_nonexistent_paths() {
        let root = temp_test_dir("absolute-env-root");
        let candidate = root.join("not-created-yet");

        assert_eq!(
            explicit_env_path_value(
                "SHINSEKAI_FRONTEND_DIST",
                Some(candidate.clone().into_os_string()),
            )
            .unwrap(),
            Some(candidate)
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn explicit_runtime_roots_reject_nonportable_environment_values() {
        let root = temp_test_dir("nonportable-env-root");
        let candidate = root.join("bad\nroot");

        let error = explicit_env_path_value("SHINSEKAI_APP_ROOT", Some(candidate.into_os_string()))
            .unwrap_err();

        assert!(error.contains("non-portable path characters"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn explicit_runtime_roots_reject_lexical_aliases() {
        let root = temp_test_dir("aliased-env-root");
        let candidate = OsString::from(format!("{}/./app", root.display()));

        let error = explicit_env_path_value("SHINSEKAI_APP_ROOT", Some(candidate)).unwrap_err();

        assert!(error.contains("non-portable path characters"));
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn explicit_runtime_roots_reject_nonportable_canonical_targets() {
        let root = temp_test_dir("nonportable-canonical-env-root");
        let target = root.join("target:with-colon");
        fs::create_dir_all(&target).unwrap();
        let alias = root.join("portable-alias");
        std::os::unix::fs::symlink(&target, &alias).unwrap();

        let error = explicit_env_path_value("SHINSEKAI_APP_ROOT", Some(alias.into_os_string()))
            .unwrap_err();

        assert!(error.contains("resolves to a path containing non-portable characters"));
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn explicit_runtime_roots_reject_non_utf8_environment_values() {
        use std::os::unix::ffi::OsStringExt;

        let value = OsString::from_vec(vec![b'/', b't', b'm', b'p', b'/', 0xff]);
        let error = explicit_env_path_value("SHINSEKAI_APP_ROOT", Some(value)).unwrap_err();

        assert!(error.contains("non-portable path characters"));
    }

    #[test]
    fn project_root_conflict_defers_runtime_bootstrap() {
        assert!(!should_bootstrap_runtime(true));
        assert!(should_bootstrap_runtime(false));
    }

    #[test]
    fn unresolved_project_root_is_not_logged_as_a_recovery_source() {
        assert_eq!(
            project_root_setup_log_event(true),
            "setup awaiting project-root selection"
        );
        assert_eq!(project_root_setup_log_event(false), "setup resolved");
    }

    #[test]
    fn restart_debug_log_messages_cannot_inject_additional_lines() {
        assert_eq!(
            sanitize_restart_debug_log_message("safe\r\nsetup resolved injected\0"),
            "safe\\r\\nsetup resolved injected\\0"
        );
    }

    #[cfg(not(target_os = "windows"))]
    #[test]
    fn delayed_restart_helper_never_reopens_the_restart_log_by_path() {
        assert!(!POSIX_RESTART_HELPER_SCRIPT.contains("restart-helper"));
        assert!(!POSIX_RESTART_HELPER_SCRIPT.contains(">>"));
        assert!(POSIX_RESTART_HELPER_SCRIPT.contains("shift 2"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn delayed_restart_helper_never_reopens_the_restart_log_by_path() {
        assert!(!WINDOWS_RESTART_HELPER_SCRIPT.contains("Add-Content"));
        assert!(!WINDOWS_RESTART_HELPER_SCRIPT.contains("$log"));
        assert!(WINDOWS_RESTART_HELPER_SCRIPT.contains("$args[2.."));
    }

    #[cfg(unix)]
    #[test]
    fn restart_debug_log_append_does_not_follow_a_symbolic_link() {
        use std::os::unix::fs::symlink;

        let root = temp_test_dir("restart-log-link");
        fs::create_dir_all(&root).unwrap();
        let target = root.join("target.log");
        let link = root.join("restart.log");
        fs::write(&target, "keep\n").unwrap();
        symlink(&target, &link).unwrap();

        assert!(append_restart_debug_log(&link, b"blocked\n").is_err());
        assert_eq!(fs::read_to_string(target).unwrap(), "keep\n");
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn restart_debug_log_append_rejects_an_intermediate_symbolic_link() {
        use std::os::unix::fs::symlink;

        let root = temp_test_dir("restart-log-parent-link");
        let external = root.join("external");
        let alias = root.join("alias");
        fs::create_dir_all(&external).unwrap();
        symlink(&external, &alias).unwrap();

        assert!(append_restart_debug_log(&alias.join("restart.log"), b"blocked\n").is_err());
        assert!(!external.join("restart.log").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn restart_debug_log_contract_rejects_an_intermediate_symbolic_link() {
        use std::os::unix::fs::symlink;

        let root = temp_test_dir("restart-log-contract-parent-link");
        let external = root.join("external");
        let alias = root.join("alias");
        fs::create_dir_all(&external).unwrap();
        symlink(&external, &alias).unwrap();

        assert!(!restart_debug_log_path_is_valid(&alias.join("restart.log")));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn restart_debug_log_ignores_relative_environment_path() {
        let temp_dir = temp_test_dir("restart-log-temp");
        let executable = temp_test_dir("restart-log-exe").join("shinsekai");

        assert_eq!(
            restart_debug_log_path_value(
                Some(OsString::from("relative.log")),
                temp_dir.clone(),
                Some(&executable),
            ),
            Some(temp_dir.join(RESTART_DEBUG_LOG_FILE))
        );
    }

    #[test]
    fn restart_debug_log_does_not_expand_user_home_alias() {
        let temp_dir = temp_test_dir("restart-log-home-alias-temp");
        let executable = temp_test_dir("restart-log-home-alias-exe").join("shinsekai");

        assert_eq!(
            restart_debug_log_path_value(
                Some(OsString::from("~/restart.log")),
                temp_dir.clone(),
                Some(&executable),
            ),
            Some(temp_dir.join(RESTART_DEBUG_LOG_FILE))
        );
    }

    #[test]
    fn restart_debug_log_ignores_nonportable_environment_path() {
        let temp_dir = temp_test_dir("restart-log-portable-temp");
        let executable = temp_test_dir("restart-log-portable-exe").join("shinsekai");
        let invalid = temp_dir.join("bad\nrestart.log");

        assert_eq!(
            restart_debug_log_path_value(
                Some(invalid.into_os_string()),
                temp_dir.clone(),
                Some(&executable),
            ),
            Some(temp_dir.join(RESTART_DEBUG_LOG_FILE))
        );
    }

    #[test]
    fn restart_debug_log_never_falls_back_to_process_cwd() {
        assert_eq!(
            restart_debug_log_path_value(
                Some(OsString::from("relative.log")),
                PathBuf::from("relative-temp"),
                Some(Path::new("relative-executable")),
            ),
            None
        );
    }

    #[test]
    fn restart_working_directory_comes_from_executable_not_process_cwd() {
        let root = temp_test_dir("restart-working-directory");
        let bin = root.join("bin");
        let executable = bin.join("shinsekai");
        fs::create_dir_all(&bin).unwrap();
        fs::write(&executable, "").unwrap();

        assert_eq!(
            restart_working_directory(&executable).unwrap(),
            bin.canonicalize().unwrap()
        );
        assert!(restart_working_directory(Path::new("relative/shinsekai")).is_err());
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
    fn windows_chat_window_open_plan_avoids_webview_timing_hazards() {
        let plan = chat_window_open_plan_for_windows(true);

        assert!(plan.defer_command);
        assert!(!plan.navigate_after_create);
        assert!(!plan.focus_after_show);
    }

    #[test]
    fn non_windows_chat_window_open_plan_keeps_existing_live_navigation() {
        let plan = chat_window_open_plan_for_windows(false);

        assert!(!plan.defer_command);
        assert!(plan.navigate_after_create);
        assert!(plan.focus_after_show);
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
    let mut child = Some(BridgeProcess::new(
        bridge.child,
        candidate_id.clone(),
        state.bridge_port,
        state.bridge_auth_token.clone(),
    ));
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
    let bridge = source_root.join("frontend_bridge.py");
    let project_data = project_root.join("data");
    let frontend_index = frontend_dist.join("index.html");
    let runtime_program = PathBuf::from(runtime.command.get_program());
    let directory_paths = [
        ("source root", source_root.to_path_buf()),
        ("project root", project_root.to_path_buf()),
        ("project data root", project_data),
        ("application root", app_root.to_path_buf()),
        ("frontend dist", frontend_dist.to_path_buf()),
    ];
    let file_paths = [
        ("Python runtime", runtime_program),
        ("frontend bridge", bridge.clone()),
        ("frontend index", frontend_index),
    ];
    let (directory_identities, file_identities) =
        capture_bridge_launch_path_identities(&directory_paths, &file_paths)?;
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

    if let Some(log_path) = restart_debug_log_path() {
        command.env("SHINSEKAI_RESTART_LOG", log_path);
    }
    command
        .arg(&bridge)
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

    revalidate_bridge_launch_path_identities(
        &directory_paths,
        &directory_identities,
        &file_paths,
        &file_identities,
    )?;

    #[cfg(windows)]
    {
        if show_backend_console() {
            const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;
            command.creation_flags(CREATE_NEW_CONSOLE);
        } else {
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
    }

    let mut child = command.spawn().map_err(|error| {
        restart_debug_log(format!("spawn_bridge failed error={error}"));
        format!(
            "failed to start Shinsekai Python bridge from {}: {error}",
            source_root.display()
        )
    })?;
    restart_debug_log(format!("spawn_bridge child_pid={}", child.id()));
    if let Err(error) = revalidate_bridge_launch_path_identities(
        &directory_paths,
        &directory_identities,
        &file_paths,
        &file_identities,
    ) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }

    wait_for_bridge(&mut child, port)?;
    if let Err(error) = revalidate_bridge_launch_path_identities(
        &directory_paths,
        &directory_identities,
        &file_paths,
        &file_identities,
    ) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    restart_debug_log(format!(
        "spawn_bridge health ready child_pid={} port={}",
        child.id(),
        port
    ));
    Ok(BridgeLaunch { child })
}

fn capture_bridge_launch_path_identities(
    directories: &[(&str, PathBuf)],
    files: &[(&str, PathBuf)],
) -> DesktopResult<(Vec<fs::File>, Vec<fs::File>)> {
    let mut directory_identities = Vec::with_capacity(directories.len());
    for (field, path) in directories {
        let identity = open_directory_without_links(path).map_err(|error| {
            format!(
                "cannot start the Python bridge because {field} is not a stable real directory ({}): {error}",
                path.display()
            )
        })?;
        directory_identities.push(identity);
    }
    let mut file_identities = Vec::with_capacity(files.len());
    for (field, path) in files {
        let identity = open_regular_file_without_links(path).map_err(|error| {
            format!(
                "cannot start the Python bridge because {field} is not a stable regular file ({}): {error}",
                path.display()
            )
        })?;
        file_identities.push(identity);
    }
    Ok((directory_identities, file_identities))
}

fn revalidate_bridge_launch_path_identities(
    directories: &[(&str, PathBuf)],
    directory_identities: &[fs::File],
    files: &[(&str, PathBuf)],
    file_identities: &[fs::File],
) -> DesktopResult<()> {
    if directories.len() != directory_identities.len() || files.len() != file_identities.len() {
        return Err("Python bridge launch path snapshot is incomplete".into());
    }
    for ((field, path), expected) in directories.iter().zip(directory_identities) {
        let current = open_directory_without_links(path).map_err(|error| {
            format!(
                "cannot start the Python bridge because {field} changed before launch ({}): {error}",
                path.display()
            )
        })?;
        if !files_have_same_identity(expected, &current)? {
            return Err(format!(
                "cannot start the Python bridge because {field} changed before launch: {}",
                path.display()
            )
            .into());
        }
    }
    for ((field, path), expected) in files.iter().zip(file_identities) {
        let current = open_regular_file_without_links(path).map_err(|error| {
            format!(
                "cannot start the Python bridge because {field} changed before launch ({}): {error}",
                path.display()
            )
        })?;
        if !files_have_same_identity(expected, &current)? {
            return Err(format!(
                "cannot start the Python bridge because {field} changed before launch: {}",
                path.display()
            )
            .into());
        }
    }
    Ok(())
}

#[cfg(windows)]
fn show_backend_console() -> bool {
    env::var(SHOW_BACKEND_CONSOLE_ENV)
        .map(|value| is_truthy_env_value(&value))
        .unwrap_or(false)
}

#[cfg(any(windows, test))]
fn is_truthy_env_value(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}

fn resolve_source_root(app: &tauri::App) -> DesktopResult<PathBuf> {
    if let Some(root) = explicit_env_path("SHINSEKAI_SOURCE_ROOT")? {
        if let Some(root) = source_root_with_bridge(&root) {
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
        if let Some(root) = source_root_with_bridge(&root) {
            return Ok(root);
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        if let Some(root) = source_root_with_bridge(&resource_dir) {
            return Ok(root);
        }
    }

    let exe_dir = env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    if let Some(root) = exe_dir {
        if let Some(root) = source_root_with_bridge(&root) {
            return Ok(root);
        }
    }

    Err("could not locate Shinsekai application resources; set SHINSEKAI_SOURCE_ROOT".into())
}

fn resolve_project_root(
    app: &tauri::App,
    source_root: &Path,
    app_root: &Path,
) -> DesktopResult<project_root::ResolvedProjectRoot> {
    let app_config_dir = app.path().app_config_dir()?;
    let app_data_dir = app.path().app_data_dir()?;
    let config_dir = app.path().config_dir()?;
    let data_dir = app.path().data_dir()?;
    let locator_path = app_config_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE);

    let raw_env = |name: &str| env::var_os(name);
    let explicit_root = project_root::preferred_environment_root(
        raw_env("SHINSEKAI_PROJECT_ROOT"),
        raw_env("EASYAI_PROJECT_ROOT"),
    );

    let legacy_config_dir = config_dir.join(project_root::LEGACY_APP_IDENTIFIER);
    let legacy_data_dir = data_dir.join(project_root::LEGACY_APP_IDENTIFIER);
    let current_data_dir = data_dir.join(project_root::CURRENT_APP_IDENTIFIER);
    let default_restart_log =
        restart_debug_log_path_value(None, env::temp_dir(), env::current_exe().ok().as_deref());
    let mut restart_log_paths: Vec<PathBuf> = default_restart_log.iter().cloned().collect();
    if let Some(custom_log) = env::var_os("SHINSEKAI_RESTART_LOG")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .filter(|path| restart_debug_log_path_is_valid(path))
        .filter(|path| default_restart_log.as_ref() != Some(path))
    {
        restart_log_paths.insert(0, custom_log);
    }

    let options = project_root::ProjectRootResolveOptions {
        explicit_root,
        source_root: source_root.to_path_buf(),
        app_root: app_root.to_path_buf(),
        current_app_data_project_root: app_data_dir.join("project"),
        legacy_app_data_project_roots: vec![legacy_data_dir.join("project")],
        locator_path,
        locator_read_paths: vec![
            app_data_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
            current_data_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
            legacy_config_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
            legacy_data_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
        ],
        restart_log_paths,
        untrusted_candidate_roots: project_root::windows_legacy_install_dir_hints(),
        development_source: dev_project_root().as_deref() == Some(source_root),
    };
    project_root::resolve(options).map_err(Into::into)
}

fn resolve_app_root(app: &tauri::App, source_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(root) = explicit_env_path("SHINSEKAI_APP_ROOT")? {
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

    if let Some(root) =
        app_root_from_current_exe().and_then(|root| canonical_existing_app_root(&root))
    {
        return Ok(root);
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        if let Some(root) = app_root_from_resource_dir(&resource_dir)
            .and_then(|root| canonical_existing_app_root(&root))
        {
            return Ok(root);
        }
    }

    Ok(source_root.to_path_buf())
}

fn appimage_app_root() -> Option<PathBuf> {
    env::var_os("APPIMAGE")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .filter(|path| path.is_absolute() && path_text_is_portable(path))
        .and_then(|path| canonicalize_regular_file_without_links(&path).ok())
        .and_then(|path| path.parent().map(Path::to_path_buf))
        .and_then(|path| canonical_existing_app_root(&path))
}

fn canonical_existing_app_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute()
        || path_is_filesystem_root(path)
        || !path_text_is_portable(path)
        || !path.is_dir()
    {
        return None;
    }
    let canonical = canonicalize_directory_following_links_stably(path).ok()?;
    (!path_is_filesystem_root(&canonical) && path_text_is_portable(&canonical)).then_some(canonical)
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
            return app_bundle
                .parent()
                .filter(|path| !path_is_filesystem_root(path))
                .map(Path::to_path_buf);
        }
    }

    executable
        .parent()
        .filter(|path| !path_is_filesystem_root(path))
        .map(Path::to_path_buf)
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
            return app_bundle
                .parent()
                .filter(|path| !path_is_filesystem_root(path))
                .map(Path::to_path_buf);
        }
    }

    if resource_dir.file_name().and_then(|name| name.to_str()) == Some("resources") {
        return resource_dir
            .parent()
            .filter(|path| !path_is_filesystem_root(path))
            .map(Path::to_path_buf);
    }
    (!path_is_filesystem_root(resource_dir)).then(|| resource_dir.to_path_buf())
}

fn dev_project_root() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let root = manifest_dir.parent()?.parent()?;
    Some(canonicalize_directory_following_links_stably(root).unwrap_or_else(|_| root.to_path_buf()))
}

fn source_root_with_bridge(root: &Path) -> Option<PathBuf> {
    if !root.is_absolute() || path_is_filesystem_root(root) || !path_text_is_portable(root) {
        return None;
    }
    let resolved = canonicalize_directory_following_links_stably(root).ok()?;
    if path_is_filesystem_root(&resolved) || !path_text_is_portable(&resolved) {
        return None;
    }
    open_regular_file_without_links(&resolved.join("frontend_bridge.py"))
        .is_ok()
        .then_some(resolved)
}

fn resolve_frontend_dist(source_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(dist) = explicit_env_path_without_leaf_alias(
        "SHINSEKAI_FRONTEND_DIST",
        env::var_os("SHINSEKAI_FRONTEND_DIST"),
    )? {
        if let Some(dist) = frontend_dist_with_index(&dist) {
            return Ok(dist);
        }
        return Err(format!(
            "SHINSEKAI_FRONTEND_DIST does not contain index.html: {}",
            dist.display()
        )
        .into());
    }

    let dist = source_root.join("frontend").join("dist");
    if let (Ok(source_root), Some(dist)) = (
        canonicalize_directory_without_links(source_root),
        frontend_dist_with_index(&dist),
    ) {
        if dist.starts_with(&source_root) {
            return Ok(dist);
        }
    }

    Err(format!(
        "built frontend not found at {}; run `pnpm build` in frontend first",
        dist.display()
    )
    .into())
}

fn frontend_dist_with_index(dist: &Path) -> Option<PathBuf> {
    let canonical = canonicalize_directory_without_links(dist).ok()?;
    open_regular_file_without_links(&canonical.join("index.html"))
        .is_ok()
        .then_some(canonical)
}

fn explicit_env_path(name: &str) -> DesktopResult<Option<PathBuf>> {
    explicit_env_path_value(name, env::var_os(name)).map_err(Into::into)
}

fn explicit_env_path_value(name: &str, value: Option<OsString>) -> Result<Option<PathBuf>, String> {
    let Some(path) = validated_explicit_env_path_value(name, value)? else {
        return Ok(None);
    };
    let canonical = if path.exists() {
        match canonicalize_directory_following_links_stably(&path) {
            Ok(canonical) => canonical,
            Err(error) => {
                // The strict opener intentionally rejects a non-portable
                // canonical target.  Preserve that precise configuration
                // diagnosis without relaxing the identity-bound open used
                // for any accepted directory.
                if let Ok(resolved) = path.canonicalize() {
                    if !path_text_is_portable(&resolved) {
                        return Err(format!(
                            "{name} resolves to a path containing non-portable characters: {}",
                            resolved.display()
                        ));
                    }
                }
                return Err(format!(
                    "{name} could not stably resolve its directory path ({}): {error}",
                    path.display()
                ));
            }
        }
    } else {
        path
    };
    if path_is_filesystem_root(&canonical) {
        return Err(format!("{name} must not resolve to a filesystem root"));
    }
    if !path_text_is_portable(&canonical) {
        return Err(format!(
            "{name} resolves to a path containing non-portable characters: {}",
            canonical.display()
        ));
    }
    Ok(Some(canonical))
}

fn explicit_env_path_without_leaf_alias(
    name: &str,
    value: Option<OsString>,
) -> Result<Option<PathBuf>, String> {
    let Some(path) = validated_explicit_env_path_value(name, value)? else {
        return Ok(None);
    };
    if !path_has_no_link_components(&path) {
        return Err(format!(
            "{name} contains a symbolic link or reparse-point component: {}",
            path.display()
        ));
    }
    Ok(Some(path))
}

fn validated_explicit_env_path_value(
    name: &str,
    value: Option<OsString>,
) -> Result<Option<PathBuf>, String> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_empty() {
        return Err(format!("{name} must not be empty"));
    }
    let path = PathBuf::from(value);
    if !path_text_is_portable(&path) {
        return Err(format!(
            "{name} contains non-portable path characters: {}",
            path.display()
        ));
    }
    if !path.is_absolute() {
        return Err(format!(
            "{name} must be an absolute path: {}",
            path.display()
        ));
    }
    if path_is_filesystem_root(&path) {
        return Err(format!("{name} must not be a filesystem root"));
    }
    Ok(Some(path))
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
