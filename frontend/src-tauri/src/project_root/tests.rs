use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Barrier,
    },
    thread,
    time::{SystemTime, UNIX_EPOCH},
};

use super::locator::*;
use super::platform::*;
use super::probe::*;
use super::restart_log::*;
use super::*;

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

fn temp_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let counter = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "shinsekai-project-root-{label}-{}-{nonce}-{counter}",
        std::process::id()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

fn data_root(parent: &Path, name: &str) -> PathBuf {
    let root = parent.join(name);
    let config = root.join("data").join("config");
    fs::create_dir_all(&config).unwrap();
    fs::write(config.join("system_config.yaml"), format!("name: {name}")).unwrap();
    root
}

fn options(root: &Path) -> ProjectRootResolveOptions {
    let app_root = root.join("current-app");
    fs::create_dir_all(&app_root).unwrap();
    ProjectRootResolveOptions {
        explicit_root: None,
        source_root: app_root.clone(),
        app_root,
        current_app_data_project_root: root.join("current-data").join("project"),
        legacy_app_data_project_roots: Vec::new(),
        locator_path: root.join("config").join(PROJECT_ROOT_LOCATOR_FILE),
        locator_read_paths: Vec::new(),
        restart_log_paths: Vec::new(),
        untrusted_candidate_roots: Vec::new(),
        development_source: false,
    }
}

#[test]
fn shinsekai_environment_override_precedes_legacy_easyai_override() {
    let selected = preferred_environment_root(
        Some(OsString::from("new-root")),
        Some(OsString::from("legacy-root")),
    )
    .unwrap();
    assert_eq!(selected.0, PathBuf::from("new-root"));

    let legacy = preferred_environment_root(None, Some(OsString::from("legacy-root"))).unwrap();
    assert_eq!(legacy.0, PathBuf::from("legacy-root"));
}

#[test]
fn explicit_override_is_used_without_persisting_a_locator() {
    let root = temp_dir("explicit");
    let explicit = root.join("explicit-root");
    let mut options = options(&root);
    options.explicit_root = Some((
        explicit.clone(),
        ProjectRootCandidateSource::EnvironmentOverride,
    ));
    let locator = options.locator_path.clone();

    let resolved = resolve(options).unwrap();

    assert_eq!(resolved.path, explicit.canonicalize().unwrap());
    assert!(!locator.exists());
    assert_eq!(
        resolved.controller.status().candidates[0].source,
        ProjectRootCandidateSource::EnvironmentOverride
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn relative_explicit_override_is_rejected() {
    let root = temp_dir("relative-explicit");
    let mut options = options(&root);
    options.explicit_root = Some((
        PathBuf::from("relative-project-root"),
        ProjectRootCandidateSource::EnvironmentOverride,
    ));

    let error = resolve(options).err().unwrap();

    assert!(error.contains("must be absolute"));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn valid_persisted_locator_has_precedence_over_discovered_data() {
    let root = temp_dir("persisted-precedence");
    let selected = data_root(&root, "selected");
    let other = data_root(&root, "other");
    let mut options = options(&root);
    options.legacy_app_data_project_roots.push(other);
    persist_locator_automatically(&options.locator_path, &selected).unwrap();

    let resolved = resolve(options).unwrap();

    assert_eq!(resolved.path, selected.canonicalize().unwrap());
    assert!(!resolved.controller.status().requires_selection);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn legacy_locator_is_migrated_before_its_root_is_used() {
    let root = temp_dir("legacy-locator-migration");
    let selected = data_root(&root, "legacy-selected");
    let mut options = options(&root);
    let legacy_locator = root.join("legacy-config").join(PROJECT_ROOT_LOCATOR_FILE);
    persist_locator_automatically(&legacy_locator, &selected).unwrap();
    options.locator_read_paths.push(legacy_locator);
    let primary_locator = options.locator_path.clone();

    let resolved = resolve(options).unwrap();

    assert_eq!(resolved.path, selected.canonicalize().unwrap());
    assert_eq!(
        read_valid_locator(&primary_locator).unwrap(),
        selected.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn legacy_locator_migration_adopts_a_different_primary_locator_that_won_the_race() {
    let root = temp_dir("legacy-locator-race");
    let legacy = data_root(&root, "legacy-selected");
    let concurrent = data_root(&root, "concurrent-selected");
    let primary_locator = root.join("config").join(PROJECT_ROOT_LOCATOR_FILE);
    persist_locator_automatically(&primary_locator, &concurrent).unwrap();

    let selected = migrate_legacy_locator(&primary_locator, &legacy).unwrap();

    assert_eq!(selected, concurrent.canonicalize().unwrap());
    assert_eq!(
        read_valid_locator(&primary_locator).unwrap(),
        concurrent.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn legacy_locator_migration_fails_closed_when_primary_cannot_be_published() {
    let root = temp_dir("legacy-locator-fail-closed");
    let legacy = data_root(&root, "legacy-selected");
    let primary_locator = root.join("config").join(PROJECT_ROOT_LOCATOR_FILE);
    fs::create_dir_all(primary_locator.parent().unwrap()).unwrap();
    fs::write(&primary_locator, b"{ malformed").unwrap();

    let error = migrate_legacy_locator(&primary_locator, &legacy).unwrap_err();

    assert!(error.contains("refusing to run with an ambiguous project root"));
    assert!(matches!(
        read_locator_state(&primary_locator),
        LocatorState::Malformed
    ));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn malformed_locator_is_preserved_until_explicit_selection() {
    let root = temp_dir("malformed-locator");
    let selected = data_root(&root, "legacy-data");
    let mut options = options(&root);
    options.legacy_app_data_project_roots.push(selected.clone());
    fs::create_dir_all(options.locator_path.parent().unwrap()).unwrap();
    fs::write(&options.locator_path, b"{ definitely not json").unwrap();
    let locator_path = options.locator_path.clone();
    let original = fs::read(&locator_path).unwrap();

    let resolved = resolve(options).unwrap();

    assert!(resolved.controller.status().requires_selection);
    assert_eq!(fs::read(&locator_path).unwrap(), original);
    resolved
        .controller
        .select(&display_path(&selected))
        .unwrap();
    assert_eq!(
        read_valid_locator(&locator_path).unwrap(),
        selected.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn oversized_locator_is_treated_as_malformed_without_overwriting_it() {
    let root = temp_dir("oversized-locator");
    let selected = data_root(&root, "legacy-data");
    let mut options = options(&root);
    options.legacy_app_data_project_roots.push(selected);
    fs::create_dir_all(options.locator_path.parent().unwrap()).unwrap();
    fs::write(
        &options.locator_path,
        vec![b' '; (MAX_PROJECT_ROOT_LOCATOR_BYTES + 1) as usize],
    )
    .unwrap();
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();

    assert!(resolved.controller.status().requires_selection);
    assert_eq!(
        fs::metadata(locator_path).unwrap().len(),
        MAX_PROJECT_ROOT_LOCATOR_BYTES + 1
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn unsupported_locator_schema_is_preserved_and_cannot_be_replaced() {
    let root = temp_dir("future-locator");
    data_root(&root, "current-app");
    let future = root.join("future-project");
    let options = options(&root);
    fs::create_dir_all(options.locator_path.parent().unwrap()).unwrap();
    fs::write(
        &options.locator_path,
        format!(
            "{{\"version\":2,\"projectRoot\":{:?}}}",
            display_path(&future)
        ),
    )
    .unwrap();
    let locator_path = options.locator_path.clone();
    let original = fs::read(&locator_path).unwrap();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(status
        .candidates
        .iter()
        .all(|candidate| !candidate.selectable));
    assert!(resolved
        .controller
        .select(&display_path(&resolved.path))
        .is_err());
    assert_eq!(fs::read(locator_path).unwrap(), original);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn development_source_ignores_and_does_not_modify_production_locator() {
    let root = temp_dir("dev-isolation");
    let dev = data_root(&root, "current-app");
    let production = data_root(&root, "production-project");
    let mut options = options(&root);
    options.development_source = true;
    persist_locator_automatically(&options.locator_path, &production).unwrap();
    let locator_path = options.locator_path.clone();
    let original = fs::read(&locator_path).unwrap();

    let resolved = resolve(options).unwrap();

    assert_eq!(resolved.path, dev.canonicalize().unwrap());
    assert_eq!(
        resolved.controller.status().candidates[0].source,
        ProjectRootCandidateSource::DevelopmentSource
    );
    assert_eq!(fs::read(locator_path).unwrap(), original);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn development_source_does_not_create_production_locator() {
    let root = temp_dir("dev-no-locator");
    data_root(&root, "current-app");
    let mut options = options(&root);
    options.development_source = true;
    let locator_path = options.locator_path.clone();

    resolve(options).unwrap();

    assert!(!locator_path.exists());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn unavailable_locator_is_preserved_until_explicit_selection() {
    let root = temp_dir("offline-locator");
    let current = data_root(&root, "current-app");
    let offline = root.join("detached-drive").join("Shinsekai");
    let options = options(&root);
    fs::create_dir_all(options.locator_path.parent().unwrap()).unwrap();
    let locator = ProjectRootLocator {
        version: PROJECT_ROOT_LOCATOR_VERSION,
        project_root: display_path(&offline),
    };
    fs::write(
        &options.locator_path,
        serde_json::to_vec_pretty(&locator).unwrap(),
    )
    .unwrap();
    let locator_path = options.locator_path.clone();
    let original = fs::read(&locator_path).unwrap();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(resolved.path, current.canonicalize().unwrap());
    assert!(status.requires_selection);
    assert_eq!(fs::read(&locator_path).unwrap(), original);
    let offline_candidate = status
        .candidates
        .iter()
        .find(|candidate| candidate.source == ProjectRootCandidateSource::PersistedLocator)
        .unwrap();
    assert!(!offline_candidate.selectable);
    assert!(resolved.controller.select(&display_path(&offline)).is_err());

    let selected = resolved.controller.select(&display_path(&current)).unwrap();
    assert!(!selected.requires_selection);
    assert_eq!(
        read_valid_locator(&locator_path).unwrap(),
        current.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn locator_with_missing_data_directory_is_unavailable_not_a_fresh_root() {
    let root = temp_dir("locator-missing-data");
    let current = data_root(&root, "current-app");
    let incomplete = root.join("incomplete-project");
    fs::create_dir_all(&incomplete).unwrap();
    let options = options(&root);
    fs::create_dir_all(options.locator_path.parent().unwrap()).unwrap();
    let locator = ProjectRootLocator {
        version: PROJECT_ROOT_LOCATOR_VERSION,
        project_root: display_path(&incomplete),
    };
    fs::write(
        &options.locator_path,
        serde_json::to_vec_pretty(&locator).unwrap(),
    )
    .unwrap();
    let locator_path = options.locator_path.clone();
    let original = fs::read(&locator_path).unwrap();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(resolved.path, current.canonicalize().unwrap());
    assert!(status.requires_selection);
    assert_eq!(fs::read(&locator_path).unwrap(), original);
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&incomplete)
            && candidate.source == ProjectRootCandidateSource::PersistedLocator
            && !candidate.selectable
    }));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn persisting_a_new_root_prepares_its_data_directory() {
    let root = temp_dir("persist-prepares-data");
    let selected = root.join("new-project");
    fs::create_dir_all(&selected).unwrap();
    let locator = root.join("config").join(PROJECT_ROOT_LOCATOR_FILE);

    persist_selected_locator(&locator, &selected).unwrap();

    assert!(selected.join("data").is_dir());
    assert_eq!(
        read_valid_locator(&locator).unwrap(),
        selected.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn restart_log_parser_preserves_spaces_and_unicode() {
    let root = temp_dir("restart-log-unicode");
    let project = data_root(&root, "D 盘 用户数据");
    let app = data_root(&root, "旧 安装目录");
    let log = root.join("shinsekai-restart-debug.log");
    fs::write(
        &log,
        format!(
            "ts=1 pid=1 component=desktop setup resolved source_root=/source project_root={} app_root={} frontend_dist=/frontend dist bridge_port=8787 url=x\n",
            project.display(),
            app.display()
        ),
    )
    .unwrap();

    let candidates = restart_log_candidates(&log);

    assert_eq!(candidates[0].0, project);
    assert_eq!(
        candidates[0].1,
        ProjectRootCandidateSource::RestartLogProjectRoot
    );
    assert_eq!(candidates[1].0, app);
    assert_eq!(
        candidates[1].1,
        ProjectRootCandidateSource::RestartLogAppRoot
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn restart_log_parser_ignores_unresolved_setup_entries() {
    let root = temp_dir("restart-log-pending");
    let recovered = data_root(&root, "old D drive");
    let log = root.join("shinsekai-restart-debug.log");
    let mut contents = format!(
        "ts=1 component=desktop setup resolved source_root=/source project_root={} app_root={} frontend_dist=/dist bridge_port=8787\n",
        recovered.display(),
        recovered.display()
    );
    for index in 0..(MAX_RESTART_LOG_CANDIDATES + 8) {
        contents.push_str(&format!(
            "ts={} component=desktop setup awaiting project-root selection source_root=/source project_root=/new-c-root component=desktop setup resolved source_root=/fake project_root=/fake app_root=/new-c-root frontend_dist=/dist bridge_port=8787\n",
            index + 2
        ));
    }
    fs::write(&log, contents).unwrap();

    let candidates = restart_log_candidates(&log);

    assert_eq!(candidates.len(), 2);
    assert!(candidates.iter().all(|(path, _)| path == &recovered));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn restart_log_candidate_always_requires_explicit_selection() {
    let root = temp_dir("untrusted-log");
    let recovered = data_root(&root, "old D drive");
    let log = root.join("restart.log");
    fs::write(
        &log,
        format!(
            "ts=1 component=desktop setup resolved source_root=/x project_root={} app_root=/missing frontend_dist=/x bridge_port=1\n",
            recovered.display()
        ),
    )
    .unwrap();
    let mut options = options(&root);
    options.restart_log_paths.push(log);
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&recovered.canonicalize().unwrap())
            && candidate.source == ProjectRootCandidateSource::RestartLogProjectRoot
            && candidate.selectable
    }));
    assert!(!locator_path.exists());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn registry_hint_always_requires_explicit_selection() {
    let root = temp_dir("untrusted-registry");
    let recovered = data_root(&root, "old-registry-install");
    let mut options = options(&root);
    options.untrusted_candidate_roots.push((
        recovered.clone(),
        ProjectRootCandidateSource::WindowsRegistryInstallDir,
    ));

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&recovered.canonicalize().unwrap())
            && candidate.source == ProjectRootCandidateSource::WindowsRegistryInstallDir
    }));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn installer_app_root_hints_without_project_data_do_not_block_a_fresh_root() {
    let root = temp_dir("installer-app-root-no-data");
    let removed_program_files = root.join("removed-program-files-install");
    let empty_program_files = root.join("empty-program-files-install");
    fs::create_dir_all(empty_program_files.join("data")).unwrap();
    let mut options = options(&root);
    options.untrusted_candidate_roots.extend([
        (
            removed_program_files.clone(),
            ProjectRootCandidateSource::WindowsInstallerAppRootHint,
        ),
        (
            empty_program_files.clone(),
            ProjectRootCandidateSource::WindowsInstallerAppRootHint,
        ),
    ]);
    let locator_path = options.locator_path.clone();
    let current_path = options.app_root.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(resolved.path, current_path.canonicalize().unwrap());
    assert!(!status.requires_selection);
    assert!(locator_path.exists());
    assert!(status.candidates.iter().all(|candidate| {
        candidate.source != ProjectRootCandidateSource::WindowsInstallerAppRootHint
    }));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn installer_app_root_hint_with_strong_data_requires_explicit_selection() {
    let root = temp_dir("installer-app-root-with-data");
    let recovered = data_root(&root, "legacy-msi-app");
    let mut options = options(&root);
    options.untrusted_candidate_roots.push((
        recovered.clone(),
        ProjectRootCandidateSource::WindowsInstallerAppRootHint,
    ));
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(!locator_path.exists());
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&recovered.canonicalize().unwrap())
            && candidate.source == ProjectRootCandidateSource::WindowsInstallerAppRootHint
            && candidate.has_project_data
            && candidate.selectable
    }));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn missing_restart_project_root_blocks_automatic_root_persistence() {
    let root = temp_dir("missing-candidate");
    let offline_project = root.join("offline-drive").join("user-data");
    let offline_app = root.join("offline-drive").join("app");
    let log = root.join("restart.log");
    fs::write(
        &log,
        format!(
            "ts=1 component=desktop setup resolved source_root=/x project_root={} app_root={} frontend_dist=/x bridge_port=1",
            offline_project.display(),
            offline_app.display()
        ),
    )
    .unwrap();
    let mut options = options(&root);
    options.restart_log_paths.push(log);
    let locator_path = options.locator_path.clone();
    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(
        resolved.path,
        root.join("current-app").canonicalize().unwrap()
    );
    assert!(status.requires_selection);
    assert!(!locator_path.exists());
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&offline_project)
            && candidate.source == ProjectRootCandidateSource::RestartLogProjectRoot
            && !candidate.has_project_data
            && !candidate.selectable
    }));
    assert!(status
        .candidates
        .iter()
        .all(|candidate| candidate.path != display_path(&offline_app)));
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&resolved.path) && candidate.selectable
    }));
    assert!(resolved
        .controller
        .select(&display_path(&offline_project))
        .is_err());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn missing_restart_app_root_alone_does_not_block_a_fresh_root() {
    let root = temp_dir("missing-restart-app-root");
    let offline_app = root.join("removed-program-files-install");
    let log = root.join("restart.log");
    let mut options = options(&root);
    fs::write(
        &log,
        format!(
            "ts=1 component=desktop setup resolved source_root=/x project_root={} app_root={} frontend_dist=/x bridge_port=1",
            options.app_root.display(),
            offline_app.display()
        ),
    )
    .unwrap();
    options.restart_log_paths.push(log);
    let locator_path = options.locator_path.clone();
    let current_path = options.app_root.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(resolved.path, current_path.canonicalize().unwrap());
    assert!(!status.requires_selection);
    assert!(locator_path.exists());
    assert!(status
        .candidates
        .iter()
        .all(|candidate| candidate.path != display_path(&offline_app)));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn empty_restart_project_root_at_startup_still_blocks_automatic_persistence() {
    let root = temp_dir("empty-restart-project-root");
    let recovered = root.join("mounted-drive").join("user-data");
    fs::create_dir_all(recovered.join("data")).unwrap();
    let log = root.join("restart.log");
    let mut options = options(&root);
    fs::write(
        &log,
        format!(
            "ts=1 component=desktop setup resolved source_root=/x project_root={} app_root={} frontend_dist=/x bridge_port=1",
            recovered.display(),
            options.app_root.display()
        ),
    )
    .unwrap();
    options.restart_log_paths.push(log);
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(!locator_path.exists());
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&recovered.canonicalize().unwrap())
            && candidate.source == ProjectRootCandidateSource::RestartLogProjectRoot
            && !candidate.has_project_data
            && !candidate.selectable
    }));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn offline_log_candidate_becomes_selectable_after_the_drive_returns() {
    let root = temp_dir("offline-log-rescan");
    let offline_parent = root.join("offline-drive");
    let offline_project = offline_parent.join("user-data");
    let log = root.join("restart.log");
    let mut options = options(&root);
    fs::write(
        &log,
        format!(
            "ts=1 component=desktop setup resolved source_root=/x project_root={} app_root={} frontend_dist=/x bridge_port=1",
            offline_project.display(),
            options.app_root.display()
        ),
    )
    .unwrap();
    options.restart_log_paths.push(log);
    let locator_path = options.locator_path.clone();
    let resolved = resolve(options).unwrap();

    let initial = resolved.controller.status();
    assert!(initial.requires_selection);
    assert!(initial.candidates.iter().any(|candidate| {
        candidate.path == display_path(&offline_project) && !candidate.selectable
    }));
    assert!(!locator_path.exists());

    assert_eq!(data_root(&offline_parent, "user-data"), offline_project);
    let rescanned = resolved.controller.status();
    assert!(rescanned.requires_selection);
    assert!(rescanned.candidates.iter().any(|candidate| {
        candidate.path == display_path(&offline_project)
            && candidate.has_project_data
            && candidate.selectable
    }));

    // The drive can disappear after the UI's scan but before submit.
    // Selection must revalidate live state and must not publish a locator.
    fs::remove_dir_all(&offline_parent).unwrap();
    assert!(resolved
        .controller
        .select(&display_path(&offline_project))
        .is_err());
    assert!(!locator_path.exists());

    assert_eq!(data_root(&offline_parent, "user-data"), offline_project);
    assert!(resolved
        .controller
        .status()
        .candidates
        .iter()
        .any(|candidate| {
            candidate.path == display_path(&offline_project)
                && candidate.has_project_data
                && candidate.selectable
        }));

    let selected = resolved
        .controller
        .select(&display_path(&offline_project))
        .unwrap();
    assert!(!selected.requires_selection);
    assert_eq!(
        read_valid_locator(&locator_path).unwrap(),
        offline_project.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn returned_log_path_without_strong_project_data_stays_unselectable() {
    let root = temp_dir("offline-log-empty-return");
    let offline_project = root.join("offline-drive").join("user-data");
    let log = root.join("restart.log");
    let mut options = options(&root);
    fs::write(
        &log,
        format!(
            "ts=1 component=desktop setup resolved source_root=/x project_root={} app_root={} frontend_dist=/x bridge_port=1",
            offline_project.display(),
            options.app_root.display()
        ),
    )
    .unwrap();
    options.restart_log_paths.push(log);
    let locator_path = options.locator_path.clone();
    let resolved = resolve(options).unwrap();

    fs::create_dir_all(offline_project.join("data")).unwrap();
    let rescanned = resolved.controller.status();

    assert!(rescanned.requires_selection);
    assert!(!locator_path.exists());
    assert!(rescanned.candidates.iter().any(|candidate| {
        candidate.path == display_path(&offline_project)
            && !candidate.has_project_data
            && !candidate.selectable
    }));
    assert!(resolved
        .controller
        .select(&display_path(&offline_project))
        .is_err());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn explicit_fallback_selection_prevents_stale_logs_from_blocking_again() {
    let root = temp_dir("offline-log-fallback");
    let offline_project = root.join("offline-drive").join("user-data");
    let log = root.join("restart.log");
    let mut resolve_options = options(&root);
    fs::write(
        &log,
        format!(
            "ts=1 component=desktop setup resolved source_root=/x project_root={} app_root={} frontend_dist=/x bridge_port=1",
            offline_project.display(),
            resolve_options.app_root.display()
        ),
    )
    .unwrap();
    resolve_options.restart_log_paths.push(log.clone());
    let current_path = resolve_options.app_root.clone();
    let locator_path = resolve_options.locator_path.clone();
    let resolved = resolve(resolve_options).unwrap();

    resolved
        .controller
        .select(&display_path(&current_path))
        .unwrap();
    assert_eq!(
        read_valid_locator(&locator_path).unwrap(),
        current_path.canonicalize().unwrap()
    );

    let mut next_options = options(&root);
    next_options.restart_log_paths.push(log);
    let next = resolve(next_options).unwrap();
    assert_eq!(next.path, current_path.canonicalize().unwrap());
    assert!(!next.controller.status().requires_selection);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn offline_registry_hint_blocks_automatic_root_persistence() {
    let root = temp_dir("offline-registry");
    let offline = root.join("offline-drive").join("legacy-install");
    let mut options = options(&root);
    options.untrusted_candidate_roots.push((
        offline.clone(),
        ProjectRootCandidateSource::WindowsRegistryInstallDir,
    ));
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(!locator_path.exists());
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&offline)
            && candidate.source == ProjectRootCandidateSource::WindowsRegistryInstallDir
            && !candidate.selectable
    }));
    assert!(resolved.controller.select(&display_path(&offline)).is_err());
    let _ = fs::remove_dir_all(root);
}

#[cfg(unix)]
#[test]
fn unwritable_registry_hint_with_strong_data_is_preserved_but_not_selectable() {
    use std::os::unix::fs::PermissionsExt;

    let root = temp_dir("unwritable-registry");
    let recovered = data_root(&root, "legacy-install");
    let data = recovered.join("data");
    let mut permissions = fs::metadata(&data).unwrap().permissions();
    permissions.set_mode(0o555);
    fs::set_permissions(&data, permissions).unwrap();
    let mut options = options(&root);
    options.untrusted_candidate_roots.push((
        recovered.clone(),
        ProjectRootCandidateSource::WindowsRegistryInstallDir,
    ));
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(!locator_path.exists());
    assert!(status.candidates.iter().any(|candidate| {
        candidate.path == display_path(&recovered.canonicalize().unwrap())
            && candidate.source == ProjectRootCandidateSource::WindowsRegistryInstallDir
            && candidate.has_project_data
            && !candidate.selectable
    }));
    assert!(resolved
        .controller
        .select(&display_path(&recovered))
        .is_err());

    let mut permissions = fs::metadata(&data).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&data, permissions).unwrap();
    let _ = fs::remove_dir_all(root);
}

#[test]
fn missing_legacy_app_data_path_does_not_block_a_fresh_root() {
    let root = temp_dir("offline-legacy-data");
    let offline = root.join("offline-drive").join("legacy-project");
    let mut options = options(&root);
    options.legacy_app_data_project_roots.push(offline.clone());
    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(!status.requires_selection);
    assert!(status.candidates.iter().all(|candidate| {
        candidate.path != display_path(&offline)
            || candidate.source != ProjectRootCandidateSource::LegacyAppData
    }));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn standard_config_marker_wins_before_large_cache_scan_budget() {
    let root = temp_dir("large-cache-marker");
    let candidate = data_root(&root, "candidate");
    let cache = candidate.join("data").join("cache");
    fs::create_dir_all(&cache).unwrap();
    for index in 0..(MAX_MARKER_SCAN_ENTRIES + 32) {
        fs::write(cache.join(format!("cache-{index}")), b"x").unwrap();
    }

    assert!(has_meaningful_project_data(&candidate));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn write_probe_never_deletes_a_preexisting_collision() {
    let root = temp_dir("probe-collision");
    let probe = root.join("preexisting-probe");
    fs::write(&probe, b"owned by someone else").unwrap();

    assert!(!write_and_remove_owned_probe(&probe));
    assert_eq!(fs::read(&probe).unwrap(), b"owned by someone else");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn fresh_current_root_precreates_data_directory() {
    let root = temp_dir("fresh-data-directory");
    let options = options(&root);
    let app_root = options.app_root.clone();

    let resolved = resolve(options).unwrap();

    assert_eq!(resolved.path, app_root.canonicalize().unwrap());
    assert!(app_root.join("data").is_dir());
    let _ = fs::remove_dir_all(root);
}

#[cfg(unix)]
#[test]
fn unwritable_data_candidate_is_preserved_but_not_selectable() {
    use std::os::unix::fs::PermissionsExt;

    let root = temp_dir("unwritable-candidate");
    let candidate = data_root(&root, "locked");
    let data = candidate.join("data");
    let mut permissions = fs::metadata(&data).unwrap().permissions();
    permissions.set_mode(0o555);
    fs::set_permissions(&data, permissions).unwrap();
    let mut options = options(&root);
    options
        .legacy_app_data_project_roots
        .push(candidate.clone());
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(
        resolved.path,
        root.join("current-app").canonicalize().unwrap()
    );
    assert!(status.requires_selection);
    assert!(!locator_path.exists());
    assert!(status.candidates.iter().any(|record| {
        record.path == display_path(&candidate.canonicalize().unwrap())
            && record.has_project_data
            && !record.selectable
    }));
    let mut permissions = fs::metadata(&data).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&data, permissions).unwrap();
    let _ = fs::remove_dir_all(root);
}

#[cfg(unix)]
#[test]
fn unwritable_current_app_data_blocks_automatic_fallback_persistence() {
    use std::os::unix::fs::PermissionsExt;

    let root = temp_dir("unwritable-current-app-data");
    let candidate = data_root(&root, "current-app");
    let data = candidate.join("data");
    let mut permissions = fs::metadata(&data).unwrap().permissions();
    permissions.set_mode(0o555);
    fs::set_permissions(&data, permissions).unwrap();
    let options = options(&root);
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert!(status.requires_selection);
    assert!(!locator_path.exists());
    assert!(status.candidates.iter().any(|record| {
        record.path == display_path(&candidate.canonicalize().unwrap())
            && record.source == ProjectRootCandidateSource::CurrentAppRoot
            && record.has_project_data
            && !record.selectable
    }));

    let mut permissions = fs::metadata(&data).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&data, permissions).unwrap();
    let _ = fs::remove_dir_all(root);
}

#[cfg(unix)]
#[test]
fn read_only_install_root_with_writable_data_remains_usable() {
    use std::os::unix::fs::PermissionsExt;

    let root = temp_dir("read-only-install-root");
    let candidate = data_root(&root, "legacy-program-files");
    let mut permissions = fs::metadata(&candidate).unwrap().permissions();
    permissions.set_mode(0o555);
    fs::set_permissions(&candidate, permissions).unwrap();
    let mut options = options(&root);
    options
        .legacy_app_data_project_roots
        .push(candidate.clone());

    let resolved = resolve(options).unwrap();

    assert_eq!(resolved.path, candidate.canonicalize().unwrap());
    let mut permissions = fs::metadata(&candidate).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&candidate, permissions).unwrap();
    let _ = fs::remove_dir_all(root);
}

#[test]
fn multiple_data_roots_require_selection_without_persisting() {
    let root = temp_dir("conflict");
    let current = data_root(&root, "current-app");
    let legacy = data_root(&root, "legacy-project");
    let mut options = options(&root);
    options.legacy_app_data_project_roots.push(legacy.clone());
    let locator_path = options.locator_path.clone();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(resolved.path, current.canonicalize().unwrap());
    assert!(status.conflict);
    assert!(status.requires_selection);
    assert_eq!(status.candidates.len(), 2);
    assert!(!locator_path.exists());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn selection_only_accepts_returned_candidates_and_persists_atomically() {
    let root = temp_dir("selection");
    data_root(&root, "current-app");
    let legacy = data_root(&root, "legacy-project");
    let unrelated = data_root(&root, "unrelated");
    let mut options = options(&root);
    options.legacy_app_data_project_roots.push(legacy.clone());
    let locator_path = options.locator_path.clone();
    let resolved = resolve(options).unwrap();

    assert!(resolved
        .controller
        .select(&display_path(&unrelated))
        .is_err());
    let selected_status = resolved.controller.select(&display_path(&legacy)).unwrap();

    assert!(!selected_status.requires_selection);
    assert_eq!(
        read_valid_locator(&locator_path).unwrap(),
        legacy.canonicalize().unwrap()
    );
    assert!(fs::read_dir(locator_path.parent().unwrap())
        .unwrap()
        .all(|entry| !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .contains(".tmp-")));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn valid_locator_is_never_overwritten() {
    let root = temp_dir("no-overwrite");
    let first = data_root(&root, "first");
    let second = data_root(&root, "second");
    let locator = root.join("config").join(PROJECT_ROOT_LOCATOR_FILE);
    persist_locator_automatically(&locator, &first).unwrap();
    let original = fs::read(&locator).unwrap();

    let error = persist_locator_automatically(&locator, &second).unwrap_err();

    assert!(error.contains("refusing to overwrite valid"));
    assert_eq!(fs::read(locator).unwrap(), original);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn concurrent_selections_cannot_overwrite_the_first_valid_choice() {
    let root = temp_dir("concurrent-selection");
    let first = data_root(&root, "current-app");
    let second = data_root(&root, "second");
    let mut options = options(&root);
    options.legacy_app_data_project_roots.push(second.clone());
    let locator = options.locator_path.clone();
    let controller = Arc::new(resolve(options).unwrap().controller);
    let barrier = Arc::new(Barrier::new(3));

    let select = |path: PathBuf| {
        let controller = Arc::clone(&controller);
        let barrier = Arc::clone(&barrier);
        thread::spawn(move || {
            barrier.wait();
            controller.select(&display_path(&path))
        })
    };
    let first_result = select(first.clone());
    let second_result = select(second.clone());
    barrier.wait();
    let results = [first_result.join().unwrap(), second_result.join().unwrap()];

    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    let persisted = read_valid_locator(&locator).unwrap();
    assert!(
        persisted == first.canonicalize().unwrap()
            || persisted == second.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn portable_marker_uses_app_root_without_overwriting_existing_locator() {
    let root = temp_dir("portable-marker");
    let existing_installed = data_root(&root, "installed-root");
    let options = options(&root);
    let locator = options.locator_path.clone();
    persist_locator_automatically(&locator, &existing_installed).unwrap();

    fs::create_dir_all(&options.app_root).unwrap();
    fs::write(
        options.app_root.join(PORTABLE_ROOT_MARKER_FILE),
        "portable=1\n",
    )
    .unwrap();
    let expected_app_root = options.app_root.canonicalize().unwrap();

    let resolved = resolve(options).unwrap();
    let status = resolved.controller.status();

    assert_eq!(resolved.path, expected_app_root);
    assert!(!status.requires_selection);
    assert_eq!(
        read_valid_locator(&locator).unwrap(),
        existing_installed.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}
