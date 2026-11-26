use std::{
    fs::{self, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};

use super::{
    platform::{display_path, lock_locator_file},
    probe::{prepare_project_root_for_persistence, validate_existing_writable_project_root},
    PROJECT_ROOT_LOCATOR_FILE,
};

pub(super) const PROJECT_ROOT_LOCATOR_VERSION: u32 = 1;
pub(super) const MAX_PROJECT_ROOT_LOCATOR_BYTES: u64 = 256 * 1024;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct ProjectRootLocator {
    pub(super) version: u32,
    pub(super) project_root: String,
}

pub(super) enum LocatorState {
    AbsentOrEmpty,
    Malformed,
    Available(PathBuf),
    Unavailable(PathBuf),
    UnsupportedVersion { version: u64, path: Option<PathBuf> },
}

pub(super) enum BlockingLocator {
    Malformed,
    Unavailable(PathBuf),
    UnsupportedVersion { version: u64, path: Option<PathBuf> },
}

pub(super) fn read_locator_state(locator_path: &Path) -> LocatorState {
    let file = match fs::File::open(locator_path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return LocatorState::AbsentOrEmpty;
        }
        Err(_) => return LocatorState::Malformed,
    };
    let mut content = Vec::new();
    if file
        .take(MAX_PROJECT_ROOT_LOCATOR_BYTES + 1)
        .read_to_end(&mut content)
        .is_err()
        || content.len() as u64 > MAX_PROJECT_ROOT_LOCATOR_BYTES
    {
        return LocatorState::Malformed;
    }
    if content.is_empty() {
        return LocatorState::AbsentOrEmpty;
    }
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(&content) else {
        return LocatorState::Malformed;
    };
    let Some(version) = value.get("version").and_then(serde_json::Value::as_u64) else {
        return LocatorState::Malformed;
    };
    if version != u64::from(PROJECT_ROOT_LOCATOR_VERSION) {
        let path = value
            .get("projectRoot")
            .and_then(serde_json::Value::as_str)
            .map(PathBuf::from)
            .filter(|path| path.is_absolute());
        return LocatorState::UnsupportedVersion { version, path };
    }
    let Ok(locator) = serde_json::from_value::<ProjectRootLocator>(value) else {
        return LocatorState::Malformed;
    };
    let path = PathBuf::from(locator.project_root);
    if !path.is_absolute() {
        return LocatorState::Malformed;
    }
    // A persisted v1 locator describes an established project root. Unlike an
    // explicit/new root, it is only usable when its data directory still exists
    // and is writable. Treat a missing data directory as unavailable so an
    // offline or partially removed root cannot silently look like a fresh root.
    validate_existing_writable_project_root(&path)
        .map(LocatorState::Available)
        .unwrap_or(LocatorState::Unavailable(path))
}

#[cfg(test)]
pub(super) fn read_valid_locator(locator_path: &Path) -> Option<PathBuf> {
    match read_locator_state(locator_path) {
        LocatorState::Available(path) => Some(path),
        LocatorState::AbsentOrEmpty
        | LocatorState::Malformed
        | LocatorState::Unavailable(_)
        | LocatorState::UnsupportedVersion { .. } => None,
    }
}

pub(super) fn persist_locator_automatically(
    locator_path: &Path,
    project_root: &Path,
) -> Result<(), String> {
    persist_locator(locator_path, project_root, false)
}

pub(super) fn persist_selected_locator(
    locator_path: &Path,
    project_root: &Path,
) -> Result<(), String> {
    persist_locator(locator_path, project_root, true)
}

pub(super) fn migrate_legacy_locator(
    locator_path: &Path,
    legacy_root: &Path,
) -> Result<PathBuf, String> {
    let migration_error = persist_locator_automatically(locator_path, legacy_root).err();
    match read_locator_state(locator_path) {
        LocatorState::Available(authoritative_root) => Ok(authoritative_root),
        _ => {
            let detail = migration_error
                .map(|error| format!(" migration failed: {error}"))
                .unwrap_or_default();
            Err(format!(
                "legacy project root locator could not be migrated to {}; refusing to run with an ambiguous project root.{detail}",
                locator_path.display()
            ))
        }
    }
}

fn persist_locator(
    locator_path: &Path,
    project_root: &Path,
    replace_unavailable: bool,
) -> Result<(), String> {
    let project_root = prepare_project_root_for_persistence(project_root)?;
    let parent = locator_path.parent().ok_or_else(|| {
        format!(
            "project root locator has no parent directory: {}",
            locator_path.display()
        )
    })?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "failed to create project root locator directory {}: {error}",
            parent.display()
        )
    })?;
    let _lock = LocatorWriteLock::acquire(parent)?;
    if locator_replacement_is_already_complete(
        read_locator_state(locator_path),
        locator_path,
        &project_root,
        replace_unavailable,
    )? {
        return Ok(());
    }
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let temp_path = parent.join(format!(
        ".{PROJECT_ROOT_LOCATOR_FILE}.tmp-{}-{nonce}",
        std::process::id()
    ));
    let locator = ProjectRootLocator {
        version: PROJECT_ROOT_LOCATOR_VERSION,
        project_root: display_path(&project_root),
    };
    let mut contents = serde_json::to_vec_pretty(&locator)
        .map_err(|error| format!("failed to serialize project root locator: {error}"))?;
    contents.push(b'\n');

    let write_result = (|| -> Result<(), String> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)
            .map_err(|error| {
                format!(
                    "failed to create temporary project root locator {}: {error}",
                    temp_path.display()
                )
            })?;
        file.write_all(&contents).map_err(|error| {
            format!(
                "failed to write temporary project root locator {}: {error}",
                temp_path.display()
            )
        })?;
        file.sync_all().map_err(|error| {
            format!(
                "failed to sync temporary project root locator {}: {error}",
                temp_path.display()
            )
        })?;

        // Re-check immediately before the atomic replacement. This preserves a
        // valid locator if another resolver completed while this file was built.
        if locator_replacement_is_already_complete(
            read_locator_state(locator_path),
            locator_path,
            &project_root,
            replace_unavailable,
        )? {
            return Ok(());
        }
        crate::atomic_file::commit(&temp_path, locator_path).map_err(|error| {
            format!(
                "failed to atomically publish project root locator {}: {error}",
                locator_path.display()
            )
        })?;
        Ok(())
    })();
    let _ = fs::remove_file(&temp_path);
    write_result
}

fn locator_replacement_is_already_complete(
    state: LocatorState,
    locator_path: &Path,
    project_root: &Path,
    replace_unavailable: bool,
) -> Result<bool, String> {
    match state {
        LocatorState::Available(existing) if existing == project_root => Ok(true),
        LocatorState::Available(existing) => Err(format!(
            "refusing to overwrite valid project root locator {} (currently {})",
            locator_path.display(),
            existing.display()
        )),
        LocatorState::Unavailable(existing) if !replace_unavailable => Err(format!(
            "refusing to overwrite unavailable project root locator {} (currently {})",
            locator_path.display(),
            existing.display()
        )),
        LocatorState::Malformed if !replace_unavailable => Err(format!(
            "refusing to automatically overwrite malformed project root locator {}",
            locator_path.display()
        )),
        LocatorState::UnsupportedVersion { version, .. } => Err(format!(
            "project root locator {} uses unsupported schema version {}; update Shinsekai before changing it",
            locator_path.display(),
            version
        )),
        LocatorState::AbsentOrEmpty
        | LocatorState::Malformed
        | LocatorState::Unavailable(_) => Ok(false),
    }
}

struct LocatorWriteLock {
    _file: fs::File,
}

impl LocatorWriteLock {
    fn acquire(parent: &Path) -> Result<Self, String> {
        let path = parent.join(format!(".{PROJECT_ROOT_LOCATOR_FILE}.lock"));
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&path)
            .map_err(|error| {
                format!(
                    "failed to open project root locator lock {}: {error}",
                    path.display()
                )
            })?;
        lock_locator_file(&file).map_err(|error| {
            format!(
                "failed to acquire project root locator lock {}: {error}",
                path.display()
            )
        })?;
        Ok(Self { _file: file })
    }
}
