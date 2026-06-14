use std::{
    env,
    error::Error,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Command, ExitStatus, Stdio},
    sync::mpsc::{self, RecvTimeoutError},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{Emitter, Manager, Runtime};

use super::{manifest::RuntimeRequirements, python_env};

type RuntimeResult<T> = Result<T, Box<dyn Error>>;
const RUNTIME_PROGRESS_EVENT: &str = "shinsekai:runtime-progress";
const TORCH_PROJECT_NAMES: &[&str] = &["torch", "torchvision", "torchaudio"];

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

fn install_runtime_requirements<F>(
    python: &Path,
    requirements_path: &Path,
    pip_index_urls: &[String],
    mut on_log_line: F,
) -> RuntimeResult<()>
where
    F: FnMut(&str),
{
    ensure_python_pip_available(python)?;
    let requirements_text = fs::read_to_string(requirements_path).map_err(|error| {
        format!(
            "read runtime requirements file {} failed: {error}",
            requirements_path.display()
        )
    })?;
    let requirement_lines = requirements_text
        .lines()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let (torch_lines, other_lines) = partition_torch_requirement_lines(&requirement_lines);
    let split_torch = !torch_lines.is_empty() && !cfg!(target_os = "macos");

    if split_torch {
        let (torch_index, reason) = pytorch_wheel_index_url_for_this_machine(pip_index_urls);
        on_log_line(&format!(
            "Installing PyTorch packages first from {torch_index} ({reason})"
        ));
        let torch_requirements =
            write_temp_requirements(requirements_path, "shinsekai-torch", &torch_lines)?;
        let other_requirements =
            write_temp_requirements(requirements_path, "shinsekai-runtime", &other_lines)?;
        let result = (|| {
            let mut install_torch = pip_install_command(python, &torch_requirements, None);
            install_torch
                .arg("--index-url")
                .arg(&torch_index)
                .arg("--extra-index-url")
                .arg("https://pypi.org/simple");
            run_command_with_live_log(
                &mut install_torch,
                "install Shinsekai PyTorch runtime dependencies",
                &mut on_log_line,
            )?;
            if !has_non_comment_requirement(&other_lines) {
                return Ok(());
            }
            install_runtime_requirements_file_with_indexes(
                python,
                &other_requirements,
                pip_index_urls,
                &mut on_log_line,
            )
        })();
        let _ = fs::remove_file(torch_requirements);
        let _ = fs::remove_file(other_requirements);
        return result;
    }

    install_runtime_requirements_file_with_indexes(
        python,
        requirements_path,
        pip_index_urls,
        &mut on_log_line,
    )
}

fn install_runtime_requirements_file_with_indexes<F>(
    python: &Path,
    requirements_path: &Path,
    pip_index_urls: &[String],
    mut on_log_line: F,
) -> RuntimeResult<()>
where
    F: FnMut(&str),
{
    let mut errors = Vec::new();

    if pip_index_urls.is_empty() {
        let mut install = pip_install_command(python, requirements_path, None);
        return run_command_with_live_log(
            &mut install,
            "install Shinsekai runtime dependencies",
            on_log_line,
        );
    }

    for pip_index_url in pip_index_urls {
        let mut install = pip_install_command(python, requirements_path, Some(pip_index_url));
        on_log_line(&format!("Using pip index: {}", pip_index_url.trim()));
        match run_command_with_live_log(
            &mut install,
            "install Shinsekai runtime dependencies",
            &mut on_log_line,
        ) {
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

fn write_temp_requirements(
    requirements_path: &Path,
    prefix: &str,
    lines: &[String],
) -> RuntimeResult<PathBuf> {
    let parent = requirements_path.parent().unwrap_or_else(|| Path::new("."));
    let filename = format!(
        "{}-{}-{}.txt",
        prefix,
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    );
    let path = parent.join(filename);
    fs::write(&path, lines.join("\n"))?;
    Ok(path)
}

fn has_non_comment_requirement(lines: &[String]) -> bool {
    lines.iter().any(|line| {
        let trimmed = line.split('#').next().unwrap_or("").trim();
        !trimmed.is_empty() && !trimmed.starts_with('#')
    })
}

fn partition_torch_requirement_lines(lines: &[String]) -> (Vec<String>, Vec<String>) {
    let mut torch_lines = Vec::new();
    let mut other_lines = Vec::new();
    for line in lines {
        let project_name = requirement_line_project_name(line);
        if project_name
            .as_deref()
            .is_some_and(|name| TORCH_PROJECT_NAMES.contains(&name))
        {
            torch_lines.push(line.trim_end_matches(['\r', '\n']).to_string());
        } else {
            other_lines.push(line.trim_end_matches(['\r', '\n']).to_string());
        }
    }
    (torch_lines, other_lines)
}

fn requirement_line_project_name(line: &str) -> Option<String> {
    let mut segment = line.split('#').next()?.trim();
    if segment.is_empty() {
        return None;
    }
    let lower = segment.to_ascii_lowercase();
    if lower.starts_with("--") || lower.starts_with("-r ") || lower.starts_with("-c ") {
        return None;
    }
    if lower.starts_with("-e ") {
        segment = segment.get(3..)?.trim();
    }
    let first = segment.split_whitespace().next().unwrap_or(segment);
    if first.contains("://") || first.starts_with("git+") {
        return None;
    }
    let name = first
        .chars()
        .take_while(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-'))
        .collect::<String>();
    if name.is_empty() {
        None
    } else {
        Some(name.to_ascii_lowercase().replace('_', "-"))
    }
}

fn pytorch_wheel_index_url_for_this_machine(pip_index_urls: &[String]) -> (String, String) {
    pytorch_wheel_index_url_for_cuda_version(
        nvidia_smi_cuda_driver_version(),
        pytorch_wheel_base_url(pip_index_urls),
    )
}

fn pytorch_wheel_base_url(pip_index_urls: &[String]) -> String {
    if let Ok(value) = env::var("SHINSEKAI_PYTORCH_WHEEL_BASE") {
        let trimmed = value.trim().trim_end_matches('/');
        if !trimmed.is_empty() {
            return trimmed.to_string();
        }
    }
    if pip_indexes_prefer_china(pip_index_urls) {
        "https://mirror.sjtu.edu.cn/pytorch-wheels".to_string()
    } else {
        "https://download.pytorch.org/whl".to_string()
    }
}

fn pip_indexes_prefer_china(pip_index_urls: &[String]) -> bool {
    let Some(primary) = pip_index_urls.first() else {
        return false;
    };
    let primary = primary.to_ascii_lowercase();
    [
        "pypi.tuna.tsinghua.edu.cn",
        "mirrors.ustc.edu.cn",
        "mirrors.hit.edu.cn",
        "mirrors.aliyun.com",
        "mirror.sjtu.edu.cn",
    ]
    .iter()
    .any(|domain| primary.contains(domain))
}

fn pytorch_wheel_index_url_for_cuda_version(
    version: Option<(u32, u32)>,
    base_url: String,
) -> (String, String) {
    let Some((major, minor)) = version else {
        return (
            format!("{base_url}/cpu"),
            "no_usable_nvidia_smi_cpu".to_string(),
        );
    };
    let tag = if (major, minor) >= (12, 4) {
        "cu124"
    } else if major >= 12 {
        "cu121"
    } else {
        "cu118"
    };
    (
        format!("{base_url}/{tag}"),
        format!("nvidia_driver_cuda_{major}.{minor}_{tag}"),
    )
}

fn nvidia_smi_cuda_driver_version() -> Option<(u32, u32)> {
    let output = Command::new("nvidia-smi").output().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    parse_nvidia_smi_cuda_version(&stdout)
}

fn parse_nvidia_smi_cuda_version(output: &str) -> Option<(u32, u32)> {
    let (_, tail) = output.split_once("CUDA Version:")?;
    let version_text = tail
        .trim_start()
        .chars()
        .take_while(|ch| ch.is_ascii_digit() || *ch == '.')
        .collect::<String>();
    let (major, minor) = version_text.split_once('.')?;
    Some((major.parse().ok()?, minor.parse().ok()?))
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
        None,
    );
    install_runtime_requirements(python, &requirements_path, pip_index_urls, |line| {
        emit_runtime_progress(
            app,
            "installingDeps",
            Some(candidate_id.to_string()),
            Some("local".to_string()),
            None,
            None,
            None,
            Some("Installing Shinsekai runtime dependencies"),
            Some(line),
        );
    })?;

    emit_runtime_progress(
        app,
        "checkingBridge",
        Some(candidate_id.clone()),
        Some("local".to_string()),
        Some(2),
        Some(3),
        None,
        Some("Checking repaired runtime"),
        None,
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
        None,
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
    let output = command
        .output()
        .map_err(|error| format!("{label} failed to start: {error}"))?;
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

fn run_command_with_live_log<F>(
    command: &mut Command,
    label: &str,
    mut on_log_line: F,
) -> RuntimeResult<()>
where
    F: FnMut(&str),
{
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn()?;
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let (tx, rx) = mpsc::channel::<(OutputStream, String)>();
    let mut readers = Vec::new();

    if let Some(stdout) = stdout {
        readers.push(spawn_output_reader(
            OutputStream::Stdout,
            stdout,
            tx.clone(),
        ));
    }
    if let Some(stderr) = stderr {
        readers.push(spawn_output_reader(
            OutputStream::Stderr,
            stderr,
            tx.clone(),
        ));
    }
    drop(tx);

    let mut stdout_lines = Vec::new();
    let mut stderr_lines = Vec::new();
    let status = wait_for_command_with_live_log(
        &mut child,
        &rx,
        &mut stdout_lines,
        &mut stderr_lines,
        &mut on_log_line,
    )?;
    for entry in rx {
        push_output_line(
            entry,
            &mut stdout_lines,
            &mut stderr_lines,
            &mut on_log_line,
        );
    }
    for reader in readers {
        let _ = reader.join();
    }

    if status.success() {
        return Ok(());
    }
    Err(format!(
        "{label} failed with status {}. stdout: {} stderr: {}",
        status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "terminated".to_string()),
        stdout_lines.join("\n").trim(),
        stderr_lines.join("\n").trim()
    )
    .into())
}

fn wait_for_command_with_live_log<F>(
    child: &mut std::process::Child,
    rx: &mpsc::Receiver<(OutputStream, String)>,
    stdout_lines: &mut Vec<String>,
    stderr_lines: &mut Vec<String>,
    on_log_line: &mut F,
) -> RuntimeResult<ExitStatus>
where
    F: FnMut(&str),
{
    let mut last_status_check = Instant::now();
    loop {
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(entry) => push_output_line(entry, stdout_lines, stderr_lines, on_log_line),
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => {
                return Ok(child.wait()?);
            }
        }
        if last_status_check.elapsed() >= Duration::from_millis(50) {
            if let Some(status) = child.try_wait()? {
                return Ok(status);
            }
            last_status_check = Instant::now();
        }
    }
}

fn push_output_line<F>(
    (stream, line): (OutputStream, String),
    stdout_lines: &mut Vec<String>,
    stderr_lines: &mut Vec<String>,
    on_log_line: &mut F,
) where
    F: FnMut(&str),
{
    if line.trim().is_empty() {
        return;
    }
    on_log_line(&line);
    match stream {
        OutputStream::Stdout => stdout_lines.push(line),
        OutputStream::Stderr => stderr_lines.push(line),
    }
}

#[derive(Clone, Copy)]
enum OutputStream {
    Stdout,
    Stderr,
}

fn spawn_output_reader<R>(
    stream: OutputStream,
    reader: R,
    tx: mpsc::Sender<(OutputStream, String)>,
) -> thread::JoinHandle<()>
where
    R: Read + Send + 'static,
{
    thread::spawn(move || {
        let mut reader = BufReader::new(reader);
        let mut buffer = Vec::new();
        loop {
            buffer.clear();
            match reader.read_until(b'\n', &mut buffer) {
                Ok(0) => break,
                Ok(_) => {
                    let text = String::from_utf8_lossy(&buffer)
                        .trim_end_matches(|ch| matches!(ch, '\r' | '\n'))
                        .to_string();
                    if tx.send((stream, text)).is_err() {
                        break;
                    }
                }
                Err(error) => {
                    let _ = tx.send((stream, format!("failed to read pip output: {error}")));
                    break;
                }
            }
        }
    })
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
    log_line: Option<String>,
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
    log_line: Option<&str>,
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
            log_line: log_line.map(ToString::to_string),
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
