use std::{
    collections::HashSet,
    ffi::OsString,
    path::{Path, PathBuf},
    sync::Mutex,
};

use serde::Serialize;

mod locator;
mod platform;
mod probe;
mod restart_log;
#[cfg(test)]
mod tests;

use locator::{
    migrate_legacy_locator, persist_locator_automatically, persist_selected_locator,
    read_locator_state, BlockingLocator, LocatorState,
};
use platform::{absolute_path, deduplicate_paths, display_path, path_identity};
pub(crate) use platform::windows_legacy_install_dir_hints;
use probe::{
    has_meaningful_project_data, has_strong_project_data, prepare_app_root, prepare_current_root,
    prepare_explicit_root, validate_existing_project_root, validate_existing_writable_project_root,
};
use restart_log::restart_log_candidates;

pub(crate) const CURRENT_APP_IDENTIFIER: &str = "studio.shinsekai";
pub(crate) const LEGACY_APP_IDENTIFIER: &str = "icu.end0rph1n.shinsekai";
pub(crate) const PROJECT_ROOT_LOCATOR_FILE: &str = "project-root.json";
pub(crate) const PORTABLE_ROOT_MARKER_FILE: &str = ".shinsekai-portable";

const MAX_RECOVERY_CANDIDATES: usize = 40;

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

    if options.app_root.join(PORTABLE_ROOT_MARKER_FILE).is_file() {
        let path = prepare_app_root(&options.app_root).ok_or_else(|| {
            format!(
                "portable bundle directory is not writable (please extract to a writable path such as D:\\Shinsekai): {}",
                options.app_root.display()
            )
        })?;
        let candidate = CandidateRecord {
            has_project_data: has_meaningful_project_data(&path),
            path: path.clone(),
            source: ProjectRootCandidateSource::CurrentAppRoot,
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
        true,
    );
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

fn add_data_candidate(
    candidates: &mut Vec<CandidateRecord>,
    seen: &mut HashSet<String>,
    path: &Path,
    source: ProjectRootCandidateSource,
    trusted_for_automatic_selection: bool,
    retain_unavailable: bool,
) {
    if !path.is_absolute() {
        return;
    }

    let Some(existing_path) = path
        .is_dir()
        .then(|| path.canonicalize().unwrap_or_else(|_| path.to_path_buf()))
    else {
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
