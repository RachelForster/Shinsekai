use super::*;
use std::{
    fs,
    time::{SystemTime, UNIX_EPOCH},
};

#[test]
fn dedupe_python_sources_keeps_the_highest_priority_managed_source() {
    let temp_root = unique_temp_dir("runtime-priority");
    let python = temp_root.join("python");
    fs::create_dir_all(&temp_root).unwrap();
    fs::write(&python, "").unwrap();
    let lower_priority = PythonSource {
        id_override: Some("lower".to_string()),
        executable: python.clone(),
        label: "lower priority managed runtime".to_string(),
        kind: PythonKind::Managed,
        priority: 100,
    };
    let higher_priority = PythonSource {
        id_override: Some("higher".to_string()),
        executable: python,
        label: "higher priority managed runtime".to_string(),
        kind: PythonKind::Managed,
        priority: 200,
    };

    let deduped = dedupe_python_sources(vec![lower_priority, higher_priority]);

    assert_eq!(deduped.len(), 1);
    assert_eq!(deduped[0].id(), "higher");
    assert_eq!(deduped[0].label, "higher priority managed runtime");

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn install_dir_runtime_priority_stays_above_app_data_runtime() {
    assert!(PRIORITY_INSTALL_DIR_RUNTIME > 8_000);
}

#[test]
fn display_path_strips_windows_verbatim_prefixes() {
    assert_eq!(
        display_path_text(r"\\?\D:\Shinsekai\runtime"),
        r"D:\Shinsekai\runtime"
    );
    assert_eq!(
        display_path_text(r"\\?\UNC\server\share\runtime"),
        r"\\server\share\runtime"
    );
    assert_eq!(
        display_path_text("//?/D:/Shinsekai/runtime"),
        "D:/Shinsekai/runtime"
    );
    assert_eq!(
        display_path_text("//?/UNC/server/share/runtime"),
        "//server/share/runtime"
    );
}

#[test]
fn managed_python_sources_use_only_runtime_roots_and_app_data() {
    let temp_root = unique_temp_dir("runtime-managed-sources");
    let install_root = temp_root.join("resources").join("runtime");
    let app_data = temp_root.join("app-data");
    let app_runtime = app_data
        .join("runtime")
        .join("runtimes")
        .join("runtime-current");
    let install_python = install_root.join("bin").join("python3");
    let app_python = app_runtime.join("bin").join("python3");
    for python in [&install_python, &app_python] {
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::write(python, "").unwrap();
    }

    let sources = managed_python_sources(
        vec![RuntimeRootCandidate {
            root: install_root,
            kind: RuntimeRootKind::InstallDir,
        }],
        Some(&app_data),
    );

    assert_eq!(sources.len(), 2);
    assert!(sources
        .iter()
        .all(|source| matches!(source.kind, PythonKind::Managed)));
    assert!(sources
        .iter()
        .any(|source| source.executable == install_python));
    assert!(sources.iter().any(|source| source.executable == app_python));

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn python_in_prefix_accepts_versioned_pbs_binary() {
    let temp_root = unique_temp_dir("runtime-versioned-python");
    let python = temp_root.join("bin").join("python3.10");
    fs::create_dir_all(python.parent().unwrap()).unwrap();
    fs::write(&python, "").unwrap();

    assert_eq!(python_in_prefix(&temp_root), Some(python));

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

fn unique_temp_dir(name: &str) -> std::path::PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
}
