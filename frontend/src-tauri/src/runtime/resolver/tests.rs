use super::*;
use std::{fs, path::PathBuf, time::SystemTime};

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

fn python_install(kind: PythonKind) -> PythonInstall {
    PythonInstall {
        id: "python-test".to_string(),
        executable: PathBuf::from("/tmp/python"),
        label: "Python test".to_string(),
        kind,
        version: Some("3.11.9".to_string()),
        major: Some(3),
        minor: Some(11),
        arch: Some(current_arch().to_string()),
        platform: None,
        prefix: None,
        base_prefix: None,
        is_venv: false,
        is_conda: false,
        conda_env: None,
        has_pip: true,
        has_venv: true,
        has_ensurepip: true,
        externally_managed: false,
        probe_error: None,
        priority: 0,
    }
}

#[test]
fn python_version_satisfies_profile_range() {
    assert!(python_version_satisfies((3, 10, 0), ">=3.10,<3.14"));
    assert!(python_version_satisfies((3, 13, 7), ">=3.10,<3.14"));
    assert!(!python_version_satisfies((3, 9, 18), ">=3.10,<3.14"));
    assert!(!python_version_satisfies((3, 14, 0), ">=3.10,<3.14"));
}

#[test]
fn python_version_parser_accepts_patch_suffixes() {
    assert_eq!(parse_python_version("3.11.9+20240107"), Some((3, 11, 9)));
    assert_eq!(parse_python_version("3.12"), Some((3, 12, 0)));
}

#[test]
fn python_version_satisfies_default_minimum() {
    assert!(python_version_satisfies((3, 10, 0), ">=3.10"));
    assert!(!python_version_satisfies((3, 9, 19), ">=3.10"));
}

#[test]
fn missing_core_deps_repair_actions_match_runtime_ownership() {
    let managed = python_install(PythonKind::Managed);
    assert_eq!(
        missing_core_deps_actions(&managed),
        vec![
            RuntimeRepairActionKind::CreateManagedVenv,
            RuntimeRepairActionKind::InstallRuntimeDeps,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );

    let managed_venv = python_install(PythonKind::ManagedVenv);
    assert_eq!(
        missing_core_deps_actions(&managed_venv),
        vec![
            RuntimeRepairActionKind::CreateManagedVenv,
            RuntimeRepairActionKind::InstallRuntimeDeps,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );

    let conda = python_install(PythonKind::Conda);
    assert_eq!(
        missing_core_deps_actions(&conda),
        vec![
            RuntimeRepairActionKind::CreateManagedVenv,
            RuntimeRepairActionKind::InstallRuntimeDeps,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );

    let system = python_install(PythonKind::Path);
    assert_eq!(
        missing_core_deps_actions(&system),
        vec![
            RuntimeRepairActionKind::CreateManagedVenv,
            RuntimeRepairActionKind::InstallRuntimeDeps,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );
}

#[test]
fn explicit_conda_python_offers_isolated_venv_before_in_place_install() {
    let mut install = python_install(PythonKind::Explicit);
    install.is_conda = true;

    assert_eq!(
        missing_core_deps_actions(&install),
        vec![
            RuntimeRepairActionKind::CreateManagedVenv,
            RuntimeRepairActionKind::InstallRuntimeDeps,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );
}

#[test]
fn system_python_without_ensurepip_does_not_offer_managed_venv() {
    let mut install = python_install(PythonKind::Path);
    install.has_venv = true;
    install.has_ensurepip = false;

    assert_eq!(
        missing_core_deps_actions(&install),
        vec![
            RuntimeRepairActionKind::InstallRuntimeDeps,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );
}

#[test]
fn externally_managed_python_does_not_offer_in_place_dependency_install() {
    let mut install = python_install(PythonKind::Path);
    install.externally_managed = true;

    assert_eq!(
        missing_core_deps_actions(&install),
        vec![
            RuntimeRepairActionKind::CreateManagedVenv,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );
}

#[test]
fn conda_without_ensurepip_can_still_offer_in_place_dependency_install() {
    let mut install = python_install(PythonKind::Conda);
    install.has_venv = true;
    install.has_ensurepip = false;
    install.has_pip = true;

    assert_eq!(
        missing_core_deps_actions(&install),
        vec![
            RuntimeRepairActionKind::InstallRuntimeDeps,
            RuntimeRepairActionKind::SelectDifferentRuntime
        ]
    );
}

#[test]
fn rosetta_warning_is_diagnostic_only_for_intel_python_under_translated_macos_process() {
    let warning = macos_rosetta_warning_for("x64", Some("x86_64"), true)
        .expect("translated x64 app with Intel Python should warn");

    assert!(warning.contains("Rosetta"));
    assert!(warning.contains("native arm64"));
}

#[test]
fn rosetta_warning_is_skipped_for_native_or_arch_mismatched_contexts() {
    assert!(macos_rosetta_warning_for("x64", Some("x86_64"), false).is_none());
    assert!(macos_rosetta_warning_for("arm64", Some("arm64"), false).is_none());
    assert!(macos_rosetta_warning_for("x64", Some("arm64"), true).is_none());
    assert!(macos_rosetta_warning_for("x64", None, true).is_none());
}

#[test]
fn recommended_action_prefers_isolated_venv_over_in_place_dependency_install() {
    let candidates = vec![
        runtime_candidate_with_actions("conda", vec![RuntimeRepairActionKind::InstallRuntimeDeps]),
        runtime_candidate_with_actions("path", vec![RuntimeRepairActionKind::CreateManagedVenv]),
    ];

    assert_eq!(
        recommended_action(&candidates, None),
        Some(RuntimeRepairActionKind::CreateManagedVenv)
    );
}

#[cfg(unix)]
#[test]
fn bridge_check_uses_requested_profile() {
    let temp_root = unique_temp_dir("runtime-bridge-profile");
    fs::create_dir_all(&temp_root).unwrap();
    fs::write(temp_root.join("frontend_bridge.py"), "").unwrap();
    fs::write(temp_root.join("requirements-runtime-core.txt"), "").unwrap();
    let arg_log = temp_root.join("args.txt");
    let fake_python = temp_root.join("python");
    fs::write(
            &fake_python,
            format!(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\nprintf '{{\"missingDistributions\":[],\"message\":\"ok\"}}\\n'\n",
                arg_log.display()
            ),
        )
        .unwrap();
    let mut permissions = fs::metadata(&fake_python).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&fake_python, permissions).unwrap();

    let report = check_bridge_runtime(
        &fake_python,
        &temp_root,
        "full",
        "requirements-runtime-core.txt",
    );

    assert!(report.ok, "{report:?}");
    let args = fs::read_to_string(&arg_log).unwrap();
    let lines = args.lines().collect::<Vec<_>>();
    let profile_index = lines
        .iter()
        .position(|line| *line == "--profile")
        .expect("profile flag should be passed");
    assert_eq!(lines.get(profile_index + 1), Some(&"full"));

    let _ = fs::remove_dir_all(temp_root);
}

fn unique_temp_dir(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
}

fn runtime_candidate_with_actions(
    id: &str,
    repair_actions: Vec<RuntimeRepairActionKind>,
) -> RuntimeCandidateView {
    RuntimeCandidateView {
        id: id.to_string(),
        python_id: Some(id.to_string()),
        label: id.to_string(),
        path: format!("/tmp/{id}"),
        kind: RuntimeKind::Path,
        version: Some("3.11.9".to_string()),
        status: RuntimeCandidateStatus::MissingCoreDeps,
        message: None,
        score: 0,
        selected: false,
        managed: false,
        missing_packages: Vec::new(),
        missing_imports: Vec::new(),
        python_version: None,
        warnings: Vec::new(),
        repair_actions,
    }
}
