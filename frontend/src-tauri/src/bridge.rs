use std::{
    env,
    ffi::OsString,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::Path,
    process::{Child, Command},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{AppHandle, Manager, State};

use crate::{
    runtime,
    state::{
        restart_debug_log, restart_debug_log_path, DesktopResult, DesktopState, BRIDGE_HOST,
        DEFAULT_BRIDGE_PORT,
    },
};

const BRIDGE_STOP_TIMEOUT: Duration = Duration::from_secs(5);
const BRIDGE_CHAT_CLOSE_TIMEOUT: Duration = Duration::from_secs(3);

#[cfg(unix)]
unsafe extern "C" {
    fn setsid() -> i32;
}

pub(crate) struct BridgeProcess {
    child: Mutex<Option<Child>>,
    pub(crate) candidate_id: Option<String>,
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

    pub(crate) fn stop(&self) {
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
                match send_bridge_agent_close(self.bridge_port, &self.auth_token) {
                    Ok(()) => restart_debug_log("bridge stop closed Agent runtime"),
                    Err(error) => {
                        restart_debug_log(format!("bridge stop Agent close failed error={error}"))
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

#[tauri::command]
pub(crate) fn desktop_app_restart(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    restart_debug_log("desktop_app_restart command received");
    restart_desktop_app(&app, &state)
}

pub(crate) fn start_bridge_for_state(
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
    {
        if crate::state::show_backend_console() {
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

    wait_for_bridge(&mut child, port)?;
    restart_debug_log(format!(
        "spawn_bridge health ready child_pid={} port={}",
        child.id(),
        port
    ));
    Ok(BridgeLaunch { child })
}

fn sanitize_python_environment(command: &mut Command) {
    command.env_remove("PYTHONHOME").env_remove("PYTHONPATH");

    if env::var_os("APPIMAGE").is_some() || env::var_os("APPDIR").is_some() {
        command.env_remove("LD_LIBRARY_PATH");
    }
}

pub(crate) fn choose_bridge_port() -> DesktopResult<u16> {
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

pub(crate) fn request_bridge_chat_close(state: &DesktopState, reason: &str) {
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

pub(crate) fn send_bridge_chat_close(port: u16, auth_token: &str) -> Result<(), String> {
    send_bridge_close_request(
        port,
        auth_token,
        "/api/chat/close",
        BRIDGE_CHAT_CLOSE_TIMEOUT,
    )
}

pub(crate) fn send_bridge_agent_close(port: u16, auth_token: &str) -> Result<(), String> {
    send_bridge_close_request(
        port,
        auth_token,
        "/api/agent/runtime/stop",
        Duration::from_secs(7),
    )
}

fn send_bridge_close_request(
    port: u16,
    auth_token: &str,
    path: &str,
    timeout: Duration,
) -> Result<(), String> {
    let addr: SocketAddr = format!("{BRIDGE_HOST}:{port}")
        .parse::<SocketAddr>()
        .map_err(|error| error.to_string())?;
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(200))
        .map_err(|error| error.to_string())?;
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_read_timeout(Some(timeout));
    let request = format!(
        "POST {path} HTTP/1.1\r\nHost: {BRIDGE_HOST}\r\nContent-Type: application/json\r\nX-Shinsekai-Bridge-Token: {auth_token}\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
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

pub(crate) fn restart_desktop_app(app: &AppHandle, state: &DesktopState) -> Result<(), String> {
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

pub(crate) fn shutdown_desktop_app(app: &AppHandle, state: &DesktopState, reason: &str) {
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
