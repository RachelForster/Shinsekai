use std::{
    error::Error,
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::Command,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{Emitter, Manager, Runtime};

use super::{manifest::RuntimeRequirements, python_env};

type RuntimeResult<T> = Result<T, Box<dyn Error>>;
const RUNTIME_PROGRESS_EVENT: &str = "shinsekai:runtime-progress";

fn configure_pip_install_command(
    command: &mut Command,
    python: &Path,
    pip_index_url: Option<&str>,
) {
    python_env::configure_pip_command(command, python);
    if let Some(url) = pip_index_url.map(str::trim).filter(|url| !url.is_empty()) {
        command.arg("-i").arg(url);
    }
}

fn ensure_python_pip_available(python: &Path) -> RuntimeResult<()> {
    if check_python_pip(python).is_ok() {
        return Ok(());
    }

    let mut ensurepip = Command::new(python);
    ensurepip
        .arg("-m")
        .arg("ensurepip")
        .arg("--upgrade")
        .arg("--default-pip");
    python_env::configure_pip_command(&mut ensurepip, python);
    if let Err(error) = run_command(&mut ensurepip, "bootstrap Python pip with ensurepip") {
        return Err(format!(
            "Python pip bootstrap failed for {}: {error}",
            python.display()
        )
        .into());
    }

    check_python_pip(python).map_err(|error| {
        format!(
            "Python pip is still not available for {} after ensurepip bootstrap: {}",
            python.display(),
            error
        )
        .into()
    })
}

fn check_python_pip(python: &Path) -> RuntimeResult<()> {
    let mut command = Command::new(python);
    command.arg("-m").arg("pip").arg("--version");
    python_env::configure_pip_command(&mut command, python);
    run_command(&mut command, "check Python pip")
}

fn install_runtime_requirements(
    python: &Path,
    requirements_path: &Path,
    pip_index_urls: &[String],
) -> RuntimeResult<()> {
    ensure_python_pip_available(python)?;
    let mut errors = Vec::new();

    if pip_index_urls.is_empty() {
        let mut install = pip_install_command(python, requirements_path, None);
        return run_command(&mut install, "install Shinsekai runtime dependencies");
    }

    for pip_index_url in pip_index_urls {
        let mut install = pip_install_command(python, requirements_path, Some(pip_index_url));
        match run_command(&mut install, "install Shinsekai runtime dependencies") {
            Ok(()) => return Ok(()),
            Err(error) => errors.push(format!("{}: {}", pip_index_url.trim(), error)),
        }
    }
    Err(format!(
        "install Shinsekai runtime dependencies failed from all configured pip indexes: {}",
        errors.join("; ")
    )
    .into())
}

fn pip_install_command(
    python: &Path,
    requirements_path: &Path,
    pip_index_url: Option<&str>,
) -> Command {
    let mut install = Command::new(python);
    install.arg("-m").arg("pip").arg("install");
    configure_pip_install_command(&mut install, python, pip_index_url);
    install.arg("-r").arg(requirements_path);
    install
}

pub fn install_runtime_dependencies<R: Runtime, M: Manager<R> + Emitter<R>>(
    app: &M,
    source_root: &Path,
    python: &Path,
    candidate_id: &str,
    profile: &str,
    requirements: &RuntimeRequirements,
    pip_index_urls: &[String],
) -> RuntimeResult<PathBuf> {
    if !python.is_file() {
        return Err(format!("runtime Python does not exist: {}", python.display()).into());
    }
    let runtime_home = runtime_home(app)?;
    let _install_lock = acquire_install_lock(&runtime_home)?;
    let candidate_id = safe_component(candidate_id);
    let requirements_path = requirements_path(source_root, &requirements.requirements_file);
    emit_runtime_progress(
        app,
        "installingDeps",
        Some(candidate_id.clone()),
        Some("local".to_string()),
        None,
        None,
        None,
        Some("Installing Shinsekai runtime dependencies"),
    );
    install_runtime_requirements(python, &requirements_path, pip_index_urls)?;

    emit_runtime_progress(
        app,
        "checkingBridge",
        Some(candidate_id.clone()),
        Some("local".to_string()),
        Some(2),
        Some(3),
        None,
        Some("Checking repaired runtime"),
    );
    verify_python_runtime(source_root, python, profile, requirements)?;
    emit_runtime_progress(
        app,
        "ready",
        Some(candidate_id),
        Some("local".to_string()),
        Some(3),
        Some(3),
        None,
        Some("Runtime dependencies are ready"),
    );
    Ok(python.to_path_buf())
}

fn verify_python_runtime(
    source_root: &Path,
    python: &Path,
    profile: &str,
    requirements: &RuntimeRequirements,
) -> RuntimeResult<()> {
    let bridge = source_root.join("frontend_bridge.py");
    let requirements_path = requirements_path(source_root, &requirements.requirements_file);
    let mut command = Command::new(python);
    command
        .arg(bridge)
        .arg("--check-runtime")
        .arg("--json")
        .arg("--profile")
        .arg(profile)
        .arg("--project-root")
        .arg(source_root)
        .arg("--requirements-file")
        .arg(requirements_path)
        .current_dir(source_root);
    python_env::configure_python_command(&mut command, python);
    run_command(&mut command, "check Shinsekai runtime")?;
    verify_python_imports(python, &requirements.imports)
}

fn verify_python_imports(python: &Path, modules: &[String]) -> RuntimeResult<()> {
    if modules.is_empty() {
        return Ok(());
    }
    let script = concat!(
        "import importlib, sys\n",
        "missing = []\n",
        "for name in sys.argv[1:]:\n",
        "    try:\n",
        "        importlib.import_module(name)\n",
        "    except Exception as exc:\n",
        "        missing.append(f'{name}: {exc}')\n",
        "if missing:\n",
        "    raise SystemExit('runtime import check failed: ' + '; '.join(missing))\n",
    );
    let mut command = Command::new(python);
    command.arg("-c").arg(script).args(modules);
    python_env::configure_python_command(&mut command, python);
    run_command(&mut command, "check Shinsekai runtime imports")
}

fn run_command(command: &mut Command, label: &str) -> RuntimeResult<()> {
    let output = command.output()?;
    if output.status.success() {
        return Ok(());
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(format!(
        "{label} failed with status {}. stdout: {} stderr: {}",
        output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "terminated".to_string()),
        stdout.trim(),
        stderr.trim()
    )
    .into())
}

fn runtime_home<R: Runtime>(app: &impl Manager<R>) -> RuntimeResult<PathBuf> {
    Ok(app.path().app_data_dir()?.join("runtime"))
}

struct InstallLock {
    path: PathBuf,
}

impl Drop for InstallLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn acquire_install_lock(runtime_home: &Path) -> RuntimeResult<InstallLock> {
    fs::create_dir_all(runtime_home)?;
    let lock_path = runtime_home.join("install.lock");
    if is_stale_lock(&lock_path) {
        let _ = fs::remove_file(&lock_path);
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lock_path)
        .map_err(|error| {
            format!(
                "another Shinsekai runtime install appears to be running ({}): {error}",
                lock_path.display()
            )
        })?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    writeln!(file, "pid={}", std::process::id())?;
    writeln!(file, "created_at_ms={now}")?;
    Ok(InstallLock { path: lock_path })
}

fn is_stale_lock(lock_path: &Path) -> bool {
    const STALE_LOCK_AFTER: Duration = Duration::from_secs(6 * 60 * 60);
    if lock_owner_has_exited(lock_path) {
        return true;
    }
    let Ok(metadata) = fs::metadata(lock_path) else {
        return false;
    };
    let Ok(modified) = metadata.modified() else {
        return false;
    };
    modified
        .elapsed()
        .map(|elapsed| elapsed > STALE_LOCK_AFTER)
        .unwrap_or(false)
}

fn lock_owner_has_exited(lock_path: &Path) -> bool {
    let Ok(text) = fs::read_to_string(lock_path) else {
        return false;
    };
    let Some(pid) = lock_pid_from_text(&text) else {
        return false;
    };
    process_has_exited(pid).unwrap_or(false)
}

fn lock_pid_from_text(text: &str) -> Option<u32> {
    text.lines()
        .find_map(|line| line.trim().strip_prefix("pid="))
        .and_then(|value| value.trim().parse::<u32>().ok())
        .filter(|pid| *pid > 0)
}

#[cfg(unix)]
fn process_has_exited(pid: u32) -> Option<bool> {
    if pid == std::process::id() {
        return Some(false);
    }
    let result = unsafe { libc::kill(pid as libc::pid_t, 0) };
    if result == 0 {
        return Some(false);
    }
    match last_errno() {
        libc::ESRCH => Some(true),
        libc::EPERM => Some(false),
        _ => None,
    }
}

#[cfg(target_os = "linux")]
fn last_errno() -> i32 {
    unsafe { *libc::__errno_location() }
}

#[cfg(any(target_os = "macos", target_os = "ios"))]
fn last_errno() -> i32 {
    unsafe { *libc::__error() }
}

#[cfg(all(
    unix,
    not(any(target_os = "linux", target_os = "macos", target_os = "ios"))
))]
fn last_errno() -> i32 {
    0
}

#[cfg(not(unix))]
fn process_has_exited(_pid: u32) -> Option<bool> {
    None
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeProgressPayload {
    phase: &'static str,
    candidate_id: Option<String>,
    source: Option<String>,
    downloaded: Option<u64>,
    total: Option<u64>,
    speed_bytes_per_sec: Option<f64>,
    message: Option<String>,
}

fn emit_runtime_progress<R: Runtime, M: Manager<R> + Emitter<R>>(
    app: &M,
    phase: &'static str,
    candidate_id: Option<String>,
    source: Option<String>,
    downloaded: Option<u64>,
    total: Option<u64>,
    speed_bytes_per_sec: Option<f64>,
    message: Option<&str>,
) {
    let _ = app.emit(
        RUNTIME_PROGRESS_EVENT,
        RuntimeProgressPayload {
            phase,
            candidate_id,
            source,
            downloaded,
            total,
            speed_bytes_per_sec,
            message: message.map(ToString::to_string),
        },
    );
}

fn requirements_path(source_root: &Path, requirements_file: &str) -> PathBuf {
    let path = PathBuf::from(requirements_file);
    if path.is_absolute() {
        path
    } else {
        source_root.join(path)
    }
}

fn safe_component(value: &str) -> String {
    let component = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.') {
                ch
            } else {
                '-'
            }
        })
        .collect::<String>();
    let trimmed = component.trim_matches(|ch| matches!(ch, '-' | '.'));
    if trimmed.is_empty() {
        "runtime".to_string()
    } else {
        trimmed.to_string()
    }
}

#[cfg(test)]
mod tests;
