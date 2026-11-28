use std::{
    env,
    fs::{File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{AppHandle, State};

use crate::{
    bridge_restart::stop_bridge_child_process,
    process_guard::{assign_child_to_job, ChildProcessJob},
    runtime,
    state::{restart_debug_log, restart_debug_log_path, DesktopResult, DesktopState, BRIDGE_HOST, DEFAULT_BRIDGE_PORT},
};

pub(crate) use crate::bridge_restart::{request_bridge_chat_close, shutdown_desktop_app};
#[cfg(test)]
pub(crate) use crate::bridge_restart::{
    send_bridge_agent_close, send_bridge_chat_close, send_bridge_runtime_shutdown,
};

const BRIDGE_STDERR_TAIL_BYTES: usize = 4096;
const BRIDGE_STDERR_SUMMARY_MAX_CHARS: usize = 240;

pub(crate) struct BridgeProcess {
    child: Mutex<Option<Child>>,
    job: Mutex<Option<ChildProcessJob>>,
    pub(crate) candidate_id: Option<String>,
    bridge_port: u16,
    auth_token: String,
}

impl BridgeProcess {
    fn new(
        child: Child,
        job: Option<ChildProcessJob>,
        candidate_id: Option<String>,
        bridge_port: u16,
        auth_token: String,
    ) -> Self {
        Self {
            child: Mutex::new(Some(child)),
            job: Mutex::new(job),
            candidate_id,
            bridge_port,
            auth_token,
        }
    }

    pub(crate) fn stop(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(child) = child.take() {
                stop_bridge_child_process(child, self.bridge_port, &self.auth_token);
            }
        }
        if let Ok(mut job) = self.job.lock() {
            let _ = job.take();
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
    job: Option<ChildProcessJob>,
}

#[tauri::command]
pub(crate) fn desktop_app_restart(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    restart_debug_log("desktop_app_restart command received");
    crate::bridge_restart::restart_desktop_app(&app, &state)
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
        bridge.job,
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

    let stderr_log_path = (!crate::state::show_backend_console())
        .then(|| prepare_bridge_stderr_log(&mut command))
        .flatten();

    let mut child = command.spawn().map_err(|error| {
        restart_debug_log(format!("spawn_bridge failed error={error}"));
        format!(
            "failed to start Shinsekai Python bridge from {}: {error}",
            source_root.display()
        )
    })?;
    restart_debug_log(format!("spawn_bridge child_pid={}", child.id()));
    let job = match assign_child_to_job(&child) {
        Ok(job) => Some(job),
        Err(error) => {
            restart_debug_log(format!("spawn_bridge assign_child_to_job failed error={error}"));
            None
        }
    };

    wait_for_bridge(&mut child, port, stderr_log_path.as_deref())?;
    restart_debug_log(format!(
        "spawn_bridge health ready child_pid={} port={}",
        child.id(),
        port
    ));
    Ok(BridgeLaunch { child, job })
}

fn sanitize_python_environment(command: &mut Command) {
    command.env_remove("PYTHONHOME").env_remove("PYTHONPATH");

    if env::var_os("APPIMAGE").is_some() || env::var_os("APPDIR").is_some() {
        command.env_remove("LD_LIBRARY_PATH");
    }
}

pub(crate) fn port_pair_available(port: u16) -> bool {
    let Some(ws_port) = port.checked_add(1) else {
        return false;
    };
    let Ok(http_listener) = TcpListener::bind((BRIDGE_HOST, port)) else {
        return false;
    };
    TcpListener::bind((BRIDGE_HOST, ws_port))
        .map(|ws_listener| {
            drop(ws_listener);
            drop(http_listener);
        })
        .is_ok()
}

pub(crate) fn choose_bridge_port() -> DesktopResult<u16> {
    if let Ok(raw) = env::var("SHINSEKAI_BRIDGE_PORT") {
        let port = raw
            .parse::<u16>()
            .map_err(|_| format!("SHINSEKAI_BRIDGE_PORT is not a valid port: {raw}"))?;
        restart_debug_log(format!("choose_bridge_port env port={port}"));
        return Ok(port);
    }

    if port_pair_available(DEFAULT_BRIDGE_PORT) {
        restart_debug_log(format!(
            "choose_bridge_port default port={DEFAULT_BRIDGE_PORT}"
        ));
        return Ok(DEFAULT_BRIDGE_PORT);
    }

    let mut fallback_port = None;
    for _ in 0..8 {
        let listener = TcpListener::bind((BRIDGE_HOST, 0))?;
        let candidate = listener.local_addr()?.port();
        drop(listener);
        if candidate
            .checked_add(1)
            .is_some_and(|ws_port| TcpListener::bind((BRIDGE_HOST, ws_port)).is_ok())
        {
            restart_debug_log(format!(
                "choose_bridge_port default_busy paired_fallback_port={candidate}"
            ));
            return Ok(candidate);
        }
        fallback_port = Some(candidate);
    }

    let port = fallback_port.ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::AddrNotAvailable,
            "no bridge port available",
        )
    })?;
    restart_debug_log(format!(
        "choose_bridge_port default_busy fallback_port={port}"
    ));
    Ok(port)
}

fn bridge_stderr_log_path() -> PathBuf {
    env::temp_dir().join(format!("shinsekai-bridge-stderr-{}.log", std::process::id()))
}

fn prepare_bridge_stderr_log(command: &mut Command) -> Option<PathBuf> {
    let path = bridge_stderr_log_path();
    match OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&path)
    {
        Ok(file) => {
            command.stderr(Stdio::from(file));
            Some(path)
        }
        Err(error) => {
            restart_debug_log(format!(
                "spawn_bridge stderr log open failed path={} error={error}",
                path.display()
            ));
            None
        }
    }
}

fn read_bridge_stderr_tail(path: &Path) -> Option<String> {
    let mut file = File::open(path).ok()?;
    let len = file.metadata().ok()?.len();
    let start = len.saturating_sub(BRIDGE_STDERR_TAIL_BYTES as u64);
    file.seek(SeekFrom::Start(start)).ok()?;
    let mut buf = Vec::new();
    file.read_to_end(&mut buf).ok()?;
    let text = String::from_utf8_lossy(&buf);
    let trimmed = text.trim();
    (!trimmed.is_empty()).then(|| trimmed.to_string())
}

pub(crate) fn summarize_bridge_stderr(stderr_text: &str) -> Option<String> {
    let line = stderr_text
        .lines()
        .rev()
        .map(str::trim)
        .find(|line| !line.is_empty())?;
    let mut chars = line.chars();
    let truncated: String = chars
        .by_ref()
        .take(BRIDGE_STDERR_SUMMARY_MAX_CHARS)
        .collect();
    Some(if chars.next().is_some() {
        format!("{truncated}...")
    } else {
        truncated
    })
}

fn wait_for_bridge(
    child: &mut Child,
    port: u16,
    stderr_log_path: Option<&Path>,
) -> DesktopResult<()> {
    let addr: SocketAddr = format!("{BRIDGE_HOST}:{port}").parse()?;
    let started = Instant::now();
    let timeout = Duration::from_secs(45);
    restart_debug_log(format!(
        "wait_for_bridge start child_pid={} port={port}",
        child.id()
    ));

    while started.elapsed() < timeout {
        if let Some(status) = child.try_wait()? {
            let stderr_tail = stderr_log_path.and_then(read_bridge_stderr_tail);
            if let Some(tail) = &stderr_tail {
                restart_debug_log(format!(
                    "wait_for_bridge child exited before ready child_pid={} status={status} stderr={tail}",
                    child.id()
                ));
            } else {
                restart_debug_log(format!(
                    "wait_for_bridge child exited before ready child_pid={} status={status}",
                    child.id()
                ));
            }
            let summary = stderr_tail
                .as_deref()
                .and_then(summarize_bridge_stderr);
            let message = match summary {
                Some(summary) => {
                    format!("Python bridge exited before startup completed: {status} ({summary})")
                }
                None => format!("Python bridge exited before startup completed: {status}"),
            };
            return Err(message.into());
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
