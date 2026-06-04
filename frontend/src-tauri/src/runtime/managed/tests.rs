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
