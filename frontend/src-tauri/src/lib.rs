use std::{
    env,
    error::Error,
    fs,
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use serde::Serialize;
use tauri::{AppHandle, Manager, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

mod runtime;

type DesktopResult<T> = Result<T, Box<dyn Error>>;

const BRIDGE_HOST: &str = "127.0.0.1";
const DEFAULT_BRIDGE_PORT: u16 = 8787;

struct BridgeProcess {
    child: Mutex<Option<Child>>,
}

impl BridgeProcess {
    fn new(child: Child) -> Self {
        Self {
            child: Mutex::new(Some(child)),
        }
    }
}

impl Drop for BridgeProcess {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut child) = child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

struct BridgeLaunch {
    child: Child,
}

#[derive(Clone)]
enum DesktopRuntimePhase {
    Checking,
    Missing { message: String },
    Updating,
    Ready,
    Error { message: String },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntimeView {
    status: &'static str,
    message: Option<String>,
    bridge_url: String,
}

struct DesktopState {
    source_root: PathBuf,
    project_root: PathBuf,
    frontend_dist: PathBuf,
    bridge_port: u16,
    bridge: Mutex<Option<BridgeProcess>>,
    runtime: Mutex<DesktopRuntimePhase>,
}

impl DesktopState {
    fn new(
        source_root: PathBuf,
        project_root: PathBuf,
        frontend_dist: PathBuf,
        bridge_port: u16,
    ) -> Self {
        Self {
            source_root,
            project_root,
            frontend_dist,
            bridge_port,
            bridge: Mutex::new(None),
            runtime: Mutex::new(DesktopRuntimePhase::Checking),
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

    fn runtime_view(&self) -> DesktopRuntimeView {
        let phase = self
            .runtime
            .lock()
            .map(|runtime| runtime.clone())
            .unwrap_or_else(|_| DesktopRuntimePhase::Error {
                message: "runtime state lock is poisoned".to_string(),
            });
        let (status, message) = match phase {
            DesktopRuntimePhase::Checking => ("checking", None),
            DesktopRuntimePhase::Missing { message } => ("missing", Some(message)),
            DesktopRuntimePhase::Updating => ("updating", None),
            DesktopRuntimePhase::Ready => ("ready", None),
            DesktopRuntimePhase::Error { message } => ("error", Some(message)),
        };
        DesktopRuntimeView {
            status,
            message,
            bridge_url: self.bridge_url(),
        }
    }
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            desktop_runtime_state,
            desktop_runtime_update,
            desktop_window_minimize,
            desktop_window_toggle_maximize,
            desktop_window_start_drag,
            desktop_window_close
        ])
        .setup(|app| {
            let source_root = resolve_source_root(app)?;
            let project_root = resolve_project_root(app, &source_root)?;
            let frontend_dist = resolve_frontend_dist(&source_root)?;
            let bridge_port = choose_bridge_port()?;
            let url = app_window_url(bridge_port);
            app.manage(DesktopState::new(
                source_root,
                project_root,
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
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Shinsekai desktop shell");
}

#[tauri::command]
fn desktop_runtime_state(state: State<'_, DesktopState>) -> DesktopRuntimeView {
    state.runtime_view()
}

#[tauri::command]
fn desktop_runtime_update(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<DesktopRuntimeView, String> {
    state.set_runtime(DesktopRuntimePhase::Updating);
    let result = runtime::repair_python_runtime(&app, &state.source_root)
        .map_err(|error| error.to_string())
        .and_then(|runtime_root| {
            if runtime_root.is_none() {
                return Err("no runtime package is available for this platform".to_string());
            }
            runtime::find_python_runtime(&app, &state.source_root)
                .map_err(|error| error.to_string())
        })
        .and_then(|runtime| {
            start_bridge_for_state(&state, runtime).map_err(|error| error.to_string())
        });

    match result {
        Ok(()) => state.set_runtime(DesktopRuntimePhase::Ready),
        Err(message) => state.set_runtime(DesktopRuntimePhase::Error { message }),
    }
    Ok(state.runtime_view())
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
fn desktop_window_close(window: WebviewWindow) -> Result<(), String> {
    window.close().map_err(|error| error.to_string())
}

fn bootstrap_runtime(app: AppHandle) {
    let state = app.state::<DesktopState>();
    state.set_runtime(DesktopRuntimePhase::Checking);
    let result = runtime::find_python_runtime(&app, &state.source_root)
        .map_err(|error| error.to_string())
        .and_then(|runtime| {
            start_bridge_for_state(&state, runtime).map_err(|error| error.to_string())
        });

    match result {
        Ok(()) => state.set_runtime(DesktopRuntimePhase::Ready),
        Err(message) => state.set_runtime(DesktopRuntimePhase::Missing { message }),
    }
}

fn app_window_url(port: u16) -> String {
    let bridge_url = format!("http://{BRIDGE_HOST}:{port}");
    let encoded = bridge_url.replace(':', "%3A").replace('/', "%2F");
    format!("index.html?shinsekai_bridge={encoded}#/settings/api")
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
        return Ok(());
    }

    let bridge = spawn_bridge(
        &state.source_root,
        &state.project_root,
        &state.frontend_dist,
        state.bridge_port,
        runtime,
    )?;
    let mut child = Some(BridgeProcess::new(bridge.child));
    if let Ok(mut bridge_process) = state.bridge.lock() {
        if bridge_process.is_none() {
            *bridge_process = child.take();
        }
    }
    Ok(())
}

fn spawn_bridge(
    source_root: &Path,
    project_root: &Path,
    frontend_dist: &Path,
    port: u16,
    runtime: runtime::PythonRuntime,
) -> DesktopResult<BridgeLaunch> {
    println!("Using Shinsekai Python runtime: {}", runtime.description);
    let mut command = runtime.command;
    sanitize_python_environment(&mut command);

    command
        .arg(source_root.join("frontend_bridge.py"))
        .arg("--host")
        .arg(BRIDGE_HOST)
        .arg("--port")
        .arg(port.to_string())
        .arg("--project-root")
        .arg(&project_root)
        .arg("--frontend-dist")
        .arg(&frontend_dist)
        .current_dir(&source_root);

    let mut child = command.spawn().map_err(|error| {
        format!(
            "failed to start Shinsekai Python bridge from {}: {error}",
            source_root.display()
        )
    })?;

    wait_for_bridge(&mut child, port)?;
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

fn resolve_project_root(app: &tauri::App, source_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_PROJECT_ROOT") {
        fs::create_dir_all(&root)?;
        return Ok(root);
    }

    if dev_project_root().as_deref() == Some(source_root) {
        return Ok(source_root.to_path_buf());
    }

    let data_dir = app.path().app_data_dir()?.join("project");
    fs::create_dir_all(&data_dir)?;
    Ok(data_dir)
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
        return Ok(port);
    }

    if TcpListener::bind((BRIDGE_HOST, DEFAULT_BRIDGE_PORT)).is_ok() {
        return Ok(DEFAULT_BRIDGE_PORT);
    }

    let listener = TcpListener::bind((BRIDGE_HOST, 0))?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_bridge(child: &mut Child, port: u16) -> DesktopResult<()> {
    let addr: SocketAddr = format!("{BRIDGE_HOST}:{port}").parse()?;
    let started = Instant::now();
    let timeout = Duration::from_secs(45);

    while started.elapsed() < timeout {
        if let Some(status) = child.try_wait()? {
            return Err(format!("Python bridge exited before startup completed: {status}").into());
        }

        if TcpStream::connect_timeout(&addr, Duration::from_millis(120)).is_ok() {
            return Ok(());
        }

        thread::sleep(Duration::from_millis(120));
    }

    Err(format!("timed out waiting for Python bridge on http://{BRIDGE_HOST}:{port}").into())
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
