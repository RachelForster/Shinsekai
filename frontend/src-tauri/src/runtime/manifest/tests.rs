use super::*;

#[test]
fn pip_index_urls_honor_explicit_source_preference() {
    let manifest = RuntimeManifest {
        version: "2.0.0".to_string(),
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
        pip_index_urls_for_source_values(&manifest, Some("official"), false, None, None, None),
        vec!["https://official.example/simple/".to_string()]
    );
    assert_eq!(
        pip_index_urls_for_source_values(&manifest, Some("china"), false, None, None, None),
        vec![
            "https://china.example/simple/".to_string(),
            "https://china-backup.example/simple/".to_string(),
        ]
    );
}

#[test]
fn pip_index_urls_respect_user_pip_configuration() {
    let manifest = RuntimeManifest {
        version: "2.0.0".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles: HashMap::new(),
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig::default(),
    };

    assert_eq!(
        pip_index_urls_for_source_values(&manifest, Some("china"), true, None, None, None),
        Vec::<String>::new()
    );
}

#[test]
fn pip_index_urls_allow_shinsekai_override() {
    let manifest = RuntimeManifest {
        version: "2.0.0".to_string(),
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
        ),
        vec![
            "https://mirror.example/simple/".to_string(),
            "https://mirror-b.example/simple/".to_string(),
        ]
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
        version: "2.0.0".to_string(),
        schema: Some(2),
        required_modules: Vec::new(),
        profiles,
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig::default(),
    };

    let requirements = runtime_requirements(Path::new("."), Some(&manifest), DEFAULT_PROFILE);

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
        version: "2.0.0".to_string(),
        schema: Some(2),
        required_modules: vec!["yaml".to_string(), "requests".to_string()],
        profiles,
        probes: ProbeConfig::default(),
        pip_indexes: PipIndexConfig::default(),
    };

    let requirements = runtime_requirements(Path::new("."), Some(&manifest), "compat");

    assert_eq!(requirements.python.as_deref(), Some(">=3.11,<3.13"));
    assert!(!requirements.bridge_check);
    assert_eq!(requirements.imports, vec!["yaml", "requests"]);
    assert_eq!(requirements.requirements_file, DEFAULT_REQUIREMENTS_FILE);
}
