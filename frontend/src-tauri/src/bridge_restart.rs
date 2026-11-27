use std::{
    env,
    ffi::OsString,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::Path,
    process::{Child, Command},
    thread,
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{AppHandle, Manager};

use crate::state::{restart_debug_log, restart_debug_log_path, DesktopState, BRIDGE_HOST};

const BRIDGE_STOP_TIMEOUT: Duration = Duration::from_secs(5);
const BRIDGE_CHAT_CLOSE_TIMEOUT: Duration = Duration::from_secs(6);
const BRIDGE_RUNTIME_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(7);

#[cfg(unix)]
unsafe extern "C" {
    fn setsid() -> i32;
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

pub(crate) fn send_bridge_runtime_shutdown(port: u16, auth_token: &str) -> Result<(), String> {
    send_bridge_close_request(
        port,
        auth_token,
        "/api/runtime/shutdown",
        BRIDGE_RUNTIME_SHUTDOWN_TIMEOUT,
    )
}

pub(crate) fn stop_bridge_child_process(mut child: Child, bridge_port: u16, auth_token: &str) {
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
    match send_bridge_agent_close(bridge_port, auth_token) {
        Ok(()) => restart_debug_log("bridge stop closed Agent runtime"),
        Err(error) => {
            restart_debug_log(format!("bridge stop Agent close failed error={error}"))
        }
    }
    match send_bridge_chat_close(bridge_port, auth_token) {
        Ok(()) => restart_debug_log(format!(
            "bridge stop closed active chat port={bridge_port}"
        )),
        Err(error) => restart_debug_log(format!(
            "bridge stop chat close failed port={bridge_port} error={error}"
        )),
    }
    match send_bridge_runtime_shutdown(bridge_port, auth_token) {
        Ok(()) => restart_debug_log(format!(
            "bridge stop shutdown managed runtime port={bridge_port}"
        )),
        Err(error) => restart_debug_log(format!(
            "bridge stop runtime shutdown failed port={bridge_port} error={error}"
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
pub(crate) fn spawn_delayed_restart(
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
pub(crate) fn spawn_delayed_restart(
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
