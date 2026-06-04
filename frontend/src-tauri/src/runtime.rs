use std::{env, error::Error, path::Path, path::PathBuf, process::Command};

use tauri::{Emitter, Manager, Runtime};

mod managed;
mod manifest;
mod python_probe;
mod resolver;

pub use resolver::{
    RuntimeCandidateStatus, RuntimeCandidateView, RuntimeRepairActionKind, RuntimeScanView,
};

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
    if let Some(message) =
        strict_explicit_runtime_failure_message(&view, candidate_id, runtime_strict())
    {
        return Err(message.into());
    }
    let Some(candidate) = resolver::ready_candidate(&view, candidate_id) else {
        return Err(view
            .message
            .unwrap_or_else(|| {
                "no complete Python runtime found; set SHINSEKAI_PYTHON, provide runtime/, install the shinsekai conda env, or configure runtime_manifest.json".to_string()
            })
            .into());
    };
    let path = PathBuf::from(&candidate.path);
    Ok(PythonRuntime {
        command: Command::new(path),
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

pub fn ready_candidate_id_for_path<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
    repaired_path: &Path,
) -> Option<String> {
    let view = scan_runtime_view(app, source_root);
    ready_candidate_id_for_path_in_view(&view, repaired_path)
}

pub fn save_runtime_preference<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
    candidate_id: &str,
) -> RuntimeResult<()> {
    let view = scan_runtime_view(app, source_root);
    let candidate = view
        .candidates
        .into_iter()
        .find(|candidate| candidate.id == candidate_id)
        .ok_or_else(|| format!("runtime candidate not found: {candidate_id}"))?;
    if candidate.status != resolver::RuntimeCandidateStatus::Ready {
        return Err(format!(
            "runtime candidate is not ready: {}",
            candidate
                .message
                .unwrap_or_else(|| candidate_id.to_string())
        )
        .into());
    }
    if candidate.path.trim().is_empty() {
        return Err("runtime candidate does not have a Python path".into());
    }
    python_probe::save_runtime_preference(
        app,
        &candidate.id,
        &PathBuf::from(candidate.path),
        &candidate.label,
    )
}

pub fn save_runtime_preference_for_path<R: Runtime>(
    app: &impl Manager<R>,
    path: &Path,
) -> RuntimeResult<String> {
    let python = resolve_python_path(path)?;
    let candidate_id = python_probe::explicit_python_id(&python);
    let label = format!("Custom Python {}", python.display());
    python_probe::save_runtime_preference(app, &candidate_id, &python, &label)?;
    Ok(candidate_id)
}

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

fn runtime_strict() -> bool {
    env::var("SHINSEKAI_RUNTIME_STRICT")
        .map(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "on"))
        .unwrap_or(false)
}

fn strict_explicit_runtime_failure_message(
    view: &RuntimeScanView,
    candidate_id: Option<&str>,
    strict: bool,
) -> Option<String> {
    if candidate_id.is_some() || !strict {
        return None;
    }
    view.candidates
        .iter()
        .find(|candidate| {
            candidate.kind == resolver::RuntimeKind::Explicit
                && candidate.status != resolver::RuntimeCandidateStatus::Ready
        })
        .map(|candidate| {
            format!(
                "explicit runtime candidate failed under SHINSEKAI_RUNTIME_STRICT=1: {}",
                candidate
                    .message
                    .clone()
                    .unwrap_or_else(|| candidate.label.clone())
            )
        })
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
    fn broken_explicit_runtime_does_not_block_fallback_without_strict_mode() {
        let view = runtime_scan_view_with_explicit_failure_and_ready_candidate();

        assert!(strict_explicit_runtime_failure_message(&view, None, false).is_none());
        assert_eq!(
            resolver::ready_candidate(&view, None).map(|candidate| candidate.id.as_str()),
            Some("managed-ready")
        );
    }

    #[test]
    fn broken_explicit_runtime_blocks_fallback_in_strict_mode() {
        let view = runtime_scan_view_with_explicit_failure_and_ready_candidate();

        let message = strict_explicit_runtime_failure_message(&view, None, true)
            .expect("strict mode should report the broken explicit candidate");

        assert!(message.contains("SHINSEKAI_RUNTIME_STRICT=1"));
        assert!(message.contains("missing explicit runtime"));
    }

    #[test]
    fn strict_mode_does_not_override_explicit_candidate_selection() {
        let view = runtime_scan_view_with_explicit_failure_and_ready_candidate();

        assert!(
            strict_explicit_runtime_failure_message(&view, Some("managed-ready"), true).is_none()
        );
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

    fn runtime_scan_view_with_explicit_failure_and_ready_candidate() -> RuntimeScanView {
        let ready_python = PathBuf::from("/tmp/managed-ready-python");
        let mut view = runtime_scan_view_with_ready_candidate("managed-ready", &ready_python);
        view.candidates.insert(
            0,
            RuntimeCandidateView {
                id: "explicit-broken".to_string(),
                python_id: Some("explicit-broken".to_string()),
                label: "SHINSEKAI_PYTHON".to_string(),
                path: "/missing/python".to_string(),
                kind: resolver::RuntimeKind::Explicit,
                version: None,
                status: resolver::RuntimeCandidateStatus::BrokenPython,
                message: Some("missing explicit runtime".to_string()),
                score: 10_000,
                selected: false,
                managed: false,
                missing_packages: Vec::new(),
                missing_imports: Vec::new(),
                python_version: None,
                warnings: Vec::new(),
                repair_actions: vec![RuntimeRepairActionKind::SelectDifferentRuntime],
            },
        );
        view
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
    }
}
