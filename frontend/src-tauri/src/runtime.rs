use std::{env, error::Error, path::Path, path::PathBuf, process::Command};

use tauri::{Emitter, Manager, Runtime};

mod managed;
mod manifest;
mod probe_runner;
mod python_env;
mod python_probe;
mod pytorch;
mod resolver;

pub use python_probe::display_path;
pub use resolver::{RuntimeCandidateView, RuntimeRepairActionKind, RuntimeScanView};

type RuntimeResult<T> = Result<T, Box<dyn Error>>;
pub const INSTALL_DIR_RUNTIME_ID: &str = python_probe::INSTALL_DIR_RUNTIME_ID;

#[derive(Debug)]
pub struct PythonRuntime {
    pub command: Command,
    pub description: String,
    pub candidate_id: Option<String>,
}

pub fn manual_install_command(
    source_root: &Path,
    candidate: Option<&RuntimeCandidateView>,
) -> Option<String> {
    let candidate = candidate.filter(|candidate| {
        candidate.managed
            && !candidate.path.trim().is_empty()
            && matches!(
                candidate.status,
                resolver::RuntimeCandidateStatus::Ready
                    | resolver::RuntimeCandidateStatus::MissingCoreDeps
                    | resolver::RuntimeCandidateStatus::MissingOptionalDeps
                    | resolver::RuntimeCandidateStatus::BrokenBridge
            )
    })?;
    let python = if candidate.display_path.trim().is_empty() {
        python_probe::display_path(Path::new(&candidate.path))
    } else {
        candidate.display_path.clone()
    };
    let profile = runtime_profile();
    let requirements =
        python_probe::display_path(&runtime_requirements_path(source_root, &profile));
    Some(manual_install_command_for_shell(
        &python,
        &requirements,
        cfg!(windows),
    ))
}

fn runtime_requirements_path(source_root: &Path, profile: &str) -> PathBuf {
    let runtime_manifest = manifest::load_manifest(source_root).ok();
    let requirements =
        manifest::runtime_requirements(source_root, runtime_manifest.as_ref(), profile);
    let path = PathBuf::from(requirements.requirements_file);
    if path.is_absolute() {
        path
    } else {
        source_root.join(path)
    }
}

fn manual_install_command_for_shell(python: &str, requirements: &str, windows: bool) -> String {
    let python = quote_shell_argument(python, windows);
    let requirements = quote_shell_argument(requirements, windows);
    let invocation = if windows {
        format!("& {python}")
    } else {
        python
    };
    format!("{invocation} -m pip install --requirement {requirements}")
}

fn quote_shell_argument(value: &str, windows: bool) -> String {
    if windows {
        format!("'{}'", value.replace('\'', "''"))
    } else {
        format!("'{}'", value.replace('\'', "'\\''"))
    }
}

pub fn scan_runtime_view<R: Runtime>(app: &impl Manager<R>, source_root: &Path) -> RuntimeScanView {
    let manifest = manifest::load_manifest(source_root).ok();
    let profile = runtime_profile();
    resolver::scan_runtime_candidates(app, source_root, manifest.as_ref(), &profile)
}

#[allow(dead_code)]
pub fn install_dir_runtime_view(source_root: &Path) -> RuntimeScanView {
    resolver::install_dir_runtime_view(source_root)
}

pub fn install_dir_runtime_view_for_app(source_root: &Path, app_root: &Path) -> RuntimeScanView {
    resolver::install_dir_runtime_view_for_root(&python_probe::effective_runtime_root(
        source_root,
        app_root,
    ))
}

#[allow(dead_code)]
pub fn find_install_dir_python_runtime(source_root: &Path) -> RuntimeResult<PythonRuntime> {
    find_install_dir_python_runtime_for_app(source_root, source_root)
}

pub fn find_install_dir_python_runtime_for_app(
    source_root: &Path,
    app_root: &Path,
) -> RuntimeResult<PythonRuntime> {
    let runtime_root = python_probe::effective_runtime_root(source_root, app_root);
    let path = python_probe::python_in_prefix(&runtime_root).ok_or_else(|| {
        format!(
            "Shinsekai managed Python runtime not found at {}",
            runtime_root.display()
        )
    })?;
    let launch_path = bridge_launch_python(&path);
    let mut command = Command::new(&launch_path);
    python_env::configure_python_command(&mut command, &path);
    Ok(PythonRuntime {
        command,
        description: format!(
            "Shinsekai bundled runtime @ {}",
            python_probe::display_path(&runtime_root)
        ),
        candidate_id: Some(python_probe::INSTALL_DIR_RUNTIME_ID.to_string()),
    })
}

#[allow(dead_code)]
pub fn find_python_runtime<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
) -> RuntimeResult<PythonRuntime> {
    find_python_runtime_for_candidate(app, source_root, None)
}

pub fn find_python_runtime_for_candidate<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
    candidate_id: Option<&str>,
) -> RuntimeResult<PythonRuntime> {
    let view = scan_runtime_view(app, source_root);
    let Some(candidate) = resolver::ready_candidate(&view, candidate_id) else {
        return Err(view
            .message
            .unwrap_or_else(|| {
                "no complete Shinsekai managed Python runtime found under runtime/".to_string()
            })
            .into());
    };
    let path = PathBuf::from(&candidate.path);
    let launch_path = bridge_launch_python(&path);
    let mut command = Command::new(&launch_path);
    python_env::configure_python_command(&mut command, &path);
    Ok(PythonRuntime {
        command,
        description: candidate.label.clone(),
        candidate_id: Some(candidate.id.clone()),
    })
}

pub fn repair_runtime_candidate<R: Runtime, M: Manager<R> + Emitter<R>>(
    app: &M,
    source_root: &Path,
    candidate_id: &str,
    action: RuntimeRepairActionKind,
) -> RuntimeResult<Option<PathBuf>> {
    let view = scan_runtime_view(app, source_root);
    let candidate = view
        .candidates
        .iter()
        .find(|candidate| candidate.id == candidate_id)
        .ok_or_else(|| format!("runtime candidate not found: {candidate_id}"))?;
    if !runtime_action_supported(candidate, action) {
        return Err(format!(
            "runtime action {action:?} is not supported for candidate {candidate_id}"
        )
        .into());
    }

    match action {
        RuntimeRepairActionKind::Start => {
            let runtime = find_python_runtime_for_candidate(app, source_root, Some(candidate_id))?;
            Ok(runtime.command.get_program().to_str().map(PathBuf::from))
        }
        RuntimeRepairActionKind::InstallRuntimeDeps => {
            let manifest = manifest::load_manifest(source_root).ok();
            let profile = runtime_profile();
            let requirements =
                manifest::runtime_requirements(source_root, manifest.as_ref(), &profile);
            let pip_index_urls = manifest
                .as_ref()
                .map(|manifest| manifest::pip_index_urls_for_source(manifest, None))
                .unwrap_or_default();
            if candidate.path.trim().is_empty() {
                return Err("runtime candidate does not have a Python path".into());
            }
            let python = managed::install_runtime_dependencies(
                app,
                source_root,
                &PathBuf::from(&candidate.path),
                candidate_id,
                &profile,
                &requirements,
                &pip_index_urls,
            )?;
            Ok(Some(python))
        }
    }
}

fn runtime_action_supported(
    candidate: &RuntimeCandidateView,
    action: RuntimeRepairActionKind,
) -> bool {
    candidate.repair_actions.contains(&action)
        || (action == RuntimeRepairActionKind::InstallRuntimeDeps
            && candidate.managed
            && !candidate.path.trim().is_empty())
}

pub fn install_runtime_profile<R: Runtime, M: Manager<R> + Emitter<R>>(
    app: &M,
    source_root: &Path,
    profile: &str,
    candidate_id: Option<&str>,
) -> RuntimeResult<PathBuf> {
    let profile = profile.trim();
    if profile.is_empty() {
        return Err("runtime profile is required".into());
    }
    let manifest = manifest::load_manifest(source_root)?;
    if !manifest.profiles.contains_key(profile) {
        return Err(format!("runtime profile is not defined in manifest: {profile}").into());
    }
    let view = scan_runtime_view(app, source_root);
    let requested_candidate_id = candidate_id.or(view.selected_candidate_id.as_deref());
    let candidate = resolver::ready_candidate(&view, requested_candidate_id)
        .or_else(|| candidate_id.is_none().then(|| resolver::ready_candidate(&view, None)).flatten())
        .ok_or_else(|| {
            if let Some(candidate_id) = candidate_id {
                format!(
                    "current Shinsekai managed Python runtime is not ready for optional dependencies: {candidate_id}"
                )
            } else {
                "Shinsekai managed Python runtime must be ready before installing optional runtime dependencies"
                    .to_string()
            }
        })?;
    if candidate.path.trim().is_empty() {
        return Err("runtime candidate does not have a Python path".into());
    }
    let requirements = manifest::runtime_requirements(source_root, Some(&manifest), profile);
    let pip_index_urls = manifest::pip_index_urls_for_source(&manifest, None);
    let progress_id = format!("{}-{profile}", candidate.id);
    managed::install_runtime_dependencies(
        app,
        source_root,
        &PathBuf::from(&candidate.path),
        &progress_id,
        profile,
        &requirements,
        &pip_index_urls,
    )
}

pub fn ready_candidate_id_for_path<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
    repaired_path: &Path,
) -> Option<String> {
    let view = scan_runtime_view(app, source_root);
    ready_candidate_id_for_path_in_view(&view, repaired_path)
}

#[allow(dead_code)]
pub fn resolve_python_path(path: &Path) -> RuntimeResult<PathBuf> {
    if path.is_file() {
        return Ok(path.to_path_buf());
    }
    if path.is_dir() {
        if let Some(python) = python_probe::python_in_prefix(path) {
            return Ok(python);
        }
        return Err(format!(
            "runtime directory does not contain a Python executable: {}",
            path.display()
        )
        .into());
    }
    Err(format!("runtime Python path does not exist: {}", path.display()).into())
}

fn runtime_profile() -> String {
    env::var("SHINSEKAI_RUNTIME_PROFILE").unwrap_or_else(|_| manifest::DEFAULT_PROFILE.to_string())
}

fn bridge_launch_python(python: &Path) -> PathBuf {
    #[cfg(windows)]
    {
        if crate::show_backend_console() {
            return python.to_path_buf();
        }
        pythonw_for_python(python).unwrap_or_else(|| python.to_path_buf())
    }
    #[cfg(not(windows))]
    {
        python.to_path_buf()
    }
}

#[allow(dead_code)]
fn pythonw_for_python(python: &Path) -> Option<PathBuf> {
    let file_name = python.file_name()?.to_str()?.to_ascii_lowercase();
    if file_name == "pythonw.exe" {
        return Some(python.to_path_buf());
    }
    if !matches!(file_name.as_str(), "python.exe" | "python3.exe") {
        return None;
    }
    let candidate = python.with_file_name("pythonw.exe");
    candidate.is_file().then_some(candidate)
}

fn ready_candidate_id_for_path_in_view(
    view: &RuntimeScanView,
    repaired_path: &Path,
) -> Option<String> {
    let repaired_python = runtime_python_path(repaired_path)?;
    let normalized_repaired = normalized_path(&repaired_python);
    view.candidates
        .iter()
        .find(|candidate| {
            candidate.status == resolver::RuntimeCandidateStatus::Ready
                && !candidate.path.trim().is_empty()
                && normalized_path(Path::new(&candidate.path)) == normalized_repaired
        })
        .map(|candidate| candidate.id.clone())
}

fn runtime_python_path(path: &Path) -> Option<PathBuf> {
    if path.is_file() {
        return Some(path.to_path_buf());
    }
    python_probe::python_in_prefix(path)
}

fn normalized_path(path: &Path) -> PathBuf {
    path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
}

#[cfg(test)]
mod tests;
