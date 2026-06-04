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

use super::{
    manifest::{current_arch, current_platform, RuntimeRequirements},
    python_probe::python_in_prefix,
};

type RuntimeResult<T> = Result<T, Box<dyn Error>>;
const RUNTIME_PROGRESS_EVENT: &str = "shinsekai:runtime-progress";
const RUNTIME_MARKER_FILE: &str = ".shinsekai-runtime.json";

pub fn create_managed_venv<R: Runtime, M: Manager<R> + Emitter<R>>(
    app: &M,
    source_root: &Path,
    base_python: &Path,
    candidate_id: &str,
    profile: &str,
    requirements: &RuntimeRequirements,
    pip_index_urls: &[String],
) -> RuntimeResult<PathBuf> {
    let runtime_home = runtime_home(app)?;
    let _install_lock = acquire_install_lock(&runtime_home)?;
    let venvs_dir = runtime_home.join("venvs");
    fs::create_dir_all(&venvs_dir)?;
    let venv_id = safe_component(&format!("{candidate_id}-{profile}"));
    let staging_root = venvs_dir.join(format!("{venv_id}.tmp-{}", std::process::id()));
    if staging_root.exists() {
        fs::remove_dir_all(&staging_root)?;
    }

    let result = (|| -> RuntimeResult<PathBuf> {
        emit_runtime_progress(
            app,
            "installingDeps",
            Some(venv_id.clone()),
            Some("local".to_string()),
            None,
            None,
            None,
            Some("Creating isolated Python environment"),
        );
        let mut create = Command::new(base_python);
        create
            .arg("-m")
            .arg("venv")
            .arg(&staging_root)
            .env_remove("PYTHONHOME")
            .env_remove("PYTHONPATH");
        run_command(&mut create, "create managed venv")?;

        let python = python_in_prefix(&staging_root).ok_or_else(|| {
            format!(
                "created venv does not contain a Python executable: {}",
                staging_root.display()
            )
        })?;
        let requirements_path = requirements_path(source_root, &requirements.requirements_file);
        emit_runtime_progress(
            app,
            "installingDeps",
            Some(venv_id.clone()),
            Some("local".to_string()),
            None,
            None,
            None,
            Some("Installing Shinsekai runtime dependencies"),
        );
        install_runtime_requirements(&python, &requirements_path, pip_index_urls)?;

        emit_runtime_progress(
            app,
            "checkingBridge",
            Some(venv_id.clone()),
            Some("local".to_string()),
            None,
            None,
            None,
            Some("Checking isolated runtime"),
        );
        verify_runtime_root(source_root, &staging_root, profile, requirements)?;
        write_runtime_marker(
            &staging_root,
            RuntimeMarker {
                version: "venv".to_string(),
                schema: 2,
                platform: current_platform().to_string(),
                arch: current_arch().to_string(),
                profile: profile.to_string(),
                source: "managed-venv".to_string(),
            },
        )?;

        publish_managed_venv(&venvs_dir, &staging_root, &venv_id)
    })();
    remove_staging_dir_after_error(&result, &staging_root);
    let venv_root = result?;
    emit_runtime_progress(
        app,
        "ready",
        Some(venv_id),
        Some("local".to_string()),
        None,
        None,
        None,
        Some("Isolated runtime is ready"),
    );
    Ok(venv_root)
}

fn remove_staging_dir_after_error<T>(result: &RuntimeResult<T>, staging_root: &Path) {
    if result.is_err() && staging_root.exists() {
        let _ = fs::remove_dir_all(staging_root);
    }
}

fn publish_managed_venv(
    venvs_dir: &Path,
    staging_root: &Path,
    venv_id: &str,
) -> RuntimeResult<PathBuf> {
    fs::create_dir_all(venvs_dir)?;
    let venv_root = venvs_dir.join(venv_id);
    let previous_root = if venv_root.exists() {
        Some(previous_runtime_root(venvs_dir, venv_id))
    } else {
        None
    };

    if let Some(previous_root) = &previous_root {
        fs::rename(&venv_root, previous_root)?;
    }

    let publish_result = fs::rename(staging_root, &venv_root);
    if let Err(error) = publish_result {
        if venv_root.exists() {
            let _ = fs::remove_dir_all(&venv_root);
        }
        if let Some(previous_root) = &previous_root {
            if previous_root.exists() && !venv_root.exists() {
                let _ = fs::rename(previous_root, &venv_root);
            }
        }
        return Err(error.into());
    }

    if let Some(previous_root) = &previous_root {
        let _ = fs::remove_dir_all(previous_root);
    }

    Ok(venv_root)
}

fn configure_pip_command(command: &mut Command) {
    command
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .env("PIP_DISABLE_PIP_VERSION_CHECK", "1");
}

fn configure_pip_install_command(command: &mut Command, pip_index_url: Option<&str>) {
    configure_pip_command(command);
    if let Some(url) = pip_index_url.map(str::trim).filter(|url| !url.is_empty()) {
        command.arg("-i").arg(url);
    }
}

fn ensure_python_pip_available(python: &Path) -> RuntimeResult<()> {
    let mut command = Command::new(python);
    command.arg("-m").arg("pip").arg("--version");
    configure_pip_command(&mut command);
    run_command(&mut command, "check Python pip").map_err(|error| {
        format!(
            "Python pip is not available for {}: {}",
            python.display(),
            error
        )
        .into()
    })
}

fn install_runtime_requirements(
    python: &Path,
    requirements_path: &Path,
    pip_index_urls: &[String],
) -> RuntimeResult<()> {
    ensure_python_pip_available(python)?;
    if pip_index_urls.is_empty() {
        let mut install = pip_install_command(python, requirements_path, None);
        return run_command(&mut install, "install Shinsekai runtime dependencies");
    }

    let mut errors = Vec::new();
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
    configure_pip_install_command(&mut install, pip_index_url);
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
        None,
        None,
        None,
        Some("Checking repaired runtime"),
    );
    verify_python_runtime(source_root, python, profile, requirements)?;
    emit_runtime_progress(
        app,
        "ready",
        Some(candidate_id),
        Some("local".to_string()),
        None,
        None,
        None,
        Some("Runtime dependencies are ready"),
    );
    Ok(python.to_path_buf())
}

fn previous_runtime_root(runtimes_dir: &Path, runtime_id: &str) -> PathBuf {
    let now = now_millis();
    for attempt in 0..1000 {
        let suffix = if attempt == 0 {
            now.to_string()
        } else {
            format!("{now}-{attempt}")
        };
        let candidate = runtimes_dir.join(format!("{runtime_id}.previous-{suffix}"));
        if !candidate.exists() {
            return candidate;
        }
    }
    runtimes_dir.join(format!(
        "{runtime_id}.previous-{now}-{}",
        std::process::id()
    ))
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeMarker {
    version: String,
    schema: u32,
    platform: String,
    arch: String,
    profile: String,
    source: String,
}

fn write_runtime_marker(runtime_root: &Path, marker: RuntimeMarker) -> RuntimeResult<()> {
    let marker_path = runtime_root.join(RUNTIME_MARKER_FILE);
    fs::write(marker_path, serde_json::to_string_pretty(&marker)?)?;
    Ok(())
}

fn now_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

fn verify_runtime_root(
    source_root: &Path,
    runtime_root: &Path,
    profile: &str,
    requirements: &RuntimeRequirements,
) -> RuntimeResult<()> {
    let python = python_in_prefix(runtime_root).ok_or_else(|| {
        format!(
            "runtime does not contain a Python executable: {}",
            runtime_root.display()
        )
    })?;
    verify_python_runtime(source_root, &python, profile, requirements)
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
        .current_dir(source_root)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH");
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
    command
        .arg("-c")
        .arg(script)
        .args(modules)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH");
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
mod tests {
    use super::*;
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn configure_pip_install_command_adds_selected_index_url_argument() {
        let mut command = Command::new("python");

        configure_pip_install_command(&mut command, Some("https://mirror.example/simple/"));

        let envs = command
            .get_envs()
            .map(|(key, value)| {
                (
                    key.to_string_lossy().to_string(),
                    value.map(|value| value.to_string_lossy().to_string()),
                )
            })
            .collect::<Vec<_>>();
        assert!(envs.contains(&("PYTHONHOME".to_string(), None)));
        assert!(envs.contains(&("PYTHONPATH".to_string(), None)));
        assert!(envs.contains(&(
            "PIP_DISABLE_PIP_VERSION_CHECK".to_string(),
            Some("1".to_string())
        )));
        let args = command
            .get_args()
            .map(|arg| arg.to_string_lossy().to_string())
            .collect::<Vec<_>>();
        assert_eq!(
            args,
            vec![
                "-i".to_string(),
                "https://mirror.example/simple/".to_string()
            ]
        );
    }

    #[test]
    fn publish_managed_venv_replaces_existing_venv_without_leaving_previous_candidate() {
        let temp_root = unique_temp_dir("runtime-venv-publish-success");
        let venvs_dir = temp_root.join("venvs");
        let venv_id = "venv-test";
        let venv_root = venvs_dir.join(venv_id);
        let staging_root = venvs_dir.join("venv-test.tmp");
        fs::create_dir_all(&venv_root).unwrap();
        fs::create_dir_all(&staging_root).unwrap();
        fs::write(venv_root.join("old.txt"), "old venv").unwrap();
        fs::write(staging_root.join("new.txt"), "new venv").unwrap();

        let published = publish_managed_venv(&venvs_dir, &staging_root, venv_id).unwrap();

        assert_eq!(published, venv_root);
        assert_eq!(
            fs::read_to_string(venv_root.join("new.txt")).unwrap(),
            "new venv"
        );
        assert!(!staging_root.exists());
        assert!(previous_runtime_dirs(&venvs_dir, venv_id).is_empty());

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn publish_managed_venv_restores_existing_venv_when_publish_fails() {
        let temp_root = unique_temp_dir("runtime-venv-publish-rollback");
        let venvs_dir = temp_root.join("venvs");
        let venv_id = "venv-test";
        let venv_root = venvs_dir.join(venv_id);
        let missing_staging_root = venvs_dir.join("missing-staging");
        fs::create_dir_all(&venv_root).unwrap();
        fs::write(venv_root.join("old.txt"), "old venv").unwrap();

        let error = publish_managed_venv(&venvs_dir, &missing_staging_root, venv_id).unwrap_err();

        assert!(!error.to_string().is_empty());
        assert_eq!(
            fs::read_to_string(venv_root.join("old.txt")).unwrap(),
            "old venv"
        );
        assert!(previous_runtime_dirs(&venvs_dir, venv_id).is_empty());

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn remove_staging_dir_after_error_only_cleans_failed_venv_staging() {
        let temp_root = unique_temp_dir("runtime-venv-staging-cleanup");
        let failed_staging_root = temp_root.join("failed.tmp");
        let ok_staging_root = temp_root.join("ok.tmp");
        fs::create_dir_all(&failed_staging_root).unwrap();
        fs::write(failed_staging_root.join("partial.txt"), "partial venv").unwrap();
        fs::create_dir_all(&ok_staging_root).unwrap();
        fs::write(ok_staging_root.join("ready.txt"), "ready venv").unwrap();

        let failed: RuntimeResult<PathBuf> = Err("venv creation failed".into());
        remove_staging_dir_after_error(&failed, &failed_staging_root);
        let ok: RuntimeResult<PathBuf> = Ok(ok_staging_root.clone());
        remove_staging_dir_after_error(&ok, &ok_staging_root);

        assert!(!failed_staging_root.exists());
        assert!(ok_staging_root.join("ready.txt").is_file());

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn lock_pid_parser_reads_install_lock_pid() {
        assert_eq!(
            lock_pid_from_text("pid=12345\ncreated_at_ms=10\n"),
            Some(12345)
        );
        assert_eq!(lock_pid_from_text("created_at_ms=10\npid= 42\n"), Some(42));
        assert_eq!(lock_pid_from_text("pid=0\n"), None);
        assert_eq!(lock_pid_from_text("created_at_ms=10\n"), None);
    }

    #[test]
    fn current_process_install_lock_is_not_stale() {
        let temp_root = unique_temp_dir("runtime-current-lock");
        let runtime_home = temp_root.join("runtime");
        fs::create_dir_all(&runtime_home).unwrap();
        fs::write(
            runtime_home.join("install.lock"),
            format!("pid={}\ncreated_at_ms=10\n", std::process::id()),
        )
        .unwrap();

        assert!(!is_stale_lock(&runtime_home.join("install.lock")));

        let _ = fs::remove_dir_all(temp_root);
    }

    #[cfg(unix)]
    #[test]
    fn exited_process_install_lock_is_replaced() {
        let temp_root = unique_temp_dir("runtime-dead-lock");
        let runtime_home = temp_root.join("runtime");
        fs::create_dir_all(&runtime_home).unwrap();
        fs::write(
            runtime_home.join("install.lock"),
            "pid=9999999\ncreated_at_ms=10\n",
        )
        .unwrap();

        assert!(is_stale_lock(&runtime_home.join("install.lock")));
        let lock = acquire_install_lock(&runtime_home).unwrap();
        let lock_text = fs::read_to_string(runtime_home.join("install.lock")).unwrap();
        assert!(lock_text.contains(&format!("pid={}", std::process::id())));
        drop(lock);
        assert!(!runtime_home.join("install.lock").exists());

        let _ = fs::remove_dir_all(temp_root);
    }

    #[cfg(unix)]
    #[test]
    fn verify_python_imports_reports_missing_modules() {
        let temp_root = unique_temp_dir("runtime-import-check");
        fs::create_dir_all(&temp_root).unwrap();
        let fake_python = temp_root.join("python");
        fs::write(
            &fake_python,
            "#!/bin/sh\ncase \"$*\" in *missing_runtime_module*) echo missing >&2; exit 1;; *) exit 0;; esac\n",
        )
        .unwrap();
        let mut permissions = fs::metadata(&fake_python).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&fake_python, permissions).unwrap();

        let modules = vec!["json".to_string(), "missing_runtime_module".to_string()];
        let error = verify_python_imports(&fake_python, &modules).unwrap_err();

        assert!(error
            .to_string()
            .contains("check Shinsekai runtime imports failed"));

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn safe_component_rejects_parent_directory_components() {
        assert_eq!(safe_component(".."), "runtime");
        assert_eq!(safe_component("../runtime test"), "runtime-test");
    }

    fn previous_runtime_dirs(runtimes_dir: &Path, runtime_id: &str) -> Vec<PathBuf> {
        let mut dirs = fs::read_dir(runtimes_dir)
            .unwrap()
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                path.file_name()
                    .and_then(|name| name.to_str())
                    .map(|name| name.starts_with(&format!("{runtime_id}.previous-")))
                    .unwrap_or(false)
            })
            .collect::<Vec<_>>();
        dirs.sort();
        dirs
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
    }
}
