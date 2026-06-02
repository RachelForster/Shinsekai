use std::{
    env,
    error::Error,
    ffi::OsString,
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command},
    sync::Mutex,
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{AppHandle, Manager, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

mod runtime;

type DesktopResult<T> = Result<T, Box<dyn Error>>;

const BRIDGE_HOST: &str = "127.0.0.1";
const DEFAULT_BRIDGE_PORT: u16 = 8787;
const RESTART_DEBUG_LOG_FILE: &str = "shinsekai-restart-debug.log";

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

    fn take_bridge(&self) -> Option<BridgeProcess> {
        self.bridge.lock().ok()?.take()
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
    restart_debug_log("run enter");
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            desktop_runtime_state,
            desktop_runtime_update,
            desktop_restart_debug_log,
            desktop_app_restart,
            desktop_bridge_restart,
            desktop_window_minimize,
            desktop_window_toggle_maximize,
            desktop_window_start_drag,
            desktop_window_close,
            desktop_open_external_url
        ])
        .setup(|app| {
            let source_root = resolve_source_root(app)?;
            let project_root = resolve_project_root(app)?;
            let frontend_dist = resolve_frontend_dist(&source_root)?;
            let bridge_port = choose_bridge_port()?;
            let url = app_window_url(bridge_port);
            restart_debug_log(format!(
                "setup resolved source_root={} project_root={} frontend_dist={} bridge_port={} url={}",
                source_root.display(),
                project_root.display(),
                frontend_dist.display(),
                bridge_port,
                url
            ));
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
fn desktop_restart_debug_log(message: String) {
    restart_debug_log(format!("frontend {}", message));
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

fn restart_bridge_for_state(
    app: &AppHandle,
    state: &DesktopState,
) -> Result<DesktopRuntimeView, String> {
    state.set_runtime(DesktopRuntimePhase::Checking);
    if let Some(bridge) = state.take_bridge() {
        restart_debug_log("desktop_bridge_restart stopping existing bridge");
        bridge.stop();
    } else {
        restart_debug_log("desktop_bridge_restart no existing bridge to stop");
    }

    let result = runtime::find_python_runtime(app, &state.source_root)
        .map_err(|error| error.to_string())
        .and_then(|runtime| {
            start_bridge_for_state(state, runtime).map_err(|error| error.to_string())
        });

    match result {
        Ok(()) => {
            restart_debug_log("desktop_bridge_restart ready");
            state.set_runtime(DesktopRuntimePhase::Ready);
            Ok(state.runtime_view())
        }
        Err(message) => {
            restart_debug_log(format!("desktop_bridge_restart failed message={message}"));
            state.set_runtime(DesktopRuntimePhase::Error {
                message: message.clone(),
            });
            Err(message)
        }
    }
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
    restart_debug_log("restart requested app.exit(0)");
    app.exit(0);
    Ok(())
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
fn desktop_window_close(window: WebviewWindow) -> Result<(), String> {
    window.close().map_err(|error| error.to_string())
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
    state.set_runtime(DesktopRuntimePhase::Checking);
    let result = runtime::find_python_runtime(&app, &state.source_root)
        .map_err(|error| error.to_string())
        .and_then(|runtime| {
            start_bridge_for_state(&state, runtime).map_err(|error| error.to_string())
        });

    match result {
        Ok(()) => {
            restart_debug_log("bootstrap_runtime ready");
            state.set_runtime(DesktopRuntimePhase::Ready)
        }
        Err(message) => {
            restart_debug_log(format!("bootstrap_runtime missing/error message={message}"));
            state.set_runtime(DesktopRuntimePhase::Missing { message })
        }
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
        restart_debug_log("start_bridge_for_state skipped; bridge already present");
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
            restart_debug_log("start_bridge_for_state stored bridge process");
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
    restart_debug_log(format!(
        "spawn_bridge runtime={} source_root={} project_root={} frontend_dist={} port={} parent_pid={}",
        runtime.description,
        source_root.display(),
        project_root.display(),
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
