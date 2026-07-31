use super::*;
use std::collections::HashMap;
use std::env;
use std::ffi::OsString;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

static PYTORCH_WHEEL_ENV_LOCK: Mutex<()> = Mutex::new(());

struct EnvRestore {
    name: &'static str,
    previous: Option<OsString>,
}

impl EnvRestore {
    fn capture(name: &'static str) -> Self {
        Self {
            name,
            previous: env::var_os(name),
        }
    }
}

impl Drop for EnvRestore {
    fn drop(&mut self) {
        if let Some(value) = self.previous.take() {
            env::set_var(self.name, value);
        } else {
            env::remove_var(self.name);
        }
    }
}

#[test]
fn configure_pip_install_command_adds_selected_index_url_argument() {
    let temp_root = unique_temp_dir("configure-pip-command");
    let python_parent = temp_root.join("bin");
    let python = python_parent.join(if cfg!(windows) {
        "python.exe"
    } else {
        "python"
    });
    fs::create_dir_all(&python_parent).unwrap();
    fs::write(&python, "").unwrap();
    let mut command = Command::new(&python);

    configure_pip_install_command(
        &mut command,
        &python,
        Some("https://mirror.example/simple/"),
    )
    .unwrap();

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
    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn pytorch_force_reinstall_command_limits_replacement_to_the_stack() {
    let temp_root = unique_temp_dir("pytorch-force-command");
    let python_parent = temp_root.join("bin");
    let python = python_parent.join(if cfg!(windows) {
        "python.exe"
    } else {
        "python"
    });
    fs::create_dir_all(&python_parent).unwrap();
    fs::write(&python, "").unwrap();
    let command = pytorch_install_command(
        &python,
        &temp_root.join("torch-requirements.txt"),
        "https://download.pytorch.org/whl/cu128",
        true,
    )
    .unwrap();
    let args = command
        .get_args()
        .map(|arg| arg.to_string_lossy().to_string())
        .collect::<Vec<_>>();

    assert!(args.iter().any(|arg| arg == "--force-reinstall"));
    assert!(args.iter().any(|arg| arg == "--upgrade"));
    assert!(args.iter().any(|arg| arg == "--no-deps"));
    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn pytorch_dependency_repair_command_does_not_force_reinstall() {
    let temp_root = unique_temp_dir("pytorch-repair-command");
    let python_parent = temp_root.join("bin");
    let python = python_parent.join(if cfg!(windows) {
        "python.exe"
    } else {
        "python"
    });
    fs::create_dir_all(&python_parent).unwrap();
    fs::write(&python, "").unwrap();
    let command = pytorch_install_command(
        &python,
        &temp_root.join("torch-requirements.txt"),
        "https://download.pytorch.org/whl/cu128",
        false,
    )
    .unwrap();
    let args = command
        .get_args()
        .map(|arg| arg.to_string_lossy().to_string())
        .collect::<Vec<_>>();

    assert!(!args.iter().any(|arg| arg == "--force-reinstall"));
    assert!(!args.iter().any(|arg| arg == "--upgrade"));
    assert!(!args.iter().any(|arg| arg == "--no-deps"));
    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn ordinary_runtime_install_is_constrained_to_the_host_pytorch_stack() {
    let temp_root = unique_temp_dir("pytorch-constraints-command");
    let python_parent = temp_root.join("bin");
    let python = python_parent.join(if cfg!(windows) {
        "python.exe"
    } else {
        "python"
    });
    let requirements = temp_root.join("plugin-requirements.txt");
    let constraints = temp_root.join("host-pytorch.txt");
    fs::create_dir_all(&python_parent).unwrap();
    fs::write(&python, "").unwrap();
    let mut command = pip_install_command(&python, &requirements, None).unwrap();
    apply_pip_constraints(&mut command, Some(&constraints));
    let args = command
        .get_args()
        .map(|arg| arg.to_string_lossy().to_string())
        .collect::<Vec<_>>();

    assert!(args
        .windows(2)
        .any(|pair| { pair[0] == "-c" && pair[1] == constraints.to_string_lossy().as_ref() }));
    let _ = fs::remove_dir_all(temp_root);
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
        &temp_root,
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

    install_runtime_requirements(&fake_python, &requirements, &temp_root, &[], |line| {
        lines.push(line.to_string());
    })
    .unwrap();

    assert!(lines.iter().any(|line| line == "Collecting pydantic"));
    assert!(lines
        .iter()
        .any(|line| line == "Installing collected packages: pydantic"));

    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn install_runtime_requirements_detects_source_replaced_while_pip_runs() {
    let temp_root = unique_temp_dir("runtime-replaced-requirements");
    fs::create_dir_all(&temp_root).unwrap();
    let fake_python = temp_root.join("python");
    let requirements = temp_root.join("requirements.txt");
    let preserved = temp_root.join("preserved-requirements.txt");
    fs::write(&requirements, "pydantic\n").unwrap();
    write_executable(
        &fake_python,
        &format!(
            r#"#!/bin/sh
case "$*" in
  *"-m pip --version"*)
    exit 0
    ;;
  *"-m pip install"*)
    mv "{requirements}" "{preserved}"
    printf 'peer\n' > "{requirements}"
    exit 0
    ;;
esac
exit 1
"#,
            requirements = requirements.display(),
            preserved = preserved.display(),
        ),
    );

    let error = install_runtime_requirements(&fake_python, &requirements, &temp_root, &[], |_| {})
        .unwrap_err();

    assert!(error.to_string().contains("changed identity"));
    assert_eq!(fs::read_to_string(&requirements).unwrap(), "peer\n");
    assert_eq!(fs::read_to_string(&preserved).unwrap(), "pydantic\n");
    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn install_runtime_requirements_detects_python_replaced_while_pip_runs() {
    let temp_root = unique_temp_dir("runtime-replaced-python");
    fs::create_dir_all(&temp_root).unwrap();
    let fake_python = temp_root.join("python");
    let preserved_python = temp_root.join("preserved-python");
    let requirements = temp_root.join("requirements.txt");
    fs::write(&requirements, "pydantic\n").unwrap();
    write_executable(
        &fake_python,
        &format!(
            r#"#!/bin/sh
case "$*" in
  *"-m pip --version"*)
    exit 0
    ;;
  *"-m pip install"*)
    mv "{python}" "{preserved}"
    printf '#!/bin/sh\nexit 0\n' > "{python}"
    chmod +x "{python}"
    exit 0
    ;;
esac
exit 1
"#,
            python = fake_python.display(),
            preserved = preserved_python.display(),
        ),
    );

    let error = install_runtime_requirements(&fake_python, &requirements, &temp_root, &[], |_| {})
        .unwrap_err();

    assert!(error
        .to_string()
        .contains("runtime Python changed identity"));
    assert!(fake_python.is_file());
    assert!(preserved_python.is_file());
    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn torch_split_uses_writable_runtime_temp_and_preserves_original_requirement_base() {
    let temp_root = unique_temp_dir("runtime-torch-temp-root");
    let packaged_source = temp_root.join("read-only packaged resources");
    let runtime_temp = temp_root.join("app-data").join("runtime");
    fs::create_dir_all(&packaged_source).unwrap();
    let fake_python = temp_root.join("python");
    let requirements = packaged_source.join("requirements-runtime-local-ai.txt");
    let included = packaged_source.join("requirements-runtime-core.txt");
    let log = temp_root.join("log.txt");
    fs::write(
        &requirements,
        "torch==2.4.1\n-r requirements-runtime-core.txt\n",
    )
    .unwrap();
    fs::write(&included, "pydantic\n").unwrap();
    write_executable(
        &fake_python,
        &format!(
            r#"#!/bin/sh
printf '%s\n' "$*" >> "{log}"
previous=""
for argument in "$@"; do
  if [ "$previous" = "-r" ] && [ -f "$argument" ]; then
    sed 's/^/requirements: /' "$argument" >> "{log}"
  fi
  previous="$argument"
done
exit 0
"#,
            log = log.display()
        ),
    );

    install_runtime_requirements(&fake_python, &requirements, &runtime_temp, &[], |_| {}).unwrap();

    let log = fs::read_to_string(log).unwrap();
    assert!(log.contains(&runtime_temp.canonicalize().unwrap().display().to_string()));
    assert!(log.contains(&format!(
        "requirements: -r \"{}\"",
        included.canonicalize().unwrap().display()
    )));
    assert_eq!(
        fs::read_dir(&packaged_source)
            .unwrap()
            .filter_map(Result::ok)
            .count(),
        2
    );
    assert!(fs::read_dir(&runtime_temp).unwrap().next().is_none());

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn partition_torch_requirement_lines_splits_pytorch_packages() {
    let lines = vec![
        "-r requirements-runtime-core.txt".to_string(),
        "torch==2.4.1".to_string(),
        "torchvision>=0.19".to_string(),
        "torchaudio".to_string(),
        "sentence-transformers".to_string(),
        "git+https://example.invalid/package.git".to_string(),
    ];

    let (torch_lines, other_lines) = pytorch::partition_requirement_lines(&lines);

    assert_eq!(
        torch_lines,
        vec![
            "torch==2.4.1".to_string(),
            "torchvision>=0.19".to_string(),
            "torchaudio".to_string()
        ]
    );
    assert_eq!(
        other_lines,
        vec![
            "-r requirements-runtime-core.txt".to_string(),
            "sentence-transformers".to_string(),
            "git+https://example.invalid/package.git".to_string()
        ]
    );
}

#[test]
fn temporary_requirements_use_an_explicit_writable_root_without_cwd_fallback() {
    let error = write_temp_requirements(
        Path::new("requirements.txt"),
        "shinsekai-test",
        &["pydantic".to_string()],
    )
    .unwrap_err();
    assert!(error.to_string().contains("must be absolute"));

    let temp_root = unique_temp_dir("runtime-temp-requirements");
    let read_only_source = temp_root.join("packaged-resources");
    let writable_runtime = temp_root.join("app-data").join("runtime");
    fs::create_dir_all(&read_only_source).unwrap();
    fs::write(read_only_source.join("requirements.txt"), "torch\n").unwrap();

    let generated = write_temp_requirements(
        &writable_runtime,
        "shinsekai-test",
        &["pydantic".to_string(), "requests".to_string()],
    )
    .unwrap();

    assert_eq!(
        generated.parent(),
        Some(writable_runtime.canonicalize().unwrap().as_path())
    );
    assert_ne!(generated.parent(), Some(read_only_source.as_path()));
    assert_eq!(
        fs::read_to_string(&generated).unwrap(),
        "pydantic\nrequests"
    );

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn temporary_requirements_cleanup_preserves_a_replacement_file() {
    let temp_root = unique_temp_dir("runtime-temp-requirements-identity");
    let runtime_root = temp_root.join("runtime");
    let generated =
        write_temp_requirements(&runtime_root, "shinsekai-test", &["pydantic".to_string()])
            .unwrap();
    let generated_path = generated.path.clone();
    let preserved = generated_path.with_extension("preserved");
    fs::rename(&generated_path, &preserved).unwrap();
    fs::write(&generated_path, "peer\n").unwrap();

    drop(generated);

    assert_eq!(fs::read_to_string(&generated_path).unwrap(), "peer\n");
    assert_eq!(fs::read_to_string(&preserved).unwrap(), "pydantic");
    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn temporary_requirements_cleanup_preserves_replacement_parent_contents() {
    let temp_root = unique_temp_dir("runtime-temp-requirements-parent-identity");
    let runtime_root = temp_root.join("runtime");
    let generated =
        write_temp_requirements(&runtime_root, "shinsekai-test", &["pydantic".to_string()])
            .unwrap();
    let generated_path = generated.path.clone();
    let generated_name = generated_path.file_name().unwrap().to_owned();
    let preserved_runtime = temp_root.join("preserved-runtime");
    fs::rename(&runtime_root, &preserved_runtime).unwrap();
    fs::create_dir_all(&runtime_root).unwrap();
    fs::write(runtime_root.join(&generated_name), "peer\n").unwrap();

    drop(generated);

    assert_eq!(
        fs::read_to_string(runtime_root.join(&generated_name)).unwrap(),
        "peer\n"
    );
    assert_eq!(
        fs::read_to_string(preserved_runtime.join(&generated_name)).unwrap(),
        "pydantic"
    );
    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn temporary_requirements_reject_a_linked_runtime_directory() {
    use std::os::unix::fs::symlink;

    let temp_root = unique_temp_dir("runtime-linked-temp-requirements");
    let external = temp_root.join("external");
    let alias = temp_root.join("runtime");
    fs::create_dir_all(&external).unwrap();
    symlink(&external, &alias).unwrap();

    let error =
        write_temp_requirements(&alias, "shinsekai-test", &["requests".to_string()]).unwrap_err();

    assert!(error.to_string().contains("symbolic link"));
    assert!(fs::read_dir(&external).unwrap().next().is_none());
    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn temporary_requirements_reject_a_linked_runtime_parent() {
    use std::os::unix::fs::symlink;

    let temp_root = unique_temp_dir("runtime-linked-parent-temp-requirements");
    let external = temp_root.join("external");
    let alias = temp_root.join("alias");
    fs::create_dir_all(&external).unwrap();
    symlink(&external, &alias).unwrap();

    let error = write_temp_requirements(
        &alias.join("runtime"),
        "shinsekai-test",
        &["requests".to_string()],
    )
    .unwrap_err();

    assert!(error.to_string().contains("symbolic link"));
    assert!(!external.join("runtime").exists());
    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn pytorch_wheel_index_url_matches_cuda_driver_version() {
    assert_eq!(
        pytorch::wheel_index_url_for_cuda_version(
            Some((13, 2)),
            "https://download.pytorch.org/whl".to_string()
        )
        .0,
        "https://download.pytorch.org/whl/cu128"
    );
    assert_eq!(
        pytorch::wheel_index_url_for_cuda_version(
            Some((12, 8)),
            "https://download.pytorch.org/whl".to_string()
        )
        .0,
        "https://download.pytorch.org/whl/cu128"
    );
    assert_eq!(
        pytorch::wheel_index_url_for_cuda_version(
            None,
            "https://download.pytorch.org/whl".to_string()
        )
        .0,
        "https://download.pytorch.org/whl/cpu"
    );
    assert_eq!(
        pytorch::wheel_index_url_for_cuda_version(
            Some((12, 4)),
            "https://download.pytorch.org/whl".to_string()
        )
        .0,
        "https://download.pytorch.org/whl/cpu"
    );
    assert_eq!(
        pytorch::wheel_index_url_for_cuda_version(
            Some((12, 1)),
            "https://download.pytorch.org/whl".to_string()
        )
        .0,
        "https://download.pytorch.org/whl/cpu"
    );
    assert_eq!(
        pytorch::wheel_index_url_for_cuda_version(
            Some((11, 8)),
            "https://download.pytorch.org/whl".to_string()
        )
        .0,
        "https://download.pytorch.org/whl/cu118"
    );
}

#[test]
fn pytorch_wheel_base_url_follows_runtime_pip_region() {
    let _guard = PYTORCH_WHEEL_ENV_LOCK.lock().unwrap();
    let _restore = EnvRestore::capture("SHINSEKAI_PYTORCH_WHEEL_BASE");
    let _runtime_source = EnvRestore::capture("SHINSEKAI_RUNTIME_SOURCE");
    let _mirror_region = EnvRestore::capture("SHINSEKAI_MIRROR_REGION");
    env::remove_var("SHINSEKAI_PYTORCH_WHEEL_BASE");
    env::remove_var("SHINSEKAI_RUNTIME_SOURCE");
    env::remove_var("SHINSEKAI_MIRROR_REGION");

    assert_eq!(
        pytorch::wheel_base_url(&["https://pypi.tuna.tsinghua.edu.cn/simple/".to_string()]),
        "https://mirrors.aliyun.com/pytorch-wheels"
    );
    assert_eq!(
        pytorch::wheel_base_url(&["https://pypi.org/simple/".to_string()]),
        "https://download.pytorch.org/whl"
    );
}

#[test]
fn pytorch_wheel_base_url_can_be_overridden() {
    let _guard = PYTORCH_WHEEL_ENV_LOCK.lock().unwrap();
    let _restore = EnvRestore::capture("SHINSEKAI_PYTORCH_WHEEL_BASE");
    let _runtime_source = EnvRestore::capture("SHINSEKAI_RUNTIME_SOURCE");
    let _mirror_region = EnvRestore::capture("SHINSEKAI_MIRROR_REGION");
    env::set_var(
        "SHINSEKAI_PYTORCH_WHEEL_BASE",
        "https://example.invalid/pytorch-wheels/",
    );
    env::set_var("SHINSEKAI_RUNTIME_SOURCE", "official");
    env::set_var("SHINSEKAI_MIRROR_REGION", "global");

    assert_eq!(
        pytorch::wheel_base_url(&["https://pypi.org/simple/".to_string()]),
        "https://example.invalid/pytorch-wheels"
    );
}

#[test]
fn pytorch_wheel_base_explicit_region_overrides_generic_pip_index() {
    let _guard = PYTORCH_WHEEL_ENV_LOCK.lock().unwrap();
    let _wheel_base = EnvRestore::capture("SHINSEKAI_PYTORCH_WHEEL_BASE");
    let _runtime_source = EnvRestore::capture("SHINSEKAI_RUNTIME_SOURCE");
    let _mirror_region = EnvRestore::capture("SHINSEKAI_MIRROR_REGION");
    env::remove_var("SHINSEKAI_PYTORCH_WHEEL_BASE");
    env::remove_var("SHINSEKAI_RUNTIME_SOURCE");

    env::set_var("SHINSEKAI_MIRROR_REGION", "china");
    assert_eq!(
        pytorch::wheel_base_url(&["https://pypi.org/simple/".to_string()]),
        "https://mirrors.aliyun.com/pytorch-wheels"
    );

    env::set_var("SHINSEKAI_MIRROR_REGION", "global");
    assert_eq!(
        pytorch::wheel_base_url(&["https://pypi.tuna.tsinghua.edu.cn/simple/".to_string()]),
        "https://download.pytorch.org/whl"
    );
}

#[test]
fn parse_nvidia_smi_cuda_version_reads_driver_report() {
    let output = r#"
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 551.86       Driver Version: 551.86       CUDA Version: 12.4     |
+-----------------------------------------------------------------------------+
"#;

    assert_eq!(
        pytorch::parse_nvidia_smi_cuda_version(output),
        Some((12, 4))
    );
    assert_eq!(pytorch::parse_nvidia_smi_cuda_version("no cuda here"), None);
}

#[test]
fn pytorch_install_plan_skips_matching_exact_cuda_stack() {
    let lines = vec!["torch==99.0.0".to_string()];
    let installed = HashMap::from([
        ("torch".to_string(), "2.7.1+cu128".to_string()),
        ("torchvision".to_string(), "0.22.1+cu128".to_string()),
        ("torchaudio".to_string(), "2.7.1+cu128".to_string()),
    ]);

    let plan = pytorch::build_install_plan(
        &lines,
        &installed,
        "https://download.pytorch.org/whl/cu128".to_string(),
        "test".to_string(),
    );

    assert!(!plan.install_required);
    assert!(!plan.force_reinstall);
    assert_eq!(
        plan.requirement_lines,
        vec![
            "torch==2.7.1".to_string(),
            "torchvision==0.22.1".to_string(),
            "torchaudio==2.7.1".to_string(),
        ]
    );
}

#[test]
fn pytorch_install_plan_forces_reinstall_for_cpu_or_version_mismatch() {
    let lines = vec![
        "torch==2.7.1".to_string(),
        "torchvision==0.22.1".to_string(),
        "torchaudio==2.7.1".to_string(),
    ];
    let installed = HashMap::from([
        ("torch".to_string(), "2.12.1+cpu".to_string()),
        ("torchaudio".to_string(), "2.11.0+cpu".to_string()),
    ]);

    let plan = pytorch::build_install_plan(
        &lines,
        &installed,
        "https://download.pytorch.org/whl/cu128".to_string(),
        "test".to_string(),
    );

    assert!(plan.install_required);
    assert!(plan.force_reinstall);
    assert!(plan.detail.contains("version mismatch"));
    assert!(plan.detail.contains("expected cu128 wheels"));
}

#[test]
fn install_lock_is_persistent_and_reused_after_release() {
    let temp_root = unique_temp_dir("runtime-persistent-lock");
    let runtime_home = temp_root.join("runtime");
    fs::create_dir_all(&runtime_home).unwrap();
    fs::write(
        runtime_home.join("install.lock"),
        "pid=9999999\ncreated_at_ms=10\n",
    )
    .unwrap();

    let lock = acquire_install_lock(&runtime_home).unwrap();
    let lock_text = fs::read_to_string(runtime_home.join("install.lock")).unwrap();
    assert!(lock_text.contains(&format!("pid={}", std::process::id())));
    drop(lock);
    assert!(runtime_home.join("install.lock").is_file());

    let next_lock = acquire_install_lock(&runtime_home).unwrap();
    drop(next_lock);
    assert!(runtime_home.join("install.lock").is_file());

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn concurrent_install_lock_is_rejected_without_replacing_the_owner_file() {
    let temp_root = unique_temp_dir("runtime-concurrent-lock");
    let runtime_home = temp_root.join("runtime");
    fs::create_dir_all(&runtime_home).unwrap();

    let owner = acquire_install_lock(&runtime_home).unwrap();
    let owner_text = fs::read_to_string(runtime_home.join("install.lock")).unwrap();
    let error = match acquire_install_lock(&runtime_home) {
        Ok(_) => panic!("concurrent runtime install lock was accepted"),
        Err(error) => error,
    };

    assert!(error
        .to_string()
        .contains("another Shinsekai runtime install"));
    assert_eq!(
        fs::read_to_string(runtime_home.join("install.lock")).unwrap(),
        owner_text
    );
    drop(owner);

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn install_lock_detects_a_replacement_runtime_directory() {
    let temp_root = unique_temp_dir("runtime-replaced-lock-parent");
    let runtime_home = temp_root.join("runtime");
    let preserved_runtime = temp_root.join("preserved-runtime");
    fs::create_dir_all(&runtime_home).unwrap();

    let owner = acquire_install_lock(&runtime_home).unwrap();
    fs::rename(&runtime_home, &preserved_runtime).unwrap();
    fs::create_dir_all(&runtime_home).unwrap();
    fs::write(runtime_home.join("install.lock"), "peer\n").unwrap();

    let error = owner.require_current_identity().unwrap_err();

    assert!(error.to_string().contains("changed identity"));
    assert_eq!(
        fs::read_to_string(runtime_home.join("install.lock")).unwrap(),
        "peer\n"
    );
    assert!(preserved_runtime.join("install.lock").is_file());
    drop(owner);
    let _ = fs::remove_dir_all(temp_root);
}

#[cfg(unix)]
#[test]
fn install_lock_rejects_a_link_without_touching_its_target() {
    use std::os::unix::fs::symlink;

    let temp_root = unique_temp_dir("runtime-linked-lock");
    let runtime_home = temp_root.join("runtime");
    let external = temp_root.join("external.lock");
    fs::create_dir_all(&runtime_home).unwrap();
    fs::write(&external, "pid=9999999\n").unwrap();
    symlink(&external, runtime_home.join("install.lock")).unwrap();

    let error = match acquire_install_lock(&runtime_home) {
        Ok(_) => panic!("linked install lock was accepted"),
        Err(error) => error,
    };

    assert!(error.to_string().contains("regular non-link"));
    assert_eq!(fs::read_to_string(&external).unwrap(), "pid=9999999\n");
    assert!(runtime_home.join("install.lock").symlink_metadata().is_ok());
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

#[cfg(unix)]
#[test]
fn verify_python_runtime_rejects_source_root_replaced_during_bridge_check() {
    let temp_root = unique_temp_dir("runtime-replaced-source-root");
    let source_root = temp_root.join("source");
    let preserved_source = temp_root.join("preserved-source");
    let fake_python = temp_root.join("python");
    fs::create_dir_all(&source_root).unwrap();
    fs::write(source_root.join("frontend_bridge.py"), "bridge\n").unwrap();
    fs::write(
        source_root.join("requirements-runtime-core.txt"),
        "pydantic\n",
    )
    .unwrap();
    write_executable(
        &fake_python,
        &format!(
            r#"#!/bin/sh
mv "{source}" "{preserved}"
mkdir "{source}"
printf 'peer bridge\n' > "{source}/frontend_bridge.py"
printf 'peer requirements\n' > "{source}/requirements-runtime-core.txt"
exit 0
"#,
            source = source_root.display(),
            preserved = preserved_source.display(),
        ),
    );
    let requirements = RuntimeRequirements {
        imports: Vec::new(),
        python: None,
        requirements_file: "requirements-runtime-core.txt".to_string(),
        bridge_check: true,
    };

    let error = verify_python_runtime(&source_root, &fake_python, "desktop-core", &requirements)
        .unwrap_err();

    assert!(error.to_string().contains("source root changed identity"));
    assert_eq!(
        fs::read_to_string(source_root.join("frontend_bridge.py")).unwrap(),
        "peer bridge\n"
    );
    assert_eq!(
        fs::read_to_string(preserved_source.join("frontend_bridge.py")).unwrap(),
        "bridge\n"
    );
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
    std::env::temp_dir()
        .canonicalize()
        .unwrap_or_else(|_| std::env::temp_dir())
        .join(format!("shinsekai-{name}-{nonce}"))
}

#[cfg(unix)]
fn write_executable(path: &Path, text: &str) {
    fs::write(path, text).unwrap();
    let mut permissions = fs::metadata(path).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(path, permissions).unwrap();
}
