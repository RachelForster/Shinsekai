//! Delayed desktop relaunch helpers that intentionally survive desktop exit.

use std::{env, ffi::OsString, path::Path, process::Command};

#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{AppHandle, Manager, State};

use crate::state::{restart_debug_log, restart_debug_log_path, DesktopState};

#[cfg(unix)]
unsafe extern "C" {
    fn setsid() -> i32;
}

#[tauri::command]
pub(crate) fn desktop_app_restart(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    restart_debug_log("desktop_app_restart command received");
    restart_desktop_app(&app, &state)
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
