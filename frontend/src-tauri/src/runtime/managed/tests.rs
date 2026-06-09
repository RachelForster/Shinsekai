use super::*;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::time::{SystemTime, UNIX_EPOCH};

#[test]
fn configure_pip_install_command_adds_selected_index_url_argument() {
    let mut command = Command::new("python");

    configure_pip_install_command(
        &mut command,
        Path::new("python"),
        Some("https://mirror.example/simple/"),
    );

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
    assert!(envs.contains(&("PYTHONUTF8".to_string(), Some("1".to_string()))));
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

#[cfg(unix)]
#[test]
fn ensure_python_pip_available_bootstraps_with_ensurepip() {
    let temp_root = unique_temp_dir("runtime-ensurepip");
    fs::create_dir_all(&temp_root).unwrap();
    let fake_python = temp_root.join("python");
    let log = temp_root.join("log.txt");
    let state = temp_root.join("pip-ready");
    write_executable(
        &fake_python,
        &format!(
            r#"#!/bin/sh
printf '%s\n' "$*" >> "{log}"
if [ "$*" = "-m pip --version" ]; then
  if [ -f "{state}" ]; then
    exit 0
  fi
  touch "{state}"
  exit 7
fi
if [ "$*" = "-m ensurepip --upgrade --default-pip" ]; then
  exit 0
fi
exit 9
"#,
            log = log.display(),
            state = state.display()
        ),
    );

    ensure_python_pip_available(&fake_python).unwrap();

    let log = fs::read_to_string(log).unwrap();
    assert!(log.contains("-m pip --version"));
    assert!(log.contains("-m ensurepip --upgrade --default-pip"));

    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn install_runtime_requirements_tries_configured_indexes_in_order() {
    let temp_root = unique_temp_dir("runtime-index-install");
    fs::create_dir_all(&temp_root).unwrap();
    let fake_python = temp_root.join("python");
    let requirements = temp_root.join("requirements.txt");
    let log = temp_root.join("log.txt");
    fs::write(&requirements, "pydantic\n").unwrap();
    write_executable(
        &fake_python,
        &format!(
            r#"#!/bin/sh
printf '%s\n' "$*" >> "{log}"
case "$*" in
  *"-m pip --version"*)
    exit 0
    ;;
  *"-m ensurepip --upgrade --default-pip"*)
    exit 0
    ;;
  *"-i https://bad.example/simple/"*)
    exit 12
    ;;
  *"-i https://good.example/simple/"*)
    exit 0
    ;;
esac
exit 11
"#,
            log = log.display()
        ),
    );

    install_runtime_requirements(
        &fake_python,
        &requirements,
        &[
            "https://bad.example/simple/".to_string(),
            "https://good.example/simple/".to_string(),
        ],
        |_| {},
    )
    .unwrap();

    let log = fs::read_to_string(log).unwrap();
    assert!(log.contains("-i https://bad.example/simple/"));
    assert!(log.contains("-i https://good.example/simple/"));
    assert!(!log.contains("--no-index"));
    assert!(!log.contains("--find-links"));

    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn install_runtime_requirements_streams_pip_output() {
    let temp_root = unique_temp_dir("runtime-stream-install");
    fs::create_dir_all(&temp_root).unwrap();
    let fake_python = temp_root.join("python");
    let requirements = temp_root.join("requirements.txt");
    fs::write(&requirements, "pydantic\n").unwrap();
    write_executable(
        &fake_python,
        r#"#!/bin/sh
case "$*" in
  *"-m pip --version"*)
    exit 0
    ;;
  *"-m pip install"*)
    echo "Collecting pydantic"
    echo "Installing collected packages: pydantic" >&2
    exit 0
    ;;
esac
exit 11
"#,
    );
    let mut lines = Vec::new();

    install_runtime_requirements(&fake_python, &requirements, &[], |line| {
        lines.push(line.to_string());
    })
    .unwrap();

    assert!(lines.iter().any(|line| line == "Collecting pydantic"));
    assert!(lines
        .iter()
        .any(|line| line == "Installing collected packages: pydantic"));

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

fn unique_temp_dir(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
}

#[cfg(unix)]
fn write_executable(path: &Path, text: &str) {
    fs::write(path, text).unwrap();
    let mut permissions = fs::metadata(path).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(path, permissions).unwrap();
}
