
use super::*;

#[test]
fn preferred_python_source_keeps_saved_candidate_id_through_dedupe() {
    let temp_root = unique_temp_dir("runtime-preference");
    let data_dir = temp_root.join("app-data");
    let runtime_dir = data_dir.join("runtime");
    let python = temp_root.join("python");
    fs::create_dir_all(&runtime_dir).unwrap();
    fs::write(&python, "").unwrap();
    fs::write(
        runtime_dir.join(RUNTIME_PREFERENCE_FILE),
        serde_json::json!({
            "candidateId": "python-conda-original",
            "pythonPath": python.display().to_string(),
            "label": "conda env shinsekai",
            "savedAtMs": 1
        })
        .to_string(),
    )
    .unwrap();

    let preferred = preferred_python_source(&data_dir).unwrap();
    let duplicate = PythonSource {
        id_override: None,
        executable: python,
        label: "PATH python".to_string(),
        kind: PythonKind::Path,
        priority: 1_000,
    };
    let deduped = dedupe_python_sources(vec![preferred, duplicate]);

    assert_eq!(deduped.len(), 1);
    assert_eq!(deduped[0].id(), "python-conda-original");

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn preferred_python_source_keeps_missing_saved_runtime_visible() {
    let temp_root = unique_temp_dir("runtime-missing-preference");
    let data_dir = temp_root.join("app-data");
    let runtime_dir = data_dir.join("runtime");
    let python = temp_root.join("missing-python");
    fs::create_dir_all(&runtime_dir).unwrap();
    fs::write(
        runtime_dir.join(RUNTIME_PREFERENCE_FILE),
        serde_json::json!({
            "candidateId": "python-saved-missing",
            "pythonPath": python.display().to_string(),
            "label": "saved missing runtime",
            "savedAtMs": 1
        })
        .to_string(),
    )
    .unwrap();

    let preferred = preferred_python_source(&data_dir).unwrap();
    let install = probe_python_source(preferred);

    assert_eq!(install.id, "python-saved-missing");
    assert_eq!(install.executable, python);
    assert_eq!(install.label, "saved missing runtime");
    assert_eq!(
        install.probe_error.as_deref(),
        Some("python executable not found")
    );

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn dedupe_python_sources_keeps_the_highest_priority_source() {
    let temp_root = unique_temp_dir("runtime-priority");
    let python = temp_root.join("python");
    fs::create_dir_all(&temp_root).unwrap();
    fs::write(&python, "").unwrap();
    let path_source = PythonSource {
        id_override: None,
        executable: python.clone(),
        label: "PATH python".to_string(),
        kind: PythonKind::Path,
        priority: 1_000,
    };
    let explicit_source = PythonSource {
        id_override: Some("explicit-python".to_string()),
        executable: python,
        label: "SHINSEKAI_PYTHON".to_string(),
        kind: PythonKind::Explicit,
        priority: 10_000,
    };

    let deduped = dedupe_python_sources(vec![path_source, explicit_source]);

    assert_eq!(deduped.len(), 1);
    assert_eq!(deduped[0].id(), "explicit-python");
    assert_eq!(deduped[0].label, "SHINSEKAI_PYTHON");

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn conda_env_prefixes_cover_envs_and_root_level_layouts() {
    let root = PathBuf::from("/opt/micromamba");

    let prefixes = conda_env_prefixes_from_roots(vec![root.clone()], DEFAULT_CONDA_ENV);

    assert_eq!(
        prefixes,
        vec![
            root.join("envs").join(DEFAULT_CONDA_ENV),
            root.join(DEFAULT_CONDA_ENV)
        ]
    );
}

#[test]
fn py_launcher_parser_preserves_windows_paths_with_spaces() {
    let path =
        parse_py_launcher_python_path(r#" -V:3.12 *        C:\Program Files\Python312\python.exe"#)
            .unwrap();

    assert_eq!(
        path,
        PathBuf::from(r"C:\Program Files\Python312\python.exe")
    );
}

#[test]
fn py_launcher_parser_accepts_unc_paths() {
    let path =
        parse_py_launcher_python_path(r#" -V:3.11          \\server\share\Python311\python.exe"#)
            .unwrap();

    assert_eq!(path, PathBuf::from(r"\\server\share\Python311\python.exe"));
}

#[test]
fn py_launcher_parser_keeps_previous_last_field_fallback() {
    let path = parse_py_launcher_python_path("legacy-format /opt/python/bin/python3").unwrap();

    assert_eq!(path, PathBuf::from("/opt/python/bin/python3"));
}

#[test]
fn active_conda_priority_stays_above_managed_venv_fallback() {
    let active_other_conda = active_conda_priority("research", DEFAULT_CONDA_ENV);

    assert!(active_other_conda > 5_500);
    assert_eq!(
        active_conda_priority(DEFAULT_CONDA_ENV, DEFAULT_CONDA_ENV),
        6_500
    );
}

#[test]
fn pyenv_asdf_and_uv_sources_find_common_python_layouts() {
    let temp_root = unique_temp_dir("runtime-shims");
    let pyenv = temp_root.join("pyenv");
    let asdf = temp_root.join("asdf");
    let uv = temp_root.join("uv");

    let pyenv_python = pyenv
        .join("versions")
        .join("3.11.9")
        .join("bin")
        .join("python3");
    let asdf_python = asdf
        .join("installs")
        .join("python")
        .join("3.12.3")
        .join("bin")
        .join("python3");
    let uv_python = uv
        .join("cpython-3.12.4-linux-x86_64-gnu")
        .join("bin")
        .join("python3");
    let pyenv_shim = pyenv.join("shims").join("python");

    for python in [&pyenv_python, &asdf_python, &uv_python, &pyenv_shim] {
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::write(python, "").unwrap();
    }

    let pyenv_sources = pyenv_python_sources(&pyenv);
    let asdf_sources = asdf_python_sources(&asdf);
    let uv_sources = uv_python_sources(&uv);

    assert!(pyenv_sources
        .iter()
        .any(|source| source.executable == pyenv_python));
    assert!(pyenv_sources
        .iter()
        .any(|source| source.executable == pyenv_shim));
    assert!(asdf_sources
        .iter()
        .any(|source| source.executable == asdf_python));
    assert!(uv_sources
        .iter()
        .any(|source| source.executable == uv_python));

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn app_data_runtime_sources_skip_staging_and_previous_artifacts() {
    let temp_root = unique_temp_dir("runtime-app-data-artifacts");
    let data_dir = temp_root.join("app-data");
    let runtime_root = data_dir
        .join("runtime")
        .join("runtimes")
        .join("runtime-current");
    let previous_runtime_root = data_dir
        .join("runtime")
        .join("runtimes")
        .join("runtime-current.previous-1");
    let staging_runtime_root = data_dir
        .join("runtime")
        .join("runtimes")
        .join("runtime-current.tmp-1");
    let venv_root = data_dir.join("runtime").join("venvs").join("venv-current");
    let previous_venv_root = data_dir
        .join("runtime")
        .join("venvs")
        .join("venv-current.previous-1");
    let staging_venv_root = data_dir
        .join("runtime")
        .join("venvs")
        .join("venv-current.tmp-1");

    for root in [
        &runtime_root,
        &previous_runtime_root,
        &staging_runtime_root,
        &venv_root,
        &previous_venv_root,
        &staging_venv_root,
    ] {
        let python = root.join("bin").join("python3");
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::write(python, "").unwrap();
    }

    let sources = app_data_runtime_sources(&data_dir);

    assert_eq!(sources.len(), 2);
    assert!(sources
        .iter()
        .any(|source| source.executable == runtime_root.join("bin").join("python3")));
    assert!(sources
        .iter()
        .any(|source| source.executable == venv_root.join("bin").join("python3")));
    assert!(!sources.iter().any(|source| source
        .executable
        .display()
        .to_string()
        .contains(".previous-")));
    assert!(!sources.iter().any(|source| source
        .executable
        .display()
        .to_string()
        .contains(".tmp-")));

    let _ = fs::remove_dir_all(temp_root);
}

fn unique_temp_dir(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
}
