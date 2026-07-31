use std::{
    env, fs,
    io::Read,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde::Serialize;

use crate::{
    path_contract::{
        canonicalize_directory_following_links_stably, canonicalize_directory_without_links,
        canonicalize_regular_file_without_links, exact_home_dir, expand_home_path,
        files_have_same_identity, open_directory_without_links, open_regular_file_without_links,
        path_has_no_link_components, path_text_has_exact_components, path_text_is_portable,
        strip_windows_verbatim_prefix,
    },
    DesktopResult,
};

const MAX_DESKTOP_FILE_BROWSER_ENTRIES: usize = 2000;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopFileBrowserEntry {
    kind: &'static str,
    modified_at: Option<f64>,
    name: String,
    path: String,
    size: Option<u64>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopFileBrowserRoot {
    label: String,
    path: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopFileBrowserSnapshot {
    cwd: String,
    entries: Vec<DesktopFileBrowserEntry>,
    parent: String,
    roots: Vec<DesktopFileBrowserRoot>,
}

pub(crate) fn browse_desktop_files(
    project_root: &Path,
    app_root: &Path,
    raw_path: Option<&str>,
    show_hidden: bool,
) -> DesktopResult<DesktopFileBrowserSnapshot> {
    let mut target = desktop_browse_target(project_root, app_root, raw_path)?;
    if target.is_file() {
        open_regular_file_without_links(&target).map_err(|error| {
            format!(
                "file browse target changed before inspection ({}): {error}",
                desktop_display_path(&target)
            )
        })?;
        target = target
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| app_root.to_path_buf());
    }
    if !target.exists() {
        return Err(format!("path does not exist: {}", desktop_display_path(&target)).into());
    }
    if !target.is_dir() {
        return Err(format!("path is not a directory: {}", desktop_display_path(&target)).into());
    }
    let target_directory = open_directory_without_links(&target).map_err(|error| {
        format!(
            "file browse directory is missing, linked, or changed ({}): {error}",
            desktop_display_path(&target)
        )
    })?;

    let mut entries = Vec::new();
    for child in fs::read_dir(&target)? {
        if entries.len() >= MAX_DESKTOP_FILE_BROWSER_ENTRIES {
            break;
        }
        let child = child?;
        // The bridge API is UTF-8.  A lossy conversion would expose a path
        // containing replacement characters that cannot be opened again, so
        // omit unrepresentable host entries instead of returning a false path.
        let Ok(name) = child.file_name().into_string() else {
            continue;
        };
        if !show_hidden && name.starts_with('.') {
            continue;
        }
        let child_path = child.path();
        // Do not expose a spelling that the next browse/select request must
        // reject (for example a POSIX filename containing a literal
        // backslash, or a Windows-reserved component).  Such an entry cannot
        // round-trip through the shared cross-platform path contract.
        if !path_text_is_portable(&child_path) {
            continue;
        }
        // Derive both the advertised type and metadata from the same
        // no-follow handle contract used by later reads. A one-shot
        // symlink_metadata call could describe one leaf and return the path
        // of a replacement leaf to React.
        let (metadata, is_dir) = match child.file_type() {
            Ok(file_type) if file_type.is_dir() => {
                let Ok(directory) = open_directory_without_links(&child_path) else {
                    continue;
                };
                let Ok(metadata) = directory.metadata() else {
                    continue;
                };
                (metadata, true)
            }
            Ok(file_type) if file_type.is_file() => {
                let Ok(file) = open_regular_file_without_links(&child_path) else {
                    continue;
                };
                let Ok(metadata) = file.metadata() else {
                    continue;
                };
                (metadata, false)
            }
            _ => continue,
        };
        entries.push(DesktopFileBrowserEntry {
            kind: if is_dir { "directory" } else { "file" },
            modified_at: metadata.modified().ok().and_then(system_time_secs),
            name,
            path: desktop_display_path(&child_path),
            size: if is_dir { None } else { Some(metadata.len()) },
        });
    }
    entries.sort_by(|left, right| {
        (left.kind != "directory")
            .cmp(&(right.kind != "directory"))
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });
    let current_target_directory = open_directory_without_links(&target).map_err(|error| {
        format!(
            "file browse directory changed during inspection ({}): {error}",
            desktop_display_path(&target)
        )
    })?;
    if !files_have_same_identity(&target_directory, &current_target_directory)? {
        return Err(format!(
            "file browse directory changed during inspection: {}",
            desktop_display_path(&target)
        )
        .into());
    }
    let parent = target
        .parent()
        .filter(|parent| *parent != target)
        .map(desktop_display_path)
        .unwrap_or_default();
    Ok(DesktopFileBrowserSnapshot {
        cwd: desktop_display_path(&target),
        entries,
        parent,
        roots: desktop_file_browser_roots(project_root, app_root)?,
    })
}

fn desktop_browse_target(
    project_root: &Path,
    app_root: &Path,
    raw_path: Option<&str>,
) -> DesktopResult<PathBuf> {
    let raw = raw_path.unwrap_or("");
    if raw != raw.trim()
        || raw
            .chars()
            .any(|character| character <= '\u{1f}' || character == '\u{7f}')
        || !desktop_path_text_is_exact(raw)
    {
        return Err(
            "path contains surrounding whitespace, control characters, or lexical aliases".into(),
        );
    }
    let uses_home_alias = raw == "~" || raw.starts_with("~/") || raw.starts_with(r"~\");
    let mut target = if raw.is_empty() {
        app_root.to_path_buf()
    } else {
        #[cfg(not(windows))]
        let native_raw = raw.replace('\\', "/");
        #[cfg(windows)]
        let native_raw = raw.to_string();
        expand_home_path(PathBuf::from(native_raw))
    };
    if uses_home_alias && !target.is_absolute() {
        return Err(
            "path uses a user-home alias but no valid absolute home directory is available".into(),
        );
    }
    if !target.is_absolute() {
        target = project_root.join(target);
    }
    if !path_has_no_link_components(&target) {
        return Err(format!(
            "path contains a symbolic link or reparse-point component: {}",
            target.display()
        )
        .into());
    }
    let canonical = if target.is_file() {
        canonicalize_regular_file_without_links(&target)
    } else {
        canonicalize_directory_without_links(&target)
    };
    match canonical {
        Ok(canonical) => Ok(canonical),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(target),
        Err(error) => Err(format!(
            "path changed while resolving the browse target ({}): {error}",
            target.display()
        )
        .into()),
    }
}

fn desktop_path_text_is_exact(raw: &str) -> bool {
    raw.is_empty() || path_text_has_exact_components(raw)
}

fn desktop_path_is_exact(path: &Path) -> bool {
    path_text_is_portable(path)
}

fn desktop_file_browser_roots(
    project_root: &Path,
    app_root: &Path,
) -> DesktopResult<Vec<DesktopFileBrowserRoot>> {
    let mut roots = Vec::new();
    let mut seen = Vec::new();
    push_desktop_file_browser_root(&mut roots, &mut seen, "Shinsekai", app_root.to_path_buf());
    let data_root = project_root.join("data");
    match open_directory_without_links(&data_root) {
        Ok(_) => push_desktop_file_browser_root(&mut roots, &mut seen, "Data", data_root),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(format!(
                "project data root must be a real directory ({}): {error}",
                data_root.display()
            )
            .into());
        }
    }
    if let Some(downloads) = desktop_downloads_dir() {
        push_desktop_file_browser_root(&mut roots, &mut seen, "Downloads", downloads);
    }
    if let Some(home) = desktop_home_dir() {
        push_desktop_file_browser_root(&mut roots, &mut seen, "Home", home);
    }
    for root in [app_root, project_root] {
        let resolved = canonicalize_directory_following_links_stably(root)
            .unwrap_or_else(|_| root.to_path_buf());
        if let Some(anchor) = resolved.ancestors().last().map(Path::to_path_buf) {
            let label = anchor.display().to_string();
            push_desktop_file_browser_root(&mut roots, &mut seen, &label, anchor);
        }
    }
    #[cfg(windows)]
    {
        for letter in b'A'..=b'Z' {
            let label = format!("{}:", letter as char);
            push_desktop_file_browser_root(
                &mut roots,
                &mut seen,
                &label,
                PathBuf::from(format!("{label}/")),
            );
        }
    }
    Ok(roots)
}

fn push_desktop_file_browser_root(
    roots: &mut Vec<DesktopFileBrowserRoot>,
    seen: &mut Vec<String>,
    label: &str,
    path: PathBuf,
) {
    let Ok(resolved) = canonicalize_directory_following_links_stably(&path) else {
        return;
    };
    let value = desktop_display_path(&resolved);
    let key = desktop_file_browser_root_key(&value);
    if seen.iter().any(|item| item == &key) {
        return;
    }
    seen.push(key);
    roots.push(DesktopFileBrowserRoot {
        label: desktop_file_browser_root_label(label, &value),
        path: value,
    });
}

fn desktop_file_browser_root_key(value: &str) -> String {
    let normalized = strip_windows_verbatim_prefix(value);
    #[cfg(windows)]
    {
        normalized.to_ascii_lowercase().replace('\\', "/")
    }
    #[cfg(not(windows))]
    {
        normalized
    }
}

fn desktop_file_browser_root_label(label: &str, path: &str) -> String {
    let normalized_label = strip_windows_verbatim_prefix(label);
    let normalized_path = strip_windows_verbatim_prefix(path);
    if normalized_label == "Home" {
        return "Home".to_string();
    }
    if normalized_label == "Data" {
        return "Data".to_string();
    }
    if normalized_label == "Downloads" {
        return "Downloads".to_string();
    }
    if normalized_label == "Shinsekai" {
        return "Shinsekai".to_string();
    }
    if normalized_label.trim().is_empty() {
        normalized_path
    } else {
        normalized_label
    }
}

fn desktop_downloads_dir() -> Option<PathBuf> {
    let home = desktop_home_dir()?;
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        if let Some(path) = xdg_downloads_dir(&home) {
            return Some(path);
        }
    }
    Some(home.join("Downloads"))
}

#[cfg(all(unix, not(target_os = "macos")))]
fn xdg_downloads_dir(home: &Path) -> Option<PathBuf> {
    let config_home = xdg_config_home(home, env::var_os("XDG_CONFIG_HOME"))?;
    xdg_downloads_dir_from_config_home(home, &config_home)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn xdg_config_home(home: &Path, configured: Option<std::ffi::OsString>) -> Option<PathBuf> {
    match configured {
        None => Some(home.join(".config")),
        Some(value) => {
            let path = PathBuf::from(value);
            (path.is_absolute() && desktop_path_is_exact(&path)).then_some(path)
        }
    }
}

#[cfg(all(unix, not(target_os = "macos")))]
fn xdg_downloads_dir_from_config_home(home: &Path, config_home: &Path) -> Option<PathBuf> {
    let user_dirs = config_home.join("user-dirs.dirs");
    let mut file = open_regular_file_without_links(&user_dirs).ok()?;
    let mut contents = String::new();
    file.read_to_string(&mut contents).ok()?;
    for line in contents.lines() {
        let trimmed = line.trim();
        if !trimmed.starts_with("XDG_DOWNLOAD_DIR=") {
            continue;
        }
        let value = trimmed
            .split_once('=')
            .map(|(_, value)| value.trim().trim_matches('"').trim_matches('\''))?;
        return expand_xdg_user_dir(value, home);
    }
    None
}

#[cfg(all(unix, not(target_os = "macos")))]
fn expand_xdg_user_dir(value: &str, home: &Path) -> Option<PathBuf> {
    if value.is_empty()
        || value != value.trim()
        || value
            .chars()
            .any(|character| character <= '\u{1f}' || character == '\u{7f}')
        || !desktop_path_text_is_exact(value)
    {
        return None;
    }
    if value == "$HOME" {
        return Some(home.to_path_buf());
    }
    if let Some(rest) = value.strip_prefix("$HOME/") {
        return Some(home.join(rest));
    }
    if let Some(rest) = value.strip_prefix("${HOME}/") {
        return Some(home.join(rest));
    }
    let path = PathBuf::from(value);
    let expanded = if path.is_absolute() {
        path
    } else {
        home.join(path)
    };
    desktop_path_is_exact(&expanded).then_some(expanded)
}

fn desktop_home_dir() -> Option<PathBuf> {
    exact_home_dir()
}

fn desktop_display_path(path: &Path) -> String {
    strip_windows_verbatim_prefix(&path.display().to_string())
}

fn system_time_secs(value: SystemTime) -> Option<f64> {
    value
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_secs_f64())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn browse_desktop_files_resolves_relative_paths_and_filters_hidden_entries() {
        let root = unique_temp_dir("desktop-files");
        let project_root = root.join("project");
        let app_root = root.join("app");
        let target = project_root.join("data");
        fs::create_dir_all(&target).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        fs::write(target.join("visible.txt"), "visible").unwrap();
        fs::write(target.join(".hidden.txt"), "hidden").unwrap();

        let snapshot = browse_desktop_files(&project_root, &app_root, Some("data"), false).unwrap();

        assert_eq!(snapshot.cwd, target.display().to_string());
        assert_eq!(snapshot.entries.len(), 1);
        assert_eq!(snapshot.entries[0].name, "visible.txt");
        assert_eq!(snapshot.entries[0].kind, "file");
        assert_eq!(snapshot.parent, project_root.display().to_string());
        assert!(snapshot.roots.iter().any(|root| root.label == "Shinsekai"));
        assert!(snapshot
            .roots
            .iter()
            .any(|root| root.label == "Data" && root.path == target.display().to_string()));

        let snapshot = browse_desktop_files(&project_root, &app_root, Some("data"), true).unwrap();
        assert!(snapshot
            .entries
            .iter()
            .any(|entry| entry.name == ".hidden.txt"));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn browse_desktop_files_can_open_the_filesystem_root_it_advertises() {
        let root = unique_temp_dir("desktop-files-filesystem-root");
        let project_root = root.join("project");
        let app_root = root.join("app");
        fs::create_dir_all(&project_root).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        let filesystem_root = root.ancestors().last().unwrap().to_path_buf();
        let filesystem_root_text = desktop_display_path(&filesystem_root);

        let snapshot =
            browse_desktop_files(&project_root, &app_root, Some(&filesystem_root_text), true)
                .unwrap();

        assert_eq!(snapshot.cwd, filesystem_root_text);
        assert_eq!(snapshot.parent, "");
        assert!(snapshot
            .roots
            .iter()
            .any(|entry| entry.path == snapshot.cwd));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn strips_windows_verbatim_prefixes_from_display_paths() {
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\?\D:\Downloads"),
            r"D:\Downloads"
        );
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\?\UNC\server\share\asset.png"),
            r"\\server\share\asset.png"
        );
        assert_eq!(
            strip_windows_verbatim_prefix("//?/D:/Downloads"),
            "D:/Downloads"
        );
        assert_eq!(
            strip_windows_verbatim_prefix("//?/UNC/server/share/asset.png"),
            "//server/share/asset.png"
        );
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\.\C:\device"),
            r"\\.\C:\device"
        );
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\?\GLOBALROOT\Device\HarddiskVolume1"),
            r"\\?\GLOBALROOT\Device\HarddiskVolume1"
        );
    }

    #[test]
    fn desktop_paths_reject_windows_device_and_unsupported_verbatim_namespaces() {
        assert!(!desktop_path_text_is_exact(r"\\.\C:\device"));
        assert!(!desktop_path_text_is_exact(
            r"\\?\GLOBALROOT\Device\HarddiskVolume1"
        ));
    }

    #[test]
    fn desktop_browse_target_rejects_surrounding_whitespace() {
        let root = unique_temp_dir("desktop-files-whitespace");
        fs::create_dir_all(&root).unwrap();

        let error = desktop_browse_target(&root, &root, Some(" data")).unwrap_err();

        assert!(error.to_string().contains("surrounding whitespace"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn desktop_browse_target_rejects_lexical_aliases() {
        let root = unique_temp_dir("desktop-files-aliases");
        fs::create_dir_all(root.join("data")).unwrap();

        for value in [
            "./data",
            "data//child",
            "data/../data",
            "data/",
            "~another-user/data",
        ] {
            let error = desktop_browse_target(&root, &root, Some(value)).unwrap_err();
            assert!(error.to_string().contains("lexical aliases"));
        }

        let _ = fs::remove_dir_all(root);
    }

    #[cfg(not(windows))]
    #[test]
    fn desktop_browse_target_normalizes_legacy_relative_windows_separators() {
        let root = unique_temp_dir("desktop-files-windows-relative");
        fs::create_dir_all(root.join("data").join("nested")).unwrap();

        let target = desktop_browse_target(&root, &root, Some(r"data\nested")).unwrap();

        assert_eq!(target, root.join("data").join("nested"));
        assert!(desktop_browse_target(&root, &root, Some(r"C:\data")).is_err());
        assert!(desktop_browse_target(&root, &root, Some("C:/data")).is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(not(windows))]
    #[test]
    fn desktop_browser_omits_entries_that_cannot_round_trip_portably() {
        let root = unique_temp_dir("desktop-files-nonportable");
        let project_root = root.join("project");
        let app_root = root.join("app");
        let target = project_root.join("data");
        fs::create_dir_all(&target).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        fs::write(target.join(r"literal\child.txt"), "unreachable").unwrap();
        fs::write(target.join("CON.txt"), "unreachable").unwrap();
        fs::write(target.join("portable.txt"), "visible").unwrap();

        let snapshot = browse_desktop_files(&project_root, &app_root, Some("data"), true).unwrap();
        let names: Vec<_> = snapshot
            .entries
            .iter()
            .map(|entry| entry.name.as_str())
            .collect();

        assert_eq!(names, vec!["portable.txt"]);
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    #[test]
    fn xdg_download_directory_rejects_whitespace_and_lexical_aliases() {
        let home = Path::new("/home/example");

        for value in [
            " Downloads",
            "Downloads ",
            "$HOME/Downloads/./Pictures",
            "$HOME/Downloads//Pictures",
            "$HOME/Downloads/../Secrets",
        ] {
            assert_eq!(expand_xdg_user_dir(value, home), None);
        }
        assert_eq!(
            expand_xdg_user_dir("$HOME/Downloads", home),
            Some(home.join("Downloads"))
        );
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    #[test]
    fn invalid_present_xdg_config_home_does_not_fall_back_to_another_config() {
        let home = Path::new("/home/example");

        assert_eq!(
            xdg_config_home(home, Some(std::ffi::OsString::from("relative-config"))),
            None
        );
        assert_eq!(
            xdg_config_home(
                home,
                Some(std::ffi::OsString::from("/home/example/config/../config"))
            ),
            None
        );
        assert_eq!(xdg_config_home(home, None), Some(home.join(".config")));
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    #[test]
    fn xdg_download_directory_does_not_read_a_linked_config_file() {
        use std::os::unix::fs::symlink;

        let root = unique_temp_dir("desktop-files-xdg-link");
        let home = root.join("home");
        let config_home = home.join(".config");
        let external = root.join("external-user-dirs.dirs");
        fs::create_dir_all(&config_home).unwrap();
        fs::write(&external, "XDG_DOWNLOAD_DIR=\"$HOME/redirected\"\n").unwrap();
        symlink(&external, config_home.join("user-dirs.dirs")).unwrap();

        assert_eq!(
            xdg_downloads_dir_from_config_home(&home, &config_home),
            None
        );
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn browse_desktop_files_skips_non_utf8_entries_instead_of_returning_lossy_paths() {
        use std::os::unix::ffi::OsStringExt;

        let root = unique_temp_dir("desktop-files-non-utf8");
        let project_root = root.join("project");
        let app_root = root.join("app");
        fs::create_dir_all(&project_root).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        let invalid_name = std::ffi::OsString::from_vec(vec![b'b', b'a', b'd', 0xff]);
        fs::write(app_root.join(invalid_name), "invalid").unwrap();

        let snapshot = browse_desktop_files(&project_root, &app_root, None, true).unwrap();

        assert!(snapshot.entries.is_empty());
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn browse_desktop_files_omits_entry_symlinks_rejected_by_readers() {
        use std::os::unix::fs::symlink;

        let root = unique_temp_dir("desktop-files-symlink-metadata");
        let project_root = root.join("project");
        let app_root = root.join("app");
        let external = root.join("external.bin");
        fs::create_dir_all(&project_root).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        fs::write(&external, vec![0_u8; 4096]).unwrap();
        let alias = app_root.join("external-link.bin");
        symlink(&external, &alias).unwrap();

        let snapshot = browse_desktop_files(&project_root, &app_root, None, true).unwrap();
        assert!(snapshot
            .entries
            .iter()
            .all(|entry| entry.name != "external-link.bin"));
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn browse_desktop_files_omits_special_files_rejected_by_readers() {
        use std::os::unix::net::UnixListener;

        let root = unique_temp_dir("desktop-files-special");
        let project_root = root.join("project");
        let app_root = root.join("app");
        fs::create_dir_all(&project_root).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        fs::write(app_root.join("regular.txt"), "visible").unwrap();
        let listener = match UnixListener::bind(app_root.join("runtime.sock")) {
            Ok(listener) => listener,
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
                let _ = fs::remove_dir_all(root);
                return;
            }
            Err(error) => panic!("failed to create Unix socket fixture: {error}"),
        };

        let snapshot = browse_desktop_files(&project_root, &app_root, None, true).unwrap();

        assert!(snapshot
            .entries
            .iter()
            .any(|entry| entry.name == "regular.txt" && entry.kind == "file"));
        assert!(snapshot
            .entries
            .iter()
            .all(|entry| entry.name != "runtime.sock"));
        drop(listener);
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn desktop_browse_target_rejects_a_direct_symlink_directory_request() {
        use std::os::unix::fs::symlink;

        let root = unique_temp_dir("desktop-files-direct-symlink");
        let project_root = root.join("project");
        let app_root = root.join("app");
        let external = root.join("external");
        let alias = project_root.join("alias");
        fs::create_dir_all(&project_root).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        fs::create_dir_all(&external).unwrap();
        symlink(&external, &alias).unwrap();

        let error = desktop_browse_target(&project_root, &app_root, Some("alias")).unwrap_err();

        assert!(error.to_string().contains("symbolic link"));
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn browse_desktop_files_rejects_a_linked_project_data_root() {
        use std::os::unix::fs::symlink;

        let root = unique_temp_dir("desktop-files-linked-data");
        let project_root = root.join("project");
        let app_root = root.join("app");
        let external = root.join("external-data");
        fs::create_dir_all(&project_root).unwrap();
        fs::create_dir_all(&app_root).unwrap();
        fs::create_dir_all(&external).unwrap();
        symlink(&external, project_root.join("data")).unwrap();

        let error = match browse_desktop_files(&project_root, &app_root, None, true) {
            Ok(_) => panic!("linked project data root was accepted"),
            Err(error) => error,
        };

        assert!(error.to_string().contains("project data root"));
        assert!(fs::read_dir(external).unwrap().next().is_none());
        let _ = fs::remove_dir_all(root);
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
    }
}
