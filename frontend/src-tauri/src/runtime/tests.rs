use super::*;
use std::{fs, time::SystemTime};

#[test]
fn manual_install_command_quotes_windows_paths_for_powershell() {
    assert_eq!(
        manual_install_command_for_shell(
            r"C:\Users\O'Brien\Shinsekai runtime\python.exe",
            r"C:\Program Files\Shinsekai\requirements-runtime-core.txt",
            true,
        ),
        "& 'C:\\Users\\O''Brien\\Shinsekai runtime\\python.exe' -m pip install --requirement 'C:\\Program Files\\Shinsekai\\requirements-runtime-core.txt'"
    );
}

#[test]
fn manual_install_command_quotes_posix_paths() {
    assert_eq!(
        manual_install_command_for_shell(
            "/Users/o'brien/Shinsekai runtime/bin/python3",
            "/Applications/Shinsekai/resources/requirements-runtime-core.txt",
            false,
        ),
        "'/Users/o'\\''brien/Shinsekai runtime/bin/python3' -m pip install --requirement '/Applications/Shinsekai/resources/requirements-runtime-core.txt'"
    );
}

#[test]
fn manual_install_command_uses_profile_requirements() {
    let source_root = unique_temp_dir("manual-profile-requirements");
    fs::create_dir_all(&source_root).unwrap();
    fs::write(
        source_root.join(manifest::MANIFEST_FILE),
        r#"{
            "version": "test",
            "profiles": {
                "desktop-core": { "requirements": "requirements-runtime-core.txt" },
                "local-ai": {
                    "extends": "desktop-core",
                    "requirements": "requirements-runtime-local-ai.txt"
                }
            }
        }"#,
    )
    .unwrap();

    assert_eq!(
        runtime_requirements_path(&source_root, "local-ai"),
        source_root.join("requirements-runtime-local-ai.txt")
    );

    let _ = fs::remove_dir_all(source_root);
}

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

#[test]
fn install_runtime_deps_is_supported_for_ready_runtime_candidate() {
    let python = Path::new("/opt/Shinsekai/runtime/bin/python3");
    let view = runtime_scan_view_with_ready_candidate("install-dir-runtime", python);

    assert!(runtime_action_supported(
        &view.candidates[0],
        RuntimeRepairActionKind::InstallRuntimeDeps
    ));
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
            kind: resolver::RuntimeKind::Managed,
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
