use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use super::{platform::absolute_path, ProjectRootCandidateSource};

pub(super) const MAX_MARKER_SCAN_ENTRIES: usize = 4096;

pub(super) fn prepare_explicit_root(path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return Err(format!(
            "explicit project root must be absolute: {}",
            path.display()
        ));
    }
    let absolute = path.to_path_buf();
    fs::create_dir_all(&absolute).map_err(|error| {
        format!(
            "failed to create explicit project root {}: {error}",
            absolute.display()
        )
    })?;
    validate_existing_project_root(&absolute).ok_or_else(|| {
        format!(
            "explicit project root is not a writable directory: {}",
            absolute.display()
        )
    })
}

pub(super) fn prepare_current_root(
    app_root: &Path,
    app_data_project_root: &Path,
    development_source: bool,
) -> Result<(PathBuf, ProjectRootCandidateSource), String> {
    if let Some(root) = prepare_app_root(app_root) {
        let source = if development_source {
            ProjectRootCandidateSource::DevelopmentSource
        } else {
            ProjectRootCandidateSource::CurrentAppRoot
        };
        return Ok((root, source));
    }

    let app_data = absolute_path(app_data_project_root)?;
    fs::create_dir_all(app_data.join("data")).map_err(|error| {
        format!(
            "failed to create application data project root {}: {error}",
            app_data.display()
        )
    })?;
    let root = validate_existing_project_root(&app_data).ok_or_else(|| {
        format!(
            "application data project root is not writable: {}",
            app_data.display()
        )
    })?;
    Ok((root, ProjectRootCandidateSource::CurrentAppData))
}

pub(super) fn prepare_app_root(app_root: &Path) -> Option<PathBuf> {
    if app_root.join("data").is_dir() {
        return validate_existing_writable_project_root(app_root);
    }
    let root = validate_existing_writable_root(app_root)?;
    fs::create_dir_all(root.join("data")).ok()?;
    can_write_directory(&root.join("data")).then_some(root)
}

pub(super) fn prepare_project_root_for_persistence(project_root: &Path) -> Result<PathBuf, String> {
    if !project_root.is_absolute() || !project_root.is_dir() {
        return Err(format!(
            "cannot persist an invalid project root: {}",
            project_root.display()
        ));
    }
    let data = project_root.join("data");
    fs::create_dir_all(&data).map_err(|error| {
        format!(
            "failed to prepare project data directory {} before persisting its locator: {error}",
            data.display()
        )
    })?;
    validate_existing_writable_project_root(project_root).ok_or_else(|| {
        format!(
            "cannot persist a project root whose data directory is not writable: {}",
            project_root.display()
        )
    })
}

pub(super) fn validate_existing_writable_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() || !path.is_dir() || !can_write_directory(path) {
        return None;
    }
    path.canonicalize().ok()
}

pub(super) fn validate_existing_writable_project_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() || !path.is_dir() {
        return None;
    }
    let data = path.join("data");
    if !data.is_dir() || !can_write_directory(&data) {
        return None;
    }
    path.canonicalize().ok()
}

pub(super) fn validate_existing_project_root(path: &Path) -> Option<PathBuf> {
    if path.join("data").is_dir() {
        validate_existing_writable_project_root(path)
    } else {
        validate_existing_writable_root(path)
    }
}

pub(super) fn can_write_directory(path: &Path) -> bool {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let probe = path.join(format!(
        ".shinsekai-write-test-{}-{nonce}",
        std::process::id()
    ));
    write_and_remove_owned_probe(&probe)
}

pub(super) fn write_and_remove_owned_probe(probe: &Path) -> bool {
    let Ok(mut file) = OpenOptions::new().write(true).create_new(true).open(probe) else {
        return false;
    };
    let written = file.write_all(b"ok").is_ok();
    drop(file);
    let removed = fs::remove_file(probe).is_ok();
    written && removed
}

pub(super) fn has_meaningful_project_data(root: &Path) -> bool {
    let data = root.join("data");
    has_strong_project_data(root) || directory_contains_file(&data, MAX_MARKER_SCAN_ENTRIES)
}

pub(super) fn has_strong_project_data(root: &Path) -> bool {
    let data = root.join("data");
    if !data.is_dir() {
        return false;
    }

    const FILE_MARKERS: &[&str] = &[
        "config/api.yaml",
        "config/background.yaml",
        "config/characters.yaml",
        "config/plugins.yaml",
        "config/system_config.yaml",
        "config/llm_model_capabilities.json",
    ];
    if FILE_MARKERS
        .iter()
        .any(|marker| data.join(marker).is_file())
    {
        return true;
    }

    const DIRECTORY_MARKERS: &[&str] = &[
        "backgrounds",
        "bgm",
        "character_templates",
        "chat_history",
        "chat_ui_themes",
        "config",
        "memory",
        "models",
        "plugins",
        "speech",
        "sprite",
        "tts_bundles",
    ];
    DIRECTORY_MARKERS
        .iter()
        .any(|marker| directory_contains_file(&data.join(marker), MAX_MARKER_SCAN_ENTRIES))
}

fn directory_contains_file(path: &Path, max_entries: usize) -> bool {
    let mut pending = vec![path.to_path_buf()];
    let mut scanned = 0;
    while let Some(directory) = pending.pop() {
        let Ok(entries) = fs::read_dir(directory) else {
            continue;
        };
        for entry in entries.flatten() {
            scanned += 1;
            if scanned > max_entries {
                return false;
            }
            let entry_path = entry.path();
            let Ok(file_type) = entry.file_type() else {
                continue;
            };
            if file_type.is_file() {
                let ignored = entry
                    .file_name()
                    .to_str()
                    .is_some_and(|name| matches!(name, ".gitkeep" | ".DS_Store"));
                if !ignored {
                    return true;
                }
            } else if file_type.is_dir() {
                pending.push(entry_path);
            }
        }
    }
    false
}
