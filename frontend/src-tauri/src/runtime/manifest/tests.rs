use super::*;

#[test]
fn pip_index_urls_honor_explicit_source_preference() {
    let manifest = RuntimeManifest {
        version: "2.0.1".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles: HashMap::new(),
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig {
            official: Some("https://official.example/simple/".to_string()),
            official_urls: Vec::new(),
            china: Some("https://china.example/simple/".to_string()),
            china_urls: vec!["https://china-backup.example/simple/".to_string()],
        },
    };

    assert_eq!(
        pip_index_urls_for_source_values(
            &manifest,
            Some("official"),
            false,
            None,
            None,
            None,
            None
        ),
        vec!["https://official.example/simple/".to_string()]
    );
    assert_eq!(
        pip_index_urls_for_source_values(&manifest, Some("china"), false, None, None, None, None),
        vec![
            "https://china.example/simple/".to_string(),
            "https://china-backup.example/simple/".to_string(),
        ]
    );
}

#[test]
fn pip_index_urls_respect_user_pip_configuration() {
    let manifest = RuntimeManifest {
        version: "2.0.1".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles: HashMap::new(),
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig::default(),
    };

    assert_eq!(
        pip_index_urls_for_source_values(&manifest, Some("china"), true, None, None, None, None),
        Vec::<String>::new()
    );
}

#[test]
fn pip_index_urls_allow_shinsekai_override() {
    let manifest = RuntimeManifest {
        version: "2.0.1".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles: HashMap::new(),
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig::default(),
    };

    assert_eq!(
        pip_index_urls_for_source_values(
            &manifest,
            Some("china"),
            false,
            Some(" https://mirror.example/simple/ "),
            Some("https://mirror-b.example/simple/, https://mirror.example/simple/"),
            None,
            None,
        ),
        vec![
            "https://mirror.example/simple/".to_string(),
            "https://mirror-b.example/simple/".to_string(),
        ]
    );
}

#[test]
fn pip_index_urls_follow_python_mirror_region() {
    let manifest = RuntimeManifest {
        version: "2.0.1".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles: HashMap::new(),
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig {
            official: Some("https://official.example/simple/".to_string()),
            official_urls: Vec::new(),
            china: Some("https://china.example/simple/".to_string()),
            china_urls: vec!["https://china-backup.example/simple/".to_string()],
        },
    };

    assert_eq!(
        pip_index_urls_for_source_values(&manifest, None, false, None, None, None, Some("global")),
        vec!["https://official.example/simple/".to_string()]
    );
    assert_eq!(
        pip_index_urls_for_source_values(&manifest, None, false, None, None, None, Some("china")),
        vec![
            "https://china.example/simple/".to_string(),
            "https://china-backup.example/simple/".to_string(),
            "https://official.example/simple/".to_string(),
        ]
    );
}

#[test]
fn pip_index_urls_runtime_source_overrides_python_mirror_region() {
    let manifest = RuntimeManifest {
        version: "2.0.1".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles: HashMap::new(),
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig {
            official: Some("https://official.example/simple/".to_string()),
            official_urls: Vec::new(),
            china: Some("https://china.example/simple/".to_string()),
            china_urls: Vec::new(),
        },
    };

    assert_eq!(
        pip_index_urls_for_source_values(
            &manifest,
            None,
            false,
            None,
            None,
            Some("china"),
            Some("global")
        ),
        vec!["https://china.example/simple/".to_string()]
    );
    assert_eq!(
        pip_index_urls_for_source_values(
            &manifest,
            None,
            false,
            None,
            None,
            Some("official"),
            Some("china")
        ),
        vec!["https://official.example/simple/".to_string()]
    );
}

#[test]
fn runtime_requirements_include_profile_python_range() {
    let mut profiles = HashMap::new();
    profiles.insert(
        DEFAULT_PROFILE.to_string(),
        RuntimeProfile {
            python: Some(">=3.10,<3.14".to_string()),
            imports: vec!["yaml".to_string()],
            requirements: Some("requirements-runtime-core.txt".to_string()),
            bridge_check: Some(true),
            extends: None,
        },
    );
    let manifest = RuntimeManifest {
        version: "2.0.1".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles,
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig::default(),
    };

    let requirements =
        runtime_requirements(Path::new("."), Some(&manifest), DEFAULT_PROFILE).unwrap();

    assert_eq!(requirements.python.as_deref(), Some(">=3.10,<3.14"));
}

#[test]
fn runtime_requirements_preserve_profile_metadata_when_imports_use_manifest_fallback() {
    let mut profiles = HashMap::new();
    profiles.insert(
        "compat".to_string(),
        RuntimeProfile {
            python: Some(">=3.11,<3.13".to_string()),
            bridge_check: Some(false),
            ..RuntimeProfile::default()
        },
    );
    let manifest = RuntimeManifest {
        version: "2.0.1".to_string(),
        schema: Some(2),
        required_modules: vec!["yaml".to_string(), "requests".to_string()],
        profiles,
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig::default(),
    };

    let requirements = runtime_requirements(Path::new("."), Some(&manifest), "compat").unwrap();

    assert_eq!(requirements.python.as_deref(), Some(">=3.11,<3.13"));
    assert!(!requirements.bridge_check);
    assert_eq!(requirements.imports, vec!["yaml", "requests"]);
    assert_eq!(requirements.requirements_file, DEFAULT_REQUIREMENTS_FILE);
}

#[test]
fn runtime_requirements_file_rejects_traversal_whitespace_and_manifest_absolute_paths() {
    let external = std::env::temp_dir().join("external-requirements.txt");
    let external_text = external.to_str().unwrap();
    let external_alias = external
        .parent()
        .unwrap()
        .join(".")
        .join(external.file_name().unwrap());
    let external_alias_text = external_alias.to_str().unwrap();
    assert_eq!(validated_requirements_file("../outside.txt", false), None);
    assert_eq!(
        validated_requirements_file("./requirements.txt", false),
        None
    );
    assert_eq!(
        validated_requirements_file("requirements//core.txt", false),
        None
    );
    assert_eq!(
        validated_requirements_file("requirements/./core.txt", false),
        None
    );
    assert_eq!(
        validated_requirements_file(" requirements.txt", false),
        None
    );
    for value in [
        "~/requirements.txt",
        "requirements/CON.txt",
        "requirements/ leading.txt",
        "requirements/trailing.",
        "requirements/alternate:stream.txt",
    ] {
        assert_eq!(validated_requirements_file(value, false), None, "{value}");
    }
    assert_eq!(validated_requirements_file(external_text, false), None);
    assert_eq!(validated_requirements_file(external_alias_text, true), None);
    assert_eq!(
        validated_requirements_file("requirements/runtime.txt", false),
        Some("requirements/runtime.txt".to_string())
    );
    assert_eq!(
        validated_requirements_file(external_text, true),
        Some(external_text.to_string())
    );
}

#[test]
fn runtime_requirements_path_values_fail_closed_instead_of_falling_back() {
    let source_root = Path::new("/tmp/shinsekai-source");

    let empty_environment =
        runtime_requirements_file_value(source_root, Some(""), Some(DEFAULT_REQUIREMENTS_FILE))
            .unwrap_err()
            .to_string();
    assert!(empty_environment.contains("SHINSEKAI_RUNTIME_REQUIREMENTS_FILE"));

    let relative_alias = runtime_requirements_file_value(
        source_root,
        Some("./requirements.txt"),
        Some(DEFAULT_REQUIREMENTS_FILE),
    )
    .unwrap_err()
    .to_string();
    assert!(relative_alias.contains("SHINSEKAI_RUNTIME_REQUIREMENTS_FILE"));

    let invalid_manifest =
        runtime_requirements_file_value(source_root, None, Some("../requirements.txt"))
            .unwrap_err()
            .to_string();
    assert!(invalid_manifest.contains("runtime manifest requirements path is invalid"));
}

#[test]
fn runtime_manifest_environment_path_must_be_absolute() {
    let error = explicit_env_path_value(
        "SHINSEKAI_RUNTIME_MANIFEST",
        Some(std::ffi::OsString::from("runtime_manifest.json")),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("SHINSEKAI_RUNTIME_MANIFEST must be an absolute path"));
}

#[test]
fn runtime_manifest_environment_path_rejects_user_home_alias() {
    let error = explicit_env_path_value(
        "SHINSEKAI_RUNTIME_MANIFEST",
        Some(std::ffi::OsString::from("~/runtime_manifest.json")),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("SHINSEKAI_RUNTIME_MANIFEST must be an absolute path"));
}

#[test]
fn runtime_manifest_environment_path_rejects_present_empty_value() {
    let error = explicit_env_path_value(
        "SHINSEKAI_RUNTIME_MANIFEST",
        Some(std::ffi::OsString::new()),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("SHINSEKAI_RUNTIME_MANIFEST must not be empty"));
}

#[test]
fn runtime_manifest_environment_path_rejects_nonportable_text() {
    let error = explicit_env_path_value(
        "SHINSEKAI_RUNTIME_MANIFEST",
        Some(std::ffi::OsString::from("/tmp/bad\nmanifest.json")),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("non-portable path characters"));
}

#[test]
fn runtime_manifest_environment_path_rejects_lexical_aliases() {
    let error = explicit_env_path_value(
        "SHINSEKAI_RUNTIME_MANIFEST",
        Some(std::ffi::OsString::from("/tmp/./runtime_manifest.json")),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("non-portable path characters"));
}

#[cfg(unix)]
#[test]
fn runtime_manifest_environment_path_rejects_a_linked_leaf() {
    let root = std::env::temp_dir().join(format!(
        "shinsekai-manifest-canonical-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let target = root.join("target:manifest.json");
    std::fs::write(&target, "{}").unwrap();
    let alias = root.join("manifest.json");
    std::os::unix::fs::symlink(&target, &alias).unwrap();

    let error = explicit_env_path_value("SHINSEKAI_RUNTIME_MANIFEST", Some(alias.into_os_string()))
        .unwrap_err()
        .to_string();

    assert!(error.contains("symbolic link"));
    let _ = std::fs::remove_dir_all(root);
}

#[cfg(unix)]
#[test]
fn runtime_manifest_environment_path_rejects_a_linked_parent() {
    let root = std::env::temp_dir().join(format!(
        "shinsekai-manifest-linked-parent-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let real_parent = root.join("real-parent");
    let linked_parent = root.join("linked-parent");
    std::fs::create_dir_all(&real_parent).unwrap();
    std::fs::write(real_parent.join("runtime_manifest.json"), "{}").unwrap();
    std::os::unix::fs::symlink(&real_parent, &linked_parent).unwrap();

    let error = explicit_env_path_value(
        "SHINSEKAI_RUNTIME_MANIFEST",
        Some(linked_parent.join("runtime_manifest.json").into_os_string()),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("symbolic link"));
    let _ = std::fs::remove_dir_all(root);
}

#[cfg(unix)]
#[test]
fn runtime_manifest_environment_path_rejects_non_utf8_text() {
    use std::os::unix::ffi::OsStringExt;

    let value = std::ffi::OsString::from_vec(vec![b'/', b't', b'm', b'p', b'/', 0xff]);
    let error = explicit_env_path_value("SHINSEKAI_RUNTIME_MANIFEST", Some(value))
        .unwrap_err()
        .to_string();

    assert!(error.contains("non-portable path characters"));
}
