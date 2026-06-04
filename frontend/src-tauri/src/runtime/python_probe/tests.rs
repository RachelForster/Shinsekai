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
fn managed_python_sources_use_only_install_dir_runtime_root() {
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

    let sources = managed_python_sources(vec![RuntimeRootCandidate { root: install_root }]);

    assert_eq!(sources.len(), 1);
    assert_eq!(sources[0].id(), INSTALL_DIR_RUNTIME_ID);
    assert!(sources
        .iter()
        .all(|source| matches!(source.kind, PythonKind::Managed)));
    assert!(sources
        .iter()
        .any(|source| source.executable == install_python));
    assert!(!sources.iter().any(|source| source.executable == app_python));

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn install_dir_runtime_root_is_source_root_runtime() {
    let source_root = std::path::Path::new("/opt/Shinsekai/resources");

    assert_eq!(
        install_dir_runtime_root(source_root),
        source_root.join("runtime")
    );
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

fn unique_temp_dir(name: &str) -> std::path::PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
}
