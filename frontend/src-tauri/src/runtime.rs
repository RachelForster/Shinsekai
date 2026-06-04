use std::{env, error::Error, path::Path, path::PathBuf, process::Command};

use tauri::{Emitter, Manager, Runtime};

mod managed;
mod manifest;
mod python_env;
mod python_probe;
mod resolver;

pub use resolver::{RuntimeCandidateView, RuntimeRepairActionKind, RuntimeScanView};

type RuntimeResult<T> = Result<T, Box<dyn Error>>;

#[derive(Debug)]
pub struct PythonRuntime {
    pub command: Command,
    pub description: String,
    pub candidate_id: Option<String>,
}

pub fn scan_runtime_view<R: Runtime>(app: &impl Manager<R>, source_root: &Path) -> RuntimeScanView {
    let manifest = manifest::load_manifest(source_root).ok();
    let profile = runtime_profile();
    resolver::scan_runtime_candidates(app, source_root, manifest.as_ref(), &profile)
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
                "no complete Shinsekai managed Python runtime found; provide bundled runtime/ or set SHINSEKAI_RUNTIME_DIR".to_string()
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
    if !candidate.repair_actions.contains(&action) {
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
        RuntimeRepairActionKind::CreateManagedVenv => {
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
            let venv = managed::create_managed_venv(
                app,
                source_root,
                &PathBuf::from(&candidate.path),
                candidate_id,
                &profile,
                &requirements,
                &pip_index_urls,
            )?;
            Ok(Some(venv))
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
        RuntimeRepairActionKind::SelectDifferentRuntime => {
            Err("this runtime action requires a dedicated command".into())
        }
    }
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
mod tests {
    use super::*;
    use std::{fs, time::SystemTime};

    #[test]
    fn ready_candidate_id_for_path_matches_python_executable() {
        let temp_root = unique_temp_dir("runtime-match-python");
        let python = temp_root.join("python");
        fs::create_dir_all(&temp_root).unwrap();
        fs::write(&python, "").unwrap();
        let view = runtime_scan_view_with_ready_candidate("managed-venv", &python);

        assert_eq!(
            ready_candidate_id_for_path_in_view(&view, &python).as_deref(),
            Some("managed-venv")
        );

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn ready_candidate_id_for_path_matches_runtime_root() {
        let temp_root = unique_temp_dir("runtime-match-root");
        let runtime_root = temp_root.join("runtime");
        let python = runtime_root.join("bin").join("python3");
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::write(&python, "").unwrap();
        let view = runtime_scan_view_with_ready_candidate("managed-runtime", &python);

        assert_eq!(
            ready_candidate_id_for_path_in_view(&view, &runtime_root).as_deref(),
            Some("managed-runtime")
        );

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn ready_candidate_id_for_path_ignores_non_ready_candidates() {
        let temp_root = unique_temp_dir("runtime-match-non-ready");
        let python = temp_root.join("python");
        fs::create_dir_all(&temp_root).unwrap();
        fs::write(&python, "").unwrap();
        let mut view = runtime_scan_view_with_ready_candidate("missing", &python);
        view.candidates[0].status = resolver::RuntimeCandidateStatus::MissingCoreDeps;

        assert!(ready_candidate_id_for_path_in_view(&view, &python).is_none());

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn resolve_python_path_accepts_runtime_prefix() {
        let temp_root = unique_temp_dir("runtime-prefix");
        let python = temp_root.join("bin").join("python3");
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::write(&python, "").unwrap();

        assert_eq!(resolve_python_path(&temp_root).unwrap(), python);

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn resolve_python_path_rejects_prefix_without_python() {
        let temp_root = unique_temp_dir("runtime-prefix-missing");
        fs::create_dir_all(&temp_root).unwrap();

        let error = resolve_python_path(&temp_root).unwrap_err().to_string();

        assert!(error.contains("does not contain a Python executable"));
        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn pythonw_for_python_prefers_sibling_pythonw_executable() {
        let temp_root = unique_temp_dir("runtime-pythonw");
        let python = temp_root.join("python.exe");
        let pythonw = temp_root.join("pythonw.exe");
        fs::create_dir_all(&temp_root).unwrap();
        fs::write(&python, "").unwrap();
        fs::write(&pythonw, "").unwrap();

        assert_eq!(pythonw_for_python(&python), Some(pythonw));

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn pythonw_for_python_falls_back_when_pythonw_is_missing() {
        let temp_root = unique_temp_dir("runtime-pythonw-missing");
        let python = temp_root.join("python.exe");
        fs::create_dir_all(&temp_root).unwrap();
        fs::write(&python, "").unwrap();

        assert!(pythonw_for_python(&python).is_none());

        let _ = fs::remove_dir_all(temp_root);
    }

    fn runtime_scan_view_with_ready_candidate(id: &str, python: &Path) -> RuntimeScanView {
        RuntimeScanView {
            selected_candidate_id: Some(id.to_string()),
            recommended_action: Some(RuntimeRepairActionKind::Start),
            candidates: vec![RuntimeCandidateView {
                id: id.to_string(),
                python_id: Some(id.to_string()),
                label: id.to_string(),
                path: python.display().to_string(),
                display_path: python_probe::display_path(python),
                kind: resolver::RuntimeKind::ManagedVenv,
                version: Some("3.11.9".to_string()),
                status: resolver::RuntimeCandidateStatus::Ready,
                message: None,
                score: 100,
                selected: true,
                managed: true,
                missing_packages: Vec::new(),
                missing_imports: Vec::new(),
                python_version: Some("3.11.9".to_string()),
                warnings: Vec::new(),
                repair_actions: vec![RuntimeRepairActionKind::Start],
            }],
            message: None,
        }
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
    }
}
