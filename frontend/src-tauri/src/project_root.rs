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

#[cfg(windows)]
use std::os::windows::ffi::{OsStrExt, OsStringExt};
#[cfg(windows)]
use std::os::windows::io::AsRawHandle;

#[cfg(unix)]
use std::os::fd::AsRawFd;

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
}

pub(crate) struct ProjectRootController {
    locator_path: PathBuf,
    candidates: Vec<CandidateRecord>,
    selection_allowed: bool,
    status: Mutex<ProjectRootStatus>,
}

impl ProjectRootController {
    pub(crate) fn status(&self) -> ProjectRootStatus {
        self.status
            .lock()
            .map(|status| status.clone())
            .unwrap_or_else(|poisoned| poisoned.into_inner().clone())
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
            .find(|candidate| {
                candidate.selectable && path_identity(&candidate.path) == path_identity(&normalized)
            })
            .ok_or_else(|| {
                "project root selection was not one of the candidates returned by the resolver"
                    .to_string()
            })?;

        persist_selected_locator(&self.locator_path, &selected.path)?;

        let mut status = self
            .status
            .lock()
            .map_err(|_| "project root status lock is poisoned".to_string())?;
        status.current_path = display_path(&selected.path);
        status.conflict = false;
        status.requires_selection = false;
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
    nonempty_os_string(shinsekai)
        .or_else(|| nonempty_os_string(easyai))
        .map(|value| {
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
    // Tauri WiX 2.0/2.1 used Cargo's first author as manufacturer and stored
    // its named InstallDir at this per-user product key. Registry content is
    // only a hint: the resolver requires strong data markers and explicit UI
    // confirmation before it can become authoritative.
    const LEGACY_PRODUCT_KEYS: &[&str] = &["Software\\Shinsekai Contributors\\Shinsekai"];
    LEGACY_PRODUCT_KEYS
        .iter()
        .filter_map(|key| read_current_user_registry_string(key, "InstallDir"))
        .filter(|value| {
            !value.is_empty()
                && !value
                    .to_string_lossy()
                    .chars()
                    .any(|character| matches!(character, '\0' | '\r' | '\n'))
        })
        .map(|value| {
            (
                PathBuf::from(value),
                ProjectRootCandidateSource::WindowsRegistryInstallDir,
            )
        })
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

fn nonempty_os_string(value: Option<OsString>) -> Option<OsString> {
    value.filter(|value| !value.is_empty())
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
        };
        return Ok(resolution(
            path,
            locator_path,
            vec![candidate],
            false,
            false,
        ));
    }

    let locator_read_paths = deduplicate_paths(
        std::iter::once(locator_path.clone()).chain(options.locator_read_paths.iter().cloned()),
    );
    let mut blocking_locator = None;
    for candidate_locator in locator_read_paths {
        match read_locator_state(&candidate_locator) {
            LocatorState::Available(path) => {
                if candidate_locator != locator_path {
                    // A locator stored under the former application identifier remains
                    // authoritative. Migrating it is best-effort because failure must not
                    // make an otherwise valid user choice unusable.
                    let _ = persist_locator_automatically(&locator_path, &path);
                }
                let candidate = CandidateRecord {
                    has_project_data: has_meaningful_project_data(&path),
                    path: path.clone(),
                    source: ProjectRootCandidateSource::PersistedLocator,
                    selectable: true,
                    trusted_for_automatic_selection: true,
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
    add_data_candidate(
        &mut data_candidates,
        &mut seen,
        &options.app_root,
        if options.development_source && options.app_root == options.source_root {
            ProjectRootCandidateSource::DevelopmentSource
        } else {
            ProjectRootCandidateSource::CurrentAppRoot
        },
        true,
    );
    add_data_candidate(
        &mut data_candidates,
        &mut seen,
        &options.current_app_data_project_root,
        ProjectRootCandidateSource::CurrentAppData,
        true,
    );
    for path in &options.legacy_app_data_project_roots {
        add_data_candidate(
            &mut data_candidates,
            &mut seen,
            path,
            ProjectRootCandidateSource::LegacyAppData,
            true,
        );
    }
    for log_path in &options.restart_log_paths {
        for (path, source) in restart_log_candidates(log_path) {
            if data_candidates.len() >= MAX_RECOVERY_CANDIDATES {
                break;
            }
            add_data_candidate(&mut data_candidates, &mut seen, &path, source, false);
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
        add_data_candidate(&mut data_candidates, &mut seen, path, *source, false);
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

    if data_candidates.len() == 1 && data_candidates[0].trusted_for_automatic_selection {
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
            },
        );
    } else if let Some(index) = candidates
        .iter()
        .position(|candidate| candidate.path == current_path)
    {
        candidates.swap(0, index);
        candidates[0].selectable = true;
        candidates[0].trusted_for_automatic_selection = true;
        if matches!(
            candidates[0].source,
            ProjectRootCandidateSource::RestartLogProjectRoot
                | ProjectRootCandidateSource::RestartLogAppRoot
                | ProjectRootCandidateSource::WindowsRegistryInstallDir
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

fn prepare_explicit_root(path: &Path) -> Result<PathBuf, String> {
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

fn prepare_current_root(
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

fn prepare_app_root(app_root: &Path) -> Option<PathBuf> {
    if app_root.join("data").is_dir() {
        return validate_existing_writable_project_root(app_root);
    }
    let root = validate_existing_writable_root(app_root)?;
    fs::create_dir_all(root.join("data")).ok()?;
    can_write_directory(&root.join("data")).then_some(root)
}

fn add_data_candidate(
    candidates: &mut Vec<CandidateRecord>,
    seen: &mut HashSet<String>,
    path: &Path,
    source: ProjectRootCandidateSource,
    trusted_for_automatic_selection: bool,
) {
    let Some(path) = validate_existing_writable_project_root(path) else {
        return;
    };
    let has_project_data = if trusted_for_automatic_selection {
        has_meaningful_project_data(&path)
    } else {
        has_strong_project_data(&path)
    };
    if !has_project_data || !seen.insert(path_identity(&path)) {
        return;
    }
    candidates.push(CandidateRecord {
        path,
        source,
        has_project_data: true,
        selectable: true,
        trusted_for_automatic_selection,
    });
}

fn validate_existing_writable_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() || !path.is_dir() || !can_write_directory(path) {
        return None;
    }
    path.canonicalize().ok()
}

fn validate_existing_writable_project_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() || !path.is_dir() {
        return None;
    }
    let data = path.join("data");
    if !data.is_dir() || !can_write_directory(&data) {
        return None;
    }
    path.canonicalize().ok()
}

fn validate_existing_project_root(path: &Path) -> Option<PathBuf> {
    if path.join("data").is_dir() {
        validate_existing_writable_project_root(path)
    } else {
        validate_existing_writable_root(path)
    }
}

fn absolute_path(path: &Path) -> Result<PathBuf, String> {
    if path.is_absolute() {
        return Ok(path.to_path_buf());
    }
    std::env::current_dir()
        .map(|cwd| cwd.join(path))
        .map_err(|error| {
            format!(
                "failed to resolve absolute path {}: {error}",
                path.display()
            )
        })
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
    let Ok(mut file) = OpenOptions::new().write(true).create_new(true).open(probe) else {
        return false;
    };
    let written = file.write_all(b"ok").is_ok();
    drop(file);
    let removed = fs::remove_file(probe).is_ok();
    written && removed
}

fn has_meaningful_project_data(root: &Path) -> bool {
    let data = root.join("data");
    has_strong_project_data(root) || directory_contains_file(&data, MAX_MARKER_SCAN_ENTRIES)
}

fn has_strong_project_data(root: &Path) -> bool {
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

fn read_locator_state(locator_path: &Path) -> LocatorState {
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
    validate_existing_project_root(&path)
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

fn persist_locator(
    locator_path: &Path,
    project_root: &Path,
    replace_unavailable: bool,
) -> Result<(), String> {
    let project_root = validate_existing_project_root(project_root).ok_or_else(|| {
        format!(
            "cannot persist invalid or unwritable project root: {}",
            project_root.display()
        )
    })?;
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
        atomic_replace_file(&temp_path, locator_path).map_err(|error| {
            format!(
                "failed to atomically publish project root locator {}: {error}",
                locator_path.display()
            )
        })?;
        if let Ok(directory) = fs::File::open(parent) {
            let _ = directory.sync_all();
        }
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

#[cfg(not(windows))]
fn atomic_replace_file(source: &Path, destination: &Path) -> std::io::Result<()> {
    fs::rename(source, destination)
}

#[cfg(windows)]
fn atomic_replace_file(source: &Path, destination: &Path) -> std::io::Result<()> {
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
    } else {
        Ok(())
    }
}

fn restart_log_candidates(log_path: &Path) -> Vec<(PathBuf, ProjectRootCandidateSource)> {
    let Ok(mut file) = fs::File::open(log_path) else {
        return Vec::new();
    };
    let Ok(length) = file.metadata().map(|metadata| metadata.len()) else {
        return Vec::new();
    };
    let start = length.saturating_sub(MAX_RESTART_LOG_BYTES as u64);
    if file.seek(SeekFrom::Start(start)).is_err() {
        return Vec::new();
    }
    let mut bytes = Vec::with_capacity((length - start) as usize);
    if file
        .take(MAX_RESTART_LOG_BYTES as u64)
        .read_to_end(&mut bytes)
        .is_err()
    {
        return Vec::new();
    }
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
        if !line.contains("setup resolved ") {
            continue;
        }
        if let Some(project_root) = setup_log_field(
            line,
            "project_root",
            &["app_root", "frontend_dist", "bridge_port", "url"],
        ) {
            candidates.push((
                PathBuf::from(project_root),
                ProjectRootCandidateSource::RestartLogProjectRoot,
            ));
        }
        if let Some(app_root) =
            setup_log_field(line, "app_root", &["frontend_dist", "bridge_port", "url"])
        {
            candidates.push((
                PathBuf::from(app_root),
                ProjectRootCandidateSource::RestartLogAppRoot,
            ));
        }
    }
    candidates
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
    let raw_value = &tail[..end];
    if raw_value
        .chars()
        .any(|character| matches!(character, '\0' | '\r' | '\n'))
    {
        return None;
    }
    let value = raw_value.trim_matches([' ', '\t']);
    (!value.is_empty()
        && !value
            .chars()
            .any(|character| matches!(character, '\0' | '\r' | '\n')))
    .then(|| value.to_string())
}

fn deduplicate_paths(paths: impl IntoIterator<Item = PathBuf>) -> Vec<PathBuf> {
    let mut seen = HashSet::new();
    paths
        .into_iter()
        .filter(|path| seen.insert(path_identity(path)))
        .collect()
}

fn path_identity(path: &Path) -> String {
    let canonical = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
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
    fn missing_log_candidates_are_ignored() {
        let root = temp_dir("missing-candidate");
        let log = root.join("restart.log");
        fs::write(
            &log,
            "ts=1 component=desktop setup resolved source_root=/x project_root=/missing/user-data app_root=/missing/app frontend_dist=/x bridge_port=1",
        )
        .unwrap();
        let mut options = options(&root);
        options.restart_log_paths.push(log);

        let resolved = resolve(options).unwrap();

        assert_eq!(
            resolved.path,
            root.join("current-app").canonicalize().unwrap()
        );
        assert!(!resolved.controller.status().conflict);
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
    fn unwritable_data_candidate_is_ignored() {
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

        let resolved = resolve(options).unwrap();

        assert_eq!(
            resolved.path,
            root.join("current-app").canonicalize().unwrap()
        );
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
}
