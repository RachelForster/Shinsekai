use std::{
    collections::HashSet,
    ffi::OsString,
    fs::{self, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};

use crate::path_contract::{
    canonicalize_directory_without_links, canonicalize_regular_file_without_links,
    files_have_same_identity, metadata_is_link, open_directory_without_links,
    open_regular_file_without_links, path_is_filesystem_root, path_text_is_portable,
};

#[cfg(windows)]
use std::os::windows::ffi::{OsStrExt, OsStringExt};
#[cfg(windows)]
use std::os::windows::fs::OpenOptionsExt;
#[cfg(windows)]
use std::os::windows::io::AsRawHandle;

#[cfg(unix)]
use std::os::{fd::AsRawFd, unix::fs::OpenOptionsExt};

#[cfg(windows)]
#[link(name = "kernel32")]
unsafe extern "system" {
    fn MoveFileExW(existing_file_name: *const u16, new_file_name: *const u16, flags: u32) -> i32;
    fn LockFileEx(
        file: *mut std::ffi::c_void,
        flags: u32,
        reserved: u32,
        bytes_low: u32,
        bytes_high: u32,
        overlapped: *mut WindowsOverlapped,
    ) -> i32;
}

#[cfg(windows)]
#[repr(C)]
struct WindowsOverlapped {
    internal: usize,
    internal_high: usize,
    offset: u32,
    offset_high: u32,
    event: *mut std::ffi::c_void,
}

#[cfg(windows)]
#[link(name = "advapi32")]
unsafe extern "system" {
    fn RegGetValueW(
        key: *mut std::ffi::c_void,
        sub_key: *const u16,
        value: *const u16,
        flags: u32,
        value_type: *mut u32,
        data: *mut std::ffi::c_void,
        data_size: *mut u32,
    ) -> i32;
}

#[cfg(windows)]
const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
#[cfg(windows)]
const MOVEFILE_WRITE_THROUGH: u32 = 0x8;
#[cfg(windows)]
const LOCKFILE_EXCLUSIVE_LOCK: u32 = 0x2;
#[cfg(windows)]
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
#[cfg(windows)]
const HKEY_CURRENT_USER: *mut std::ffi::c_void = (-2_147_483_647_isize) as *mut std::ffi::c_void;
#[cfg(windows)]
const RRF_RT_REG_SZ_OR_EXPAND_SZ: u32 = 0x2 | 0x4;

pub(crate) const CURRENT_APP_IDENTIFIER: &str = "studio.shinsekai";
pub(crate) const LEGACY_APP_IDENTIFIER: &str = "icu.end0rph1n.shinsekai";
pub(crate) const PROJECT_ROOT_LOCATOR_FILE: &str = "project-root.json";

const PROJECT_ROOT_LOCATOR_VERSION: u32 = 1;
const MAX_PROJECT_ROOT_LOCATOR_BYTES: u64 = 256 * 1024;
const MAX_RESTART_LOG_BYTES: usize = 2 * 1024 * 1024;
const MAX_RESTART_LOG_CANDIDATES: usize = 16;
const MAX_RECOVERY_CANDIDATES: usize = 40;
const MAX_MARKER_SCAN_ENTRIES: usize = 4096;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) enum ProjectRootCandidateSource {
    EnvironmentOverride,
    PersistedLocator,
    CurrentAppRoot,
    CurrentAppData,
    LegacyAppData,
    RestartLogProjectRoot,
    RestartLogAppRoot,
    #[cfg_attr(not(windows), allow(dead_code))]
    WindowsRegistryInstallDir,
    #[cfg_attr(not(windows), allow(dead_code))]
    WindowsInstallerAppRootHint,
    DevelopmentSource,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProjectRootCandidate {
    pub(crate) path: String,
    pub(crate) source: ProjectRootCandidateSource,
    pub(crate) has_project_data: bool,
    pub(crate) selectable: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProjectRootStatus {
    pub(crate) current_path: String,
    pub(crate) locator_path: String,
    pub(crate) conflict: bool,
    pub(crate) requires_selection: bool,
    pub(crate) candidates: Vec<ProjectRootCandidate>,
}

#[derive(Debug)]
struct CandidateRecord {
    path: PathBuf,
    source: ProjectRootCandidateSource,
    has_project_data: bool,
    selectable: bool,
    trusted_for_automatic_selection: bool,
    allow_empty_project_data: bool,
}

pub(crate) struct ProjectRootController {
    locator_path: PathBuf,
    candidates: Vec<CandidateRecord>,
    selection_allowed: bool,
    status: Mutex<ProjectRootStatus>,
}

impl ProjectRootController {
    pub(crate) fn status(&self) -> ProjectRootStatus {
        let mut status = self
            .status
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if self.selection_allowed && status.requires_selection {
            status.candidates = self
                .candidates
                .iter()
                .map(current_candidate_snapshot)
                .collect();
        }
        status.clone()
    }

    pub(crate) fn select(&self, requested: &str) -> Result<ProjectRootStatus, String> {
        if !self.selection_allowed {
            return Err(
                "project root selection is disabled by an environment override or an unsupported locator schema"
                    .to_string(),
            );
        }

        let requested_path = PathBuf::from(requested);
        let normalized = validate_existing_project_root(&requested_path).ok_or_else(|| {
            format!(
                "project root selection is not an absolute, existing, writable directory: {}",
                requested_path.display()
            )
        })?;
        let selected = self
            .candidates
            .iter()
            .find(|candidate| path_identity(&candidate.path) == path_identity(&normalized))
            .ok_or_else(|| {
                "project root selection was not one of the candidates returned by the resolver"
                    .to_string()
            })?;
        if !current_candidate_snapshot(selected).selectable {
            return Err(format!(
                "project root selection is not currently available or does not contain recognized project data: {}",
                requested_path.display()
            ));
        }

        persist_selected_locator(&self.locator_path, &normalized)?;

        let mut status = self
            .status
            .lock()
            .map_err(|_| "project root status lock is poisoned".to_string())?;
        status.current_path = display_path(&normalized);
        status.conflict = false;
        status.requires_selection = false;
        status.candidates = self
            .candidates
            .iter()
            .map(current_candidate_snapshot)
            .collect();
        Ok(status.clone())
    }
}

pub(crate) struct ResolvedProjectRoot {
    pub(crate) path: PathBuf,
    pub(crate) controller: ProjectRootController,
}

pub(crate) struct ProjectRootResolveOptions {
    pub(crate) explicit_root: Option<(PathBuf, ProjectRootCandidateSource)>,
    pub(crate) source_root: PathBuf,
    pub(crate) app_root: PathBuf,
    pub(crate) current_app_data_project_root: PathBuf,
    pub(crate) legacy_app_data_project_roots: Vec<PathBuf>,
    pub(crate) locator_path: PathBuf,
    pub(crate) locator_read_paths: Vec<PathBuf>,
    pub(crate) restart_log_paths: Vec<PathBuf>,
    pub(crate) untrusted_candidate_roots: Vec<(PathBuf, ProjectRootCandidateSource)>,
    pub(crate) development_source: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProjectRootLocator {
    version: u32,
    project_root: String,
}

enum LocatorState {
    AbsentOrEmpty,
    Malformed,
    Available(PathBuf),
    Unavailable(PathBuf),
    UnsupportedVersion { version: u64, path: Option<PathBuf> },
}

enum BlockingLocator {
    Malformed,
    Unavailable(PathBuf),
    UnsupportedVersion { version: u64, path: Option<PathBuf> },
}

pub(crate) fn preferred_environment_root(
    shinsekai: Option<OsString>,
    easyai: Option<OsString>,
) -> Option<(PathBuf, ProjectRootCandidateSource)> {
    shinsekai.or(easyai).map(|value| {
        (
            PathBuf::from(value),
            ProjectRootCandidateSource::EnvironmentOverride,
        )
    })
}

#[cfg(not(windows))]
pub(crate) fn windows_legacy_install_dir_hints() -> Vec<(PathBuf, ProjectRootCandidateSource)> {
    Vec::new()
}

#[cfg(windows)]
pub(crate) fn windows_legacy_install_dir_hints() -> Vec<(PathBuf, ProjectRootCandidateSource)> {
    // NSIS records the matched MSI app root before removing it. It is not a
    // blocker when it disappears normally or contains no project data. The two
    // historical InstallDir spellings retain their older offline-recovery
    // semantics. Every registry path remains untrusted and requires strong data
    // markers plus explicit UI confirmation before it can become authoritative.
    const LEGACY_ROOT_VALUES: &[(&str, &str, ProjectRootCandidateSource)] = &[
        (
            "Software\\studio.shinsekai\\Migration",
            "LegacyMsiAppRoot",
            ProjectRootCandidateSource::WindowsInstallerAppRootHint,
        ),
        (
            "Software\\shinsekai\\Shinsekai",
            "InstallDir",
            ProjectRootCandidateSource::WindowsRegistryInstallDir,
        ),
        (
            "Software\\Shinsekai Contributors\\Shinsekai",
            "InstallDir",
            ProjectRootCandidateSource::WindowsRegistryInstallDir,
        ),
    ];
    LEGACY_ROOT_VALUES
        .iter()
        .filter_map(|&(key, value, source)| {
            read_current_user_registry_string(key, value).map(|path| (path, source))
        })
        .filter(|(path, _)| {
            !path.is_empty()
                && !path
                    .to_string_lossy()
                    .chars()
                    .any(|character| matches!(character, '\0' | '\r' | '\n'))
        })
        .map(|(path, source)| (PathBuf::from(path), source))
        .collect()
}

#[cfg(windows)]
fn read_current_user_registry_string(sub_key: &str, value: &str) -> Option<OsString> {
    let sub_key: Vec<u16> = OsString::from(sub_key)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let value: Vec<u16> = OsString::from(value).encode_wide().chain(Some(0)).collect();
    let mut byte_len = 0_u32;
    let size_result = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            sub_key.as_ptr(),
            value.as_ptr(),
            RRF_RT_REG_SZ_OR_EXPAND_SZ,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut byte_len,
        )
    };
    if size_result != 0 || byte_len < 2 {
        return None;
    }
    let mut buffer = vec![0_u16; byte_len.div_ceil(2) as usize];
    let read_result = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            sub_key.as_ptr(),
            value.as_ptr(),
            RRF_RT_REG_SZ_OR_EXPAND_SZ,
            std::ptr::null_mut(),
            buffer.as_mut_ptr().cast(),
            &mut byte_len,
        )
    };
    if read_result != 0 {
        return None;
    }
    let value_len = buffer.iter().position(|value| *value == 0)?;
    Some(OsString::from_wide(&buffer[..value_len]))
}

pub(crate) fn resolve(options: ProjectRootResolveOptions) -> Result<ResolvedProjectRoot, String> {
    let locator_path = absolute_path(&options.locator_path)?;

    if let Some((explicit_root, source)) = options.explicit_root {
        let path = prepare_explicit_root(&explicit_root)?;
        let candidate = CandidateRecord {
            has_project_data: has_meaningful_project_data(&path),
            path: path.clone(),
            source,
            selectable: true,
            trusted_for_automatic_selection: false,
            allow_empty_project_data: true,
        };
        return Ok(resolution(
            path,
            locator_path,
            vec![candidate],
            false,
            false,
        ));
    }

    if options.development_source {
        let path = prepare_app_root(&options.source_root).ok_or_else(|| {
            format!(
                "development project root is not writable: {}",
                options.source_root.display()
            )
        })?;
        let candidate = CandidateRecord {
            has_project_data: has_meaningful_project_data(&path),
            path: path.clone(),
            source: ProjectRootCandidateSource::DevelopmentSource,
            selectable: true,
            trusted_for_automatic_selection: true,
            allow_empty_project_data: true,
        };
        return Ok(resolution(
            path,
            locator_path,
            vec![candidate],
            false,
            false,
        ));
    }

    // The platform config directory may itself be reached through a symlink or
    // reparse-point alias. Resolve that parent once before any locator read,
    // lock, temporary write, or later UI selection so all operations remain
    // attached to one directory identity even if the alias is retargeted.
    let locator_path = prepare_primary_locator_path(&locator_path)?;

    let locator_read_paths = deduplicate_paths(
        std::iter::once(locator_path.clone()).chain(options.locator_read_paths.iter().cloned()),
    );
    let mut blocking_locator = None;
    for candidate_locator in locator_read_paths {
        match read_locator_state(&candidate_locator) {
            LocatorState::Available(mut path) => {
                if candidate_locator != locator_path {
                    // Once a legacy locator is migrated, the primary locator is the
                    // authority. Re-read it even when the write fails: another process
                    // may have won the race with a different valid selection. Never run
                    // from the legacy root while the primary locator says otherwise.
                    path = migrate_legacy_locator(&locator_path, &path)?;
                }
                let candidate = CandidateRecord {
                    has_project_data: has_meaningful_project_data(&path),
                    path: path.clone(),
                    source: ProjectRootCandidateSource::PersistedLocator,
                    selectable: true,
                    trusted_for_automatic_selection: true,
                    allow_empty_project_data: true,
                };
                return Ok(resolution(path, locator_path, vec![candidate], true, false));
            }
            LocatorState::Unavailable(path) => {
                // A removable/offline drive and a temporarily unwritable directory
                // must not silently reset the user's prior choice. Stop at the first
                // structurally valid locator and require an explicit replacement.
                blocking_locator = Some(BlockingLocator::Unavailable(path));
                break;
            }
            LocatorState::Malformed if candidate_locator == locator_path => {
                blocking_locator = Some(BlockingLocator::Malformed);
                break;
            }
            LocatorState::UnsupportedVersion { version, path } => {
                blocking_locator = Some(BlockingLocator::UnsupportedVersion { version, path });
                break;
            }
            LocatorState::AbsentOrEmpty | LocatorState::Malformed => {}
        }
    }

    let mut data_candidates = Vec::new();
    let mut seen = HashSet::new();
    // Installation directories are executable/resource locations, not data
    // locations. Only a strong legacy-data signature may promote one to a
    // recovery candidate; a packaged cache, schema, or other incidental file
    // under `data/` must never recreate the old install-as-project behavior.
    if has_strong_project_data(&options.app_root) {
        add_data_candidate(
            &mut data_candidates,
            &mut seen,
            &options.app_root,
            ProjectRootCandidateSource::CurrentAppRoot,
            true,
            true,
        );
    }
    add_data_candidate(
        &mut data_candidates,
        &mut seen,
        &options.current_app_data_project_root,
        ProjectRootCandidateSource::CurrentAppData,
        true,
        true,
    );
    for path in &options.legacy_app_data_project_roots {
        add_data_candidate(
            &mut data_candidates,
            &mut seen,
            path,
            ProjectRootCandidateSource::LegacyAppData,
            true,
            true,
        );
    }
    for log_path in &options.restart_log_paths {
        for (path, source) in restart_log_candidates(log_path) {
            if data_candidates.len() >= MAX_RECOVERY_CANDIDATES {
                break;
            }
            // Older production builds could report the writable installation
            // directory as their project root even before any user data was
            // created.  Once installation and data roots are separated, that
            // empty current app directory is not a recovery candidate and
            // must not force a meaningless migration prompt.  A different
            // (for example removed/old) app path is still retained, as is a
            // current app root that actually contains project data.
            if source == ProjectRootCandidateSource::RestartLogProjectRoot
                && path_identity(&path) == path_identity(&options.app_root)
                && !has_strong_project_data(&path)
            {
                continue;
            }
            add_data_candidate(&mut data_candidates, &mut seen, &path, source, false, true);
        }
        if data_candidates.len() >= MAX_RECOVERY_CANDIDATES {
            break;
        }
    }
    for (path, source) in options
        .untrusted_candidate_roots
        .iter()
        .take(MAX_RECOVERY_CANDIDATES.saturating_sub(data_candidates.len()))
    {
        add_data_candidate(&mut data_candidates, &mut seen, path, *source, false, true);
    }

    if let Some(blocking_locator) = blocking_locator {
        let (current_path, current_source) = prepare_current_root(
            &options.app_root,
            &options.current_app_data_project_root,
            false,
        )?;
        put_current_candidate_first(
            &mut data_candidates,
            &mut seen,
            &current_path,
            current_source,
        );
        let selection_allowed = match blocking_locator {
            BlockingLocator::Malformed => true,
            BlockingLocator::Unavailable(unavailable_path) => {
                if seen.insert(path_identity(&unavailable_path)) {
                    data_candidates.push(CandidateRecord {
                        path: unavailable_path,
                        source: ProjectRootCandidateSource::PersistedLocator,
                        has_project_data: false,
                        selectable: false,
                        trusted_for_automatic_selection: false,
                        allow_empty_project_data: true,
                    });
                }
                true
            }
            BlockingLocator::UnsupportedVersion { version, path } => {
                if let Some(path) = path {
                    if seen.insert(path_identity(&path)) {
                        data_candidates.push(CandidateRecord {
                            path,
                            source: ProjectRootCandidateSource::PersistedLocator,
                            has_project_data: false,
                            selectable: false,
                            trusted_for_automatic_selection: false,
                            allow_empty_project_data: true,
                        });
                    }
                }
                for candidate in &mut data_candidates {
                    candidate.selectable = false;
                }
                let _ = version;
                false
            }
        };
        return Ok(resolution(
            current_path,
            locator_path,
            data_candidates,
            selection_allowed,
            true,
        ));
    }

    if data_candidates.len() == 1
        && data_candidates[0].selectable
        && data_candidates[0].trusted_for_automatic_selection
    {
        let selected = data_candidates[0].path.clone();
        persist_locator_automatically(&locator_path, &selected)?;
        return Ok(resolution(
            selected,
            locator_path,
            data_candidates,
            true,
            false,
        ));
    }

    let (current_path, current_source) = prepare_current_root(
        &options.app_root,
        &options.current_app_data_project_root,
        false,
    )?;

    if !data_candidates.is_empty() {
        put_current_candidate_first(
            &mut data_candidates,
            &mut seen,
            &current_path,
            current_source,
        );
        // A recovery record that resolves to the prepared current root is not
        // an ambiguity. This commonly happens after the old MSI app directory
        // disappears while the last logged project root already points at the
        // current per-user location.
        if data_candidates.len() == 1
            && data_candidates[0].selectable
            && data_candidates[0].trusted_for_automatic_selection
        {
            persist_locator_automatically(&locator_path, &current_path)?;
            return Ok(resolution(
                current_path,
                locator_path,
                data_candidates,
                true,
                false,
            ));
        }
        return Ok(resolution(
            current_path,
            locator_path,
            data_candidates,
            true,
            true,
        ));
    }

    let candidate = CandidateRecord {
        path: current_path.clone(),
        source: current_source,
        has_project_data: false,
        selectable: true,
        trusted_for_automatic_selection: true,
        allow_empty_project_data: true,
    };
    persist_locator_automatically(&locator_path, &current_path)?;
    Ok(resolution(
        current_path,
        locator_path,
        vec![candidate],
        true,
        false,
    ))
}

fn put_current_candidate_first(
    candidates: &mut Vec<CandidateRecord>,
    seen: &mut HashSet<String>,
    current_path: &Path,
    current_source: ProjectRootCandidateSource,
) {
    if seen.insert(path_identity(current_path)) {
        candidates.insert(
            0,
            CandidateRecord {
                path: current_path.to_path_buf(),
                source: current_source,
                has_project_data: has_meaningful_project_data(current_path),
                selectable: true,
                trusted_for_automatic_selection: true,
                allow_empty_project_data: true,
            },
        );
    } else if let Some(index) = candidates
        .iter()
        .position(|candidate| path_identity(&candidate.path) == path_identity(current_path))
    {
        candidates.swap(0, index);
        candidates[0].selectable = true;
        candidates[0].trusted_for_automatic_selection = true;
        candidates[0].allow_empty_project_data = true;
        if matches!(
            candidates[0].source,
            ProjectRootCandidateSource::RestartLogProjectRoot
                | ProjectRootCandidateSource::RestartLogAppRoot
                | ProjectRootCandidateSource::WindowsRegistryInstallDir
                | ProjectRootCandidateSource::WindowsInstallerAppRootHint
        ) {
            candidates[0].source = current_source;
        }
    }
}

fn resolution(
    path: PathBuf,
    locator_path: PathBuf,
    candidates: Vec<CandidateRecord>,
    selection_allowed: bool,
    conflict: bool,
) -> ResolvedProjectRoot {
    let status = ProjectRootStatus {
        current_path: display_path(&path),
        locator_path: display_path(&locator_path),
        conflict,
        requires_selection: conflict,
        candidates: candidates
            .iter()
            .map(|candidate| ProjectRootCandidate {
                path: display_path(&candidate.path),
                source: candidate.source,
                has_project_data: candidate.has_project_data,
                selectable: candidate.selectable,
            })
            .collect(),
    };
    ResolvedProjectRoot {
        path,
        controller: ProjectRootController {
            locator_path,
            candidates,
            selection_allowed,
            status: Mutex::new(status),
        },
    }
}

fn current_candidate_snapshot(candidate: &CandidateRecord) -> ProjectRootCandidate {
    // Keep the UI's enabled state and the final selection check on the same
    // live filesystem view. Untrusted recovery hints need strong data markers;
    // prepared current roots and persisted locators may legitimately be empty.
    let has_project_data = if matches!(
        candidate.source,
        ProjectRootCandidateSource::RestartLogProjectRoot
            | ProjectRootCandidateSource::RestartLogAppRoot
            | ProjectRootCandidateSource::WindowsRegistryInstallDir
            | ProjectRootCandidateSource::WindowsInstallerAppRootHint
    ) {
        has_strong_project_data(&candidate.path)
    } else {
        has_meaningful_project_data(&candidate.path)
    };
    let writable_project_root = validate_existing_writable_project_root(&candidate.path).is_some();
    ProjectRootCandidate {
        path: display_path(&candidate.path),
        source: candidate.source,
        has_project_data,
        selectable: writable_project_root
            && (candidate.allow_empty_project_data || has_project_data),
    }
}

fn prepare_explicit_root(path: &Path) -> Result<PathBuf, String> {
    if !path_text_is_portable(path) {
        return Err(format!(
            "explicit project root contains non-portable characters: {}",
            path.display()
        ));
    }
    if !path.is_absolute() {
        return Err(format!(
            "explicit project root must be absolute: {}",
            path.display()
        ));
    }
    if path_is_filesystem_root(path) {
        return Err(format!(
            "explicit project root must not be a filesystem root: {}",
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

fn prepare_current_root(
    app_root: &Path,
    app_data_project_root: &Path,
    development_source: bool,
) -> Result<(PathBuf, ProjectRootCandidateSource), String> {
    // A writable installation directory is not, by itself, a writable-data
    // contract.  Per-user installers and portable distributions are commonly
    // writable, but an update can replace or remove that directory.  Preserve
    // an application root only when it already contains meaningful project
    // data (or when source development explicitly selected it); otherwise a
    // fresh production install must start in the platform app-data directory.
    if development_source || has_strong_project_data(app_root) {
        if let Some(root) = prepare_app_root(app_root) {
            let source = if development_source {
                ProjectRootCandidateSource::DevelopmentSource
            } else {
                ProjectRootCandidateSource::CurrentAppRoot
            };
            return Ok((root, source));
        }
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

fn prepare_app_root(app_root: &Path) -> Option<PathBuf> {
    if app_root.join("data").is_dir() {
        return validate_existing_writable_project_root(app_root);
    }
    let root = validate_existing_writable_root(app_root)?;
    let root_identity = open_directory_without_links(&root).ok()?;
    fs::create_dir_all(root.join("data")).ok()?;
    if !path_refers_to_open_directory(&root, &root_identity) {
        return None;
    }
    let prepared = validate_existing_writable_project_root(&root)?;
    (prepared == root && path_refers_to_open_directory(&root, &root_identity)).then_some(prepared)
}

fn add_data_candidate(
    candidates: &mut Vec<CandidateRecord>,
    seen: &mut HashSet<String>,
    path: &Path,
    source: ProjectRootCandidateSource,
    trusted_for_automatic_selection: bool,
    retain_unavailable: bool,
) {
    if !path.is_absolute() || !path_text_is_portable(path) {
        return;
    }

    let existing_path = match canonicalize_directory_without_links(path) {
        Ok(path) => path,
        Err(_) => {
            if retain_unavailable
                && matches!(
                    source,
                    ProjectRootCandidateSource::RestartLogProjectRoot
                        | ProjectRootCandidateSource::WindowsRegistryInstallDir
                )
                && !path.exists()
                && seen.insert(path_identity(path))
            {
                candidates.push(CandidateRecord {
                    path: path.to_path_buf(),
                    source,
                    has_project_data: false,
                    selectable: false,
                    trusted_for_automatic_selection,
                    allow_empty_project_data: false,
                });
            }
            return;
        }
    };

    let has_project_data = if trusted_for_automatic_selection {
        has_meaningful_project_data(&existing_path)
    } else {
        has_strong_project_data(&existing_path)
    };
    if !has_project_data {
        if retain_unavailable
            && matches!(
                source,
                ProjectRootCandidateSource::RestartLogProjectRoot
                    | ProjectRootCandidateSource::WindowsRegistryInstallDir
            )
            && seen.insert(path_identity(&existing_path))
        {
            candidates.push(CandidateRecord {
                path: existing_path,
                source,
                has_project_data: false,
                selectable: false,
                trusted_for_automatic_selection,
                allow_empty_project_data: false,
            });
        }
        return;
    }
    if !seen.insert(path_identity(&existing_path)) {
        return;
    }
    let selectable = validate_existing_writable_project_root(&existing_path).is_some();
    if !selectable && !retain_unavailable {
        return;
    }
    candidates.push(CandidateRecord {
        path: existing_path,
        source,
        has_project_data: true,
        selectable,
        trusted_for_automatic_selection,
        allow_empty_project_data: false,
    });
}

fn validate_existing_writable_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute()
        || path_is_filesystem_root(path)
        || !path_text_is_portable(path)
        || !path.is_dir()
    {
        return None;
    }
    let canonical = canonicalize_directory_without_links(path).ok()?;
    if path_is_filesystem_root(&canonical) || !path_text_is_portable(&canonical) {
        return None;
    }
    let identity = open_directory_without_links(&canonical).ok()?;
    if !can_write_directory(&canonical) || !path_refers_to_open_directory(&canonical, &identity) {
        return None;
    }
    Some(canonical)
}

fn validate_existing_writable_project_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute()
        || path_is_filesystem_root(path)
        || !path_text_is_portable(path)
        || !path.is_dir()
    {
        return None;
    }
    let root = canonicalize_directory_without_links(path).ok()?;
    if path_is_filesystem_root(&root) || !path_text_is_portable(&root) {
        return None;
    }
    let root_identity = open_directory_without_links(&root).ok()?;
    let data = root.join("data");
    let data_identity = open_directory_without_links(&data).ok()?;
    if !can_write_directory(&data)
        || !path_refers_to_open_directory(&root, &root_identity)
        || !path_refers_to_open_directory(&data, &data_identity)
    {
        return None;
    }
    let canonical_data = canonicalize_directory_without_links(&data).ok()?;
    (path_text_is_portable(&canonical_data)
        && canonical_data.starts_with(&root)
        && path_refers_to_open_directory(&root, &root_identity)
        && path_refers_to_open_directory(&canonical_data, &data_identity))
    .then_some(root)
}

fn validate_existing_project_root(path: &Path) -> Option<PathBuf> {
    let data = path.join("data");
    match open_directory_without_links(&data) {
        Ok(_) => validate_existing_writable_project_root(path),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            validate_existing_writable_root(path)
        }
        Err(_) => None,
    }
}

fn absolute_path(path: &Path) -> Result<PathBuf, String> {
    if path.is_absolute() && !path_is_filesystem_root(path) && path_text_is_portable(path) {
        return Ok(path.to_path_buf());
    }
    Err(format!(
        "project-root infrastructure path must be absolute and portable: {}",
        path.display()
    ))
}

fn prepare_primary_locator_path(path: &Path) -> Result<PathBuf, String> {
    let path = absolute_path(path)?;
    let parent = path.parent().ok_or_else(|| {
        format!(
            "project root locator has no parent directory: {}",
            path.display()
        )
    })?;
    let name = path
        .file_name()
        .ok_or_else(|| format!("project root locator has no filename: {}", path.display()))?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "failed to create project root locator directory {}: {error}",
            parent.display()
        )
    })?;
    let canonical_parent = resolve_infrastructure_parent(parent).map_err(|error| {
        format!(
            "failed to resolve project root locator directory {}: {error}",
            parent.display()
        )
    })?;
    if path_is_filesystem_root(&canonical_parent) || !path_text_is_portable(&canonical_parent) {
        return Err(format!(
            "project-root locator directory must be a non-root portable path: {}",
            canonical_parent.display()
        ));
    }
    Ok(canonical_parent.join(name))
}

fn can_write_directory(path: &Path) -> bool {
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

fn write_and_remove_owned_probe(probe: &Path) -> bool {
    write_and_remove_owned_probe_after_write(probe, || {})
}

fn write_and_remove_owned_probe_after_write(probe: &Path, after_write: impl FnOnce()) -> bool {
    let Some(parent_path) = probe.parent() else {
        return false;
    };
    let Ok(parent_directory) = open_directory_without_links(parent_path) else {
        return false;
    };
    let Ok(mut file) = OpenOptions::new().write(true).create_new(true).open(probe) else {
        return false;
    };
    let written = file.write_all(b"ok").is_ok();
    after_write();

    // A path-based remove must not delete a file that replaced our probe
    // between creation and cleanup. Re-open through the canonical parent and
    // compare the live path with the handle returned by create_new first.
    let still_owned = path_refers_to_open_directory(parent_path, &parent_directory)
        && path_refers_to_open_file(probe, &file);
    drop(file);
    if !still_owned {
        return false;
    }
    let removed = fs::remove_file(probe).is_ok();
    written && removed
}

fn path_refers_to_open_file(path: &Path, open_file: &fs::File) -> bool {
    (|| -> std::io::Result<bool> {
        let parent = canonicalize_directory_without_links(
            path.parent()
                .ok_or_else(|| std::io::Error::other("owned file has no parent"))?,
        )?;
        let name = path
            .file_name()
            .ok_or_else(|| std::io::Error::other("owned file has no filename"))?;
        let verification = open_regular_file_without_links(&parent.join(name))?;
        files_have_same_identity(open_file, &verification)
    })()
    .unwrap_or(false)
}

fn path_refers_to_open_directory(path: &Path, open_directory: &fs::File) -> bool {
    open_directory_without_links(path)
        .and_then(|verification| files_have_same_identity(open_directory, &verification))
        .unwrap_or(false)
}

fn has_meaningful_project_data(root: &Path) -> bool {
    let data = root.join("data");
    has_strong_project_data(root) || directory_contains_file(&data, MAX_MARKER_SCAN_ENTRIES)
}

fn has_strong_project_data(root: &Path) -> bool {
    let data = root.join("data");
    if open_directory_without_links(&data).is_err() {
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
        .any(|marker| is_regular_project_marker(root, marker))
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

fn is_regular_project_marker(root: &Path, marker: &str) -> bool {
    let mut cursor = root.join("data");
    let Ok(data_identity) = open_directory_without_links(&cursor) else {
        return false;
    };
    let mut directories = vec![(cursor.clone(), data_identity)];
    let mut components = marker.split('/').peekable();
    while let Some(component) = components.next() {
        cursor.push(component);
        if components.peek().is_some() {
            let Ok(identity) = open_directory_without_links(&cursor) else {
                return false;
            };
            directories.push((cursor.clone(), identity));
        } else {
            let Ok(file) = open_regular_file_without_links(&cursor) else {
                return false;
            };
            return directory_snapshots_are_current(&directories)
                && path_refers_to_open_file(&cursor, &file);
        }
    }
    false
}

fn directory_contains_file(path: &Path, max_entries: usize) -> bool {
    let Ok(root_identity) = open_directory_without_links(path) else {
        return false;
    };
    let mut pending = vec![(path.to_path_buf(), root_identity)];
    let mut visited = Vec::new();
    let mut scanned = 0;
    while let Some((directory, directory_identity)) = pending.pop() {
        let Ok(entries) = fs::read_dir(&directory) else {
            return false;
        };
        for entry in entries.flatten() {
            scanned += 1;
            if scanned > max_entries {
                return false;
            }
            let entry_path = entry.path();
            if !path_text_is_portable(&entry_path) {
                continue;
            }
            if let Ok(file) = open_regular_file_without_links(&entry_path) {
                let ignored = entry
                    .file_name()
                    .to_str()
                    .is_some_and(|name| matches!(name, ".gitkeep" | ".DS_Store"));
                if !ignored
                    && path_refers_to_open_directory(&directory, &directory_identity)
                    && directory_snapshots_are_current(&visited)
                    && path_refers_to_open_file(&entry_path, &file)
                {
                    return true;
                }
            } else if let Ok(identity) = open_directory_without_links(&entry_path) {
                pending.push((entry_path, identity));
            }
        }
        if !path_refers_to_open_directory(&directory, &directory_identity) {
            return false;
        }
        visited.push((directory, directory_identity));
    }
    false
}

fn directory_snapshots_are_current(directories: &[(PathBuf, fs::File)]) -> bool {
    directories
        .iter()
        .all(|(path, identity)| path_refers_to_open_directory(path, identity))
}

fn read_locator_state(locator_path: &Path) -> LocatorState {
    match fs::symlink_metadata(locator_path) {
        Ok(metadata) if metadata_is_link(&metadata) || !metadata.file_type().is_file() => {
            return LocatorState::Malformed;
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return LocatorState::AbsentOrEmpty;
        }
        Err(_) => return LocatorState::Malformed,
    }
    let resolved_path = match resolve_infrastructure_file_path(locator_path) {
        Ok(path) => path,
        Err(_) => return LocatorState::Malformed,
    };
    let Ok(content) =
        read_stable_regular_file_prefix(&resolved_path, MAX_PROJECT_ROOT_LOCATOR_BYTES + 1)
    else {
        return LocatorState::Malformed;
    };
    if content.len() as u64 > MAX_PROJECT_ROOT_LOCATOR_BYTES {
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
            .filter(|path| path.is_absolute() && path_text_is_portable(path));
        return LocatorState::UnsupportedVersion { version, path };
    }
    let Ok(locator) = serde_json::from_value::<ProjectRootLocator>(value) else {
        return LocatorState::Malformed;
    };
    let path = PathBuf::from(locator.project_root);
    if !path.is_absolute() || !path_text_is_portable(&path) {
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
fn read_valid_locator(locator_path: &Path) -> Option<PathBuf> {
    match read_locator_state(locator_path) {
        LocatorState::Available(path) => Some(path),
        LocatorState::AbsentOrEmpty
        | LocatorState::Malformed
        | LocatorState::Unavailable(_)
        | LocatorState::UnsupportedVersion { .. } => None,
    }
}

fn persist_locator_automatically(locator_path: &Path, project_root: &Path) -> Result<(), String> {
    persist_locator(locator_path, project_root, false)
}

fn persist_selected_locator(locator_path: &Path, project_root: &Path) -> Result<(), String> {
    persist_locator(locator_path, project_root, true)
}

fn migrate_legacy_locator(locator_path: &Path, legacy_root: &Path) -> Result<PathBuf, String> {
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
    let parent_directory = open_directory_without_links(parent).map_err(|error| {
        format!(
            "failed to bind project root locator directory {}: {error}",
            parent.display()
        )
    })?;
    let _lock = LocatorWriteLock::acquire(parent)?;
    if !path_refers_to_open_directory(parent, &parent_directory) {
        return Err(format!(
            "project root locator directory changed while acquiring its lock: {}",
            parent.display()
        ));
    }
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
    let write_result = (|| -> Result<(), String> {
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
        if !path_refers_to_open_directory(parent, &parent_directory)
            || !path_refers_to_open_file(&temp_path, &file)
        {
            return Err(format!(
                "project root locator path identity changed before publication: {}",
                locator_path.display()
            ));
        }

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
        atomic_replace_file(&temp_path, locator_path, parent, &parent_directory).map_err(
            |error| {
                format!(
                    "failed to atomically publish project root locator {}: {error}",
                    locator_path.display()
                )
            },
        )?;
        if !path_refers_to_open_directory(parent, &parent_directory)
            || !path_refers_to_open_file(locator_path, &file)
        {
            return Err(format!(
                "project root locator path identity changed during publication: {}",
                locator_path.display()
            ));
        }
        let _ = parent_directory.sync_all();
        Ok(())
    })();
    // On successful publication temp_path no longer names this handle. On
    // failure or early completion, remove it only while it still has the
    // identity created above, preserving any concurrent replacement.
    let remove_temp = path_refers_to_open_file(&temp_path, &file);
    drop(file);
    if remove_temp {
        let _ = fs::remove_file(&temp_path);
    }
    write_result
}

fn prepare_project_root_for_persistence(project_root: &Path) -> Result<PathBuf, String> {
    if !project_root.is_absolute() || !project_root.is_dir() {
        return Err(format!(
            "cannot persist an invalid project root: {}",
            project_root.display()
        ));
    }
    let project_root = canonicalize_directory_without_links(project_root).map_err(|error| {
        format!(
            "cannot resolve project root before persistence {}: {error}",
            project_root.display()
        )
    })?;
    if path_is_filesystem_root(&project_root) || !path_text_is_portable(&project_root) {
        return Err(format!(
            "cannot persist a non-portable project root: {}",
            project_root.display()
        ));
    }
    let project_root_identity = open_directory_without_links(&project_root).map_err(|error| {
        format!(
            "cannot bind project root before persistence {}: {error}",
            project_root.display()
        )
    })?;
    let data = project_root.join("data");
    fs::create_dir_all(&data).map_err(|error| {
        format!(
            "failed to prepare project data directory {} before persisting its locator: {error}",
            data.display()
        )
    })?;
    if !path_refers_to_open_directory(&project_root, &project_root_identity) {
        return Err(format!(
            "project root changed identity while preparing its data directory: {}",
            project_root.display()
        ));
    }
    let data_identity = open_directory_without_links(&data).map_err(|error| {
        format!(
            "cannot bind project data directory before persistence {}: {error}",
            data.display()
        )
    })?;
    let prepared = validate_existing_writable_project_root(&project_root).ok_or_else(|| {
        format!(
            "cannot persist a project root whose data directory is not writable: {}",
            project_root.display()
        )
    })?;
    if prepared != project_root
        || !path_refers_to_open_directory(&project_root, &project_root_identity)
        || !path_refers_to_open_directory(&data, &data_identity)
    {
        return Err(format!(
            "project root changed identity during persistence validation: {}",
            project_root.display()
        ));
    }
    Ok(prepared)
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
        if fs::symlink_metadata(&path)
            .ok()
            .is_some_and(|metadata| metadata_is_link(&metadata) || !metadata.file_type().is_file())
        {
            return Err(format!(
                "project root locator lock must be a regular non-link file: {}",
                path.display()
            ));
        }
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        options.custom_flags(libc::O_NOFOLLOW);
        #[cfg(windows)]
        options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
        let file = options.open(&path).map_err(|error| {
            format!(
                "failed to open project root locator lock {}: {error}",
                path.display()
            )
        })?;
        if fs::symlink_metadata(&path)
            .ok()
            .is_some_and(|metadata| metadata_is_link(&metadata) || !metadata.file_type().is_file())
        {
            return Err(format!(
                "project root locator lock changed to a non-regular or linked file: {}",
                path.display()
            ));
        }
        let verification = open_regular_file_without_links(&path).map_err(|error| {
            format!(
                "failed to verify project root locator lock {}: {error}",
                path.display()
            )
        })?;
        if !files_have_same_identity(&file, &verification).map_err(|error| {
            format!(
                "failed to compare project root locator lock identity {}: {error}",
                path.display()
            )
        })? {
            return Err(format!(
                "project root locator lock changed to a different file: {}",
                path.display()
            ));
        }
        lock_locator_file(&file).map_err(|error| {
            format!(
                "failed to acquire project root locator lock {}: {error}",
                path.display()
            )
        })?;
        Ok(Self { _file: file })
    }
}

#[cfg(unix)]
fn lock_locator_file(file: &fs::File) -> std::io::Result<()> {
    let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) };
    if result == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(windows)]
fn lock_locator_file(file: &fs::File) -> std::io::Result<()> {
    let mut overlapped = WindowsOverlapped {
        internal: 0,
        internal_high: 0,
        offset: 0,
        offset_high: 0,
        event: std::ptr::null_mut(),
    };
    let result = unsafe {
        LockFileEx(
            file.as_raw_handle().cast(),
            LOCKFILE_EXCLUSIVE_LOCK,
            0,
            1,
            0,
            &mut overlapped,
        )
    };
    if result == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(unix)]
fn atomic_replace_file(
    source: &Path,
    destination: &Path,
    parent_path: &Path,
    parent_directory: &fs::File,
) -> std::io::Result<()> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    if source.parent() != Some(parent_path) || destination.parent() != Some(parent_path) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "atomic replacement paths must share the bound parent directory",
        ));
    }
    let source_name = CString::new(
        source
            .file_name()
            .ok_or_else(|| std::io::Error::other("replacement source has no filename"))?
            .as_bytes(),
    )
    .map_err(|_| std::io::Error::other("replacement source contains NUL"))?;
    let destination_name = CString::new(
        destination
            .file_name()
            .ok_or_else(|| std::io::Error::other("replacement destination has no filename"))?
            .as_bytes(),
    )
    .map_err(|_| std::io::Error::other("replacement destination contains NUL"))?;
    let result = unsafe {
        libc::renameat(
            parent_directory.as_raw_fd(),
            source_name.as_ptr(),
            parent_directory.as_raw_fd(),
            destination_name.as_ptr(),
        )
    };
    if result == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(all(not(unix), not(windows)))]
fn atomic_replace_file(
    _source: &Path,
    _destination: &Path,
    _parent_path: &Path,
    _parent_directory: &fs::File,
) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "atomic file replacement is unavailable on this platform",
    ))
}

#[cfg(windows)]
fn atomic_replace_file(
    source: &Path,
    destination: &Path,
    parent_path: &Path,
    parent_directory: &fs::File,
) -> std::io::Result<()> {
    if source.parent() != Some(parent_path) || destination.parent() != Some(parent_path) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "atomic replacement paths must share the bound parent directory",
        ));
    }
    if !path_refers_to_open_directory(parent_path, parent_directory) {
        return Err(std::io::Error::other(
            "atomic replacement parent directory changed identity",
        ));
    }
    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    let result = unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if result == 0 {
        Err(std::io::Error::last_os_error())
    } else if !path_refers_to_open_directory(parent_path, parent_directory) {
        Err(std::io::Error::other(
            "atomic replacement parent directory changed identity",
        ))
    } else {
        Ok(())
    }
}

fn restart_log_candidates(log_path: &Path) -> Vec<(PathBuf, ProjectRootCandidateSource)> {
    let Ok(metadata) = fs::symlink_metadata(log_path) else {
        return Vec::new();
    };
    if metadata_is_link(&metadata) || !metadata.file_type().is_file() {
        return Vec::new();
    }
    let Ok(resolved_path) = resolve_infrastructure_file_path(log_path) else {
        return Vec::new();
    };
    let Ok((start, bytes)) = read_stable_regular_file_tail(&resolved_path, MAX_RESTART_LOG_BYTES)
    else {
        return Vec::new();
    };
    let mut content = String::from_utf8_lossy(&bytes).as_ref().to_string();
    if start > 0 {
        let Some(first_newline) = content.find('\n') else {
            return Vec::new();
        };
        content.drain(..=first_newline);
    }
    let mut candidates = Vec::new();
    for line in content.lines().rev() {
        if candidates.len() >= MAX_RESTART_LOG_CANDIDATES {
            break;
        }
        let Some((_, desktop_event)) = line.split_once(" component=desktop ") else {
            continue;
        };
        let Some(resolved_fields) = desktop_event.strip_prefix("setup resolved ") else {
            continue;
        };
        if let Some(project_root) = setup_log_field(
            resolved_fields,
            "project_root",
            &["app_root", "frontend_dist", "bridge_port", "url"],
        ) {
            candidates.push((
                PathBuf::from(project_root),
                ProjectRootCandidateSource::RestartLogProjectRoot,
            ));
        }
        if let Some(app_root) = setup_log_field(
            resolved_fields,
            "app_root",
            &["frontend_dist", "bridge_port", "url"],
        ) {
            candidates.push((
                PathBuf::from(app_root),
                ProjectRootCandidateSource::RestartLogAppRoot,
            ));
        }
    }
    candidates
}

fn resolve_infrastructure_file_path(path: &Path) -> std::io::Result<PathBuf> {
    let parent = path
        .parent()
        .ok_or_else(|| std::io::Error::other("infrastructure file has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| std::io::Error::other("infrastructure file has no filename"))?;
    Ok(resolve_infrastructure_parent(parent)?.join(name))
}

fn resolve_infrastructure_parent(parent: &Path) -> std::io::Result<PathBuf> {
    let resolved_parent = parent.canonicalize()?;
    if path_is_filesystem_root(&resolved_parent) || !path_text_is_portable(&resolved_parent) {
        return Err(std::io::Error::other(
            "infrastructure file parent resolved to an invalid path",
        ));
    }
    let parent_identity = open_directory_without_links(&resolved_parent)?;
    let verification_parent = parent.canonicalize()?;
    let verification_identity = open_directory_without_links(&verification_parent)?;
    if verification_parent != resolved_parent
        || !files_have_same_identity(&parent_identity, &verification_identity)?
    {
        return Err(std::io::Error::other(
            "infrastructure file parent changed while resolving its path",
        ));
    }
    Ok(resolved_parent)
}

fn read_stable_regular_file_prefix(path: &Path, limit: u64) -> std::io::Result<Vec<u8>> {
    let mut file = open_regular_file_without_links(path)?;
    let mut content = Vec::new();
    (&mut file).take(limit).read_to_end(&mut content)?;
    let mut verification = open_regular_file_without_links(path)?;
    if !files_have_same_identity(&file, &verification)? {
        return Err(std::io::Error::other(
            "infrastructure file changed while reading",
        ));
    }
    let mut verification_content = Vec::new();
    (&mut verification)
        .take(limit)
        .read_to_end(&mut verification_content)?;
    if verification_content != content {
        return Err(std::io::Error::other(
            "infrastructure file contents changed while reading",
        ));
    }
    Ok(content)
}

fn read_stable_regular_file_tail(path: &Path, limit: usize) -> std::io::Result<(u64, Vec<u8>)> {
    fn read_tail(file: &mut fs::File, limit: usize) -> std::io::Result<(u64, Vec<u8>)> {
        let length = file.metadata()?.len();
        let start = length.saturating_sub(limit as u64);
        file.seek(SeekFrom::Start(start))?;
        let mut bytes = Vec::with_capacity((length - start) as usize);
        file.take(limit as u64).read_to_end(&mut bytes)?;
        Ok((start, bytes))
    }

    let mut file = open_regular_file_without_links(path)?;
    let snapshot = read_tail(&mut file, limit)?;
    let mut verification = open_regular_file_without_links(path)?;
    if !files_have_same_identity(&file, &verification)? {
        return Err(std::io::Error::other(
            "infrastructure file changed while reading",
        ));
    }
    let verification_snapshot = read_tail(&mut verification, limit)?;
    if verification_snapshot != snapshot {
        return Err(std::io::Error::other(
            "infrastructure file contents changed while reading",
        ));
    }
    Ok(snapshot)
}

fn setup_log_field(line: &str, field: &str, following_fields: &[&str]) -> Option<String> {
    let marker = format!(" {field}=");
    let start = line.find(&marker)? + marker.len();
    let tail = &line[start..];
    let end = following_fields
        .iter()
        .filter_map(|following| tail.find(&format!(" {following}=")))
        .min()
        .unwrap_or(tail.len());
    let value = &tail[..end];
    if value.is_empty()
        || value.trim() != value
        || value
            .chars()
            .any(|character| character <= '\u{1f}' || character == '\u{7f}')
    {
        return None;
    }
    Some(value.to_string())
}

fn deduplicate_paths(paths: impl IntoIterator<Item = PathBuf>) -> Vec<PathBuf> {
    let mut seen = HashSet::new();
    paths
        .into_iter()
        .filter(|path| seen.insert(path_identity(path)))
        .collect()
}

fn path_identity(path: &Path) -> String {
    let canonical = canonicalize_directory_without_links(path)
        .or_else(|_| canonicalize_regular_file_without_links(path))
        .unwrap_or_else(|_| path.to_path_buf());
    let value = display_path(&canonical);
    #[cfg(windows)]
    {
        return value.to_lowercase();
    }
    #[cfg(not(windows))]
    value
}

fn display_path(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Barrier,
    };
    use std::thread;

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
    fn empty_current_environment_override_does_not_fall_back_to_legacy() {
        let root = temp_dir("empty-current-env");
        let legacy_root = root.join("legacy-root");
        let selected = preferred_environment_root(
            Some(OsString::new()),
            Some(legacy_root.clone().into_os_string()),
        )
        .unwrap();

        assert!(selected.0.as_os_str().is_empty());
        let mut resolve_options = options(&root);
        resolve_options.explicit_root = Some(selected);
        let error = match resolve(resolve_options) {
            Ok(_) => panic!("empty current override must not resolve"),
            Err(error) => error,
        };
        assert!(error.contains("explicit project root contains non-portable characters"));
        assert!(!legacy_root.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn infrastructure_paths_never_rebase_against_process_cwd() {
        let error = absolute_path(Path::new("relative/locator.json")).unwrap_err();

        assert!(error.contains("must be absolute"));
    }

    #[cfg(unix)]
    #[test]
    fn primary_locator_parent_alias_is_pinned_before_persistence_and_selection() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("locator-parent-alias");
        let real_config = root.join("real-config");
        let other_config = root.join("other-config");
        fs::create_dir_all(&real_config).unwrap();
        fs::create_dir_all(&other_config).unwrap();
        let alias = root.join("config-alias");
        symlink(&real_config, &alias).unwrap();

        let mut resolve_options = options(&root);
        resolve_options.locator_path = alias.join(PROJECT_ROOT_LOCATOR_FILE);
        let resolved = resolve(resolve_options).unwrap();
        let real_locator = real_config.join(PROJECT_ROOT_LOCATOR_FILE);

        assert_eq!(
            resolved.controller.status().locator_path,
            display_path(&real_locator)
        );
        assert!(real_locator.is_file());

        fs::remove_file(&alias).unwrap();
        symlink(&other_config, &alias).unwrap();
        let selected = display_path(&resolved.path);
        resolved.controller.select(&selected).unwrap();

        assert!(real_locator.is_file());
        assert!(!other_config.join(PROJECT_ROOT_LOCATOR_FILE).exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn filesystem_root_cannot_become_a_project_or_infrastructure_root() {
        let current = std::env::current_dir().unwrap();
        let filesystem_root = current.ancestors().last().unwrap();

        assert!(filesystem_root.is_absolute());
        assert!(prepare_explicit_root(filesystem_root)
            .unwrap_err()
            .contains("filesystem root"));
        assert!(absolute_path(filesystem_root)
            .unwrap_err()
            .contains("absolute and portable"));
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

    #[cfg(unix)]
    #[test]
    fn explicit_override_rejects_alias_to_nonportable_canonical_root() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("explicit-nonportable-canonical");
        let target = root.join("target:with-colon");
        fs::create_dir_all(target.join("data")).unwrap();
        let alias = root.join("portable-alias");
        symlink(&target, &alias).unwrap();
        let mut resolve_options = options(&root);
        resolve_options.explicit_root =
            Some((alias, ProjectRootCandidateSource::EnvironmentOverride));

        let error = resolve(resolve_options).err().unwrap();

        assert!(error.contains("not a writable directory"));
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn explicit_override_rejects_symlinked_data_directory() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("explicit-data-symlink");
        let explicit = root.join("explicit-root");
        let external = root.join("external-data");
        fs::create_dir_all(&explicit).unwrap();
        fs::create_dir_all(&external).unwrap();
        fs::write(external.join("keep.txt"), "keep").unwrap();
        symlink(&external, explicit.join("data")).unwrap();
        let mut options = options(&root);
        options.explicit_root = Some((explicit, ProjectRootCandidateSource::EnvironmentOverride));

        let error = match resolve(options) {
            Ok(_) => panic!("symlinked data directory was accepted"),
            Err(error) => error,
        };

        assert!(error.contains("not a writable directory"));
        assert_eq!(
            fs::read_to_string(external.join("keep.txt")).unwrap(),
            "keep"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn explicit_override_rejects_broken_data_symlink() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("explicit-broken-data-symlink");
        let explicit = root.join("explicit-root");
        fs::create_dir_all(&explicit).unwrap();
        symlink(root.join("missing-data"), explicit.join("data")).unwrap();
        let mut options = options(&root);
        options.explicit_root = Some((explicit, ProjectRootCandidateSource::EnvironmentOverride));

        let error = match resolve(options) {
            Ok(_) => panic!("broken data symlink was accepted"),
            Err(error) => error,
        };

        assert!(error.contains("not a writable directory"));
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
    fn explicit_override_rejects_nonportable_path_text_before_creating_it() {
        let root = temp_dir("nonportable-explicit");
        let explicit = root.join("bad\nproject");
        let mut options = options(&root);
        options.explicit_root = Some((
            explicit.clone(),
            ProjectRootCandidateSource::EnvironmentOverride,
        ));

        let error = resolve(options).err().unwrap();

        assert!(error.contains("non-portable characters"));
        assert!(!explicit.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn explicit_override_rejects_lexical_aliases_before_creating_it() {
        let root = temp_dir("aliased-explicit");
        for suffix in ["./aliased-project", "nested//aliased-project"] {
            let explicit = PathBuf::from(format!("{}/{suffix}", root.display()));
            let mut options = options(&root);
            options.explicit_root = Some((
                explicit.clone(),
                ProjectRootCandidateSource::EnvironmentOverride,
            ));

            let error = resolve(options).err().unwrap();

            assert!(error.contains("non-portable characters"));
            assert!(!explicit.exists());
        }
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn project_root_contract_rejects_non_utf8_path_text() {
        use std::os::unix::ffi::OsStringExt;

        let path = PathBuf::from(OsString::from_vec(vec![b'/', b't', b'm', b'p', b'/', 0xff]));

        assert!(!path_text_is_portable(&path));
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
    fn locator_with_nonportable_project_path_is_malformed_even_when_directory_exists() {
        let root = temp_dir("nonportable-locator");
        let selected = data_root(&root, "bad\nproject");
        let locator = root.join("config").join(PROJECT_ROOT_LOCATOR_FILE);
        fs::create_dir_all(locator.parent().unwrap()).unwrap();
        fs::write(
            &locator,
            serde_json::to_vec(&serde_json::json!({
                "version": PROJECT_ROOT_LOCATOR_VERSION,
                "projectRoot": display_path(&selected),
            }))
            .unwrap(),
        )
        .unwrap();

        assert!(matches!(
            read_locator_state(&locator),
            LocatorState::Malformed
        ));
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

    #[cfg(unix)]
    #[test]
    fn symlinked_locator_is_malformed_instead_of_authoritative() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("symlinked-locator");
        let project = data_root(&root, "project");
        let target = root.join("external-locator.json");
        let locator = root.join("config").join(PROJECT_ROOT_LOCATOR_FILE);
        fs::create_dir_all(locator.parent().unwrap()).unwrap();
        fs::write(
            &target,
            serde_json::to_vec_pretty(&ProjectRootLocator {
                version: PROJECT_ROOT_LOCATOR_VERSION,
                project_root: display_path(&project),
            })
            .unwrap(),
        )
        .unwrap();
        symlink(&target, &locator).unwrap();

        assert!(matches!(
            read_locator_state(&locator),
            LocatorState::Malformed
        ));
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
    fn restart_log_parser_ignores_control_character_paths() {
        let root = temp_dir("restart-log-control");
        let log = root.join("shinsekai-restart-debug.log");
        fs::write(
            &log,
            "ts=1 pid=1 component=desktop setup resolved source_root=/source project_root=/bad\troot app_root=/app frontend_dist=/dist bridge_port=8787 url=x\n",
        )
        .unwrap();

        let candidates = restart_log_candidates(&log);

        assert!(candidates
            .iter()
            .all(|(path, _)| path != Path::new("/bad\troot")));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn restart_log_parser_does_not_trim_path_identity() {
        let line = " setup resolved project_root=/tmp/project  app_root=/app frontend_dist=/dist";

        assert_eq!(
            setup_log_field(line, "project_root", &["app_root", "frontend_dist"]),
            None
        );
    }

    #[cfg(unix)]
    #[test]
    fn restart_log_parser_ignores_symlinked_log_file() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("symlinked-restart-log");
        let project = data_root(&root, "project");
        let target = root.join("external.log");
        let link = root.join("restart.log");
        fs::write(
            &target,
            format!(
                "ts=1 component=desktop setup resolved project_root={} app_root=/app frontend_dist=/dist\n",
                project.display()
            ),
        )
        .unwrap();
        symlink(&target, &link).unwrap();

        assert!(restart_log_candidates(&link).is_empty());
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
        let current_path = options.current_app_data_project_root.clone();

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
            root.join("current-data")
                .join("project")
                .canonicalize()
                .unwrap()
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
        let current_path = options.current_app_data_project_root.clone();

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
        let current_path = resolve_options.current_app_data_project_root.clone();
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

    #[cfg(unix)]
    #[test]
    fn symlinked_config_marker_is_not_recognized_as_project_data() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("symlinked-config-marker");
        let candidate = root.join("candidate");
        let external_config = root.join("external-config");
        fs::create_dir_all(candidate.join("data")).unwrap();
        fs::create_dir_all(&external_config).unwrap();
        fs::write(external_config.join("api.yaml"), "provider: external").unwrap();
        symlink(&external_config, candidate.join("data/config")).unwrap();

        assert!(!has_strong_project_data(&candidate));
        assert!(!has_meaningful_project_data(&candidate));
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
    fn write_probe_preserves_a_replacement_created_before_cleanup() {
        let root = temp_dir("probe-replacement");
        let probe = root.join("replaced-probe");

        assert!(!write_and_remove_owned_probe_after_write(&probe, || {
            fs::remove_file(&probe).unwrap();
            fs::write(&probe, b"replacement").unwrap();
        }));
        assert_eq!(fs::read(&probe).unwrap(), b"replacement");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn write_probe_rejects_a_replacement_parent_before_cleanup() {
        let root = temp_dir("probe-parent-replacement");
        let candidate = root.join("candidate");
        let preserved_candidate = root.join("preserved-candidate");
        fs::create_dir_all(&candidate).unwrap();
        let probe = candidate.join("write-probe");

        assert!(!write_and_remove_owned_probe_after_write(&probe, || {
            fs::rename(&candidate, &preserved_candidate).unwrap();
            fs::create_dir_all(&candidate).unwrap();
            fs::write(&probe, b"peer").unwrap();
        }));

        assert_eq!(fs::read(&probe).unwrap(), b"peer");
        assert_eq!(
            fs::read(preserved_candidate.join("write-probe")).unwrap(),
            b"ok"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn atomic_locator_replace_stays_bound_to_the_open_parent_directory() {
        let root = temp_dir("locator-parent-binding");
        let parent = root.join("config");
        let preserved_parent = root.join("preserved-config");
        fs::create_dir_all(&parent).unwrap();
        let source = parent.join("locator.tmp");
        let destination = parent.join(PROJECT_ROOT_LOCATOR_FILE);
        fs::write(&source, b"new locator").unwrap();
        fs::write(&destination, b"old locator").unwrap();
        let parent_directory = open_directory_without_links(&parent).unwrap();

        fs::rename(&parent, &preserved_parent).unwrap();
        fs::create_dir_all(&parent).unwrap();
        fs::write(&source, b"peer temp").unwrap();
        fs::write(&destination, b"peer locator").unwrap();

        atomic_replace_file(&source, &destination, &parent, &parent_directory).unwrap();

        assert_eq!(fs::read(&source).unwrap(), b"peer temp");
        assert_eq!(fs::read(&destination).unwrap(), b"peer locator");
        assert!(!preserved_parent.join("locator.tmp").exists());
        assert_eq!(
            fs::read(preserved_parent.join(PROJECT_ROOT_LOCATOR_FILE)).unwrap(),
            b"new locator"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn fresh_production_root_uses_app_data_and_precreates_data_directory() {
        let root = temp_dir("fresh-data-directory");
        let options = options(&root);
        let app_root = options.app_root.clone();
        let app_data_root = options.current_app_data_project_root.clone();

        let resolved = resolve(options).unwrap();

        assert_eq!(resolved.path, app_data_root.canonicalize().unwrap());
        assert!(app_data_root.join("data").is_dir());
        assert!(!app_root.join("data").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn incidental_install_data_does_not_make_the_installation_a_project_root() {
        let root = temp_dir("incidental-install-data");
        let options = options(&root);
        let app_root = options.app_root.clone();
        let app_data_root = options.current_app_data_project_root.clone();
        fs::create_dir_all(app_root.join("data")).unwrap();
        fs::write(app_root.join("data").join("packaged-schema.json"), b"{}").unwrap();

        let resolved = resolve(options).unwrap();

        assert_eq!(resolved.path, app_data_root.canonicalize().unwrap());
        assert_eq!(
            fs::read(app_root.join("data").join("packaged-schema.json")).unwrap(),
            b"{}"
        );
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
            root.join("current-data")
                .join("project")
                .canonicalize()
                .unwrap()
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

    #[cfg(unix)]
    #[test]
    fn locator_lock_does_not_follow_a_symbolic_link() {
        use std::os::unix::fs::symlink;

        let root = temp_dir("symlinked-locator-lock");
        let parent = root.join("config");
        fs::create_dir_all(&parent).unwrap();
        let unrelated = root.join("unrelated.txt");
        fs::write(&unrelated, "keep").unwrap();
        let lock_path = parent.join(format!(".{PROJECT_ROOT_LOCATOR_FILE}.lock"));
        symlink(&unrelated, &lock_path).unwrap();

        let error = LocatorWriteLock::acquire(&parent).err().unwrap();

        assert!(error.contains("regular non-link file"));
        assert_eq!(fs::read_to_string(unrelated).unwrap(), "keep");
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
}
