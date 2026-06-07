use std::{
    env, fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde::Serialize;

use crate::DesktopResult;

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

    let mut entries = Vec::new();
    for child in fs::read_dir(&target)? {
        if entries.len() >= MAX_DESKTOP_FILE_BROWSER_ENTRIES {
            break;
        }
        let child = child?;
        let name = child.file_name().to_string_lossy().to_string();
        if !show_hidden && name.starts_with('.') {
            continue;
        }
        let file_type = match child.file_type() {
            Ok(file_type) => file_type,
            Err(_) => continue,
        };
        let metadata = match child.metadata() {
            Ok(metadata) => metadata,
            Err(_) => continue,
        };
        let is_dir = file_type.is_dir();
        entries.push(DesktopFileBrowserEntry {
            kind: if is_dir { "directory" } else { "file" },
            modified_at: metadata.modified().ok().and_then(system_time_secs),
            name,
            path: desktop_display_path(&child.path()),
            size: if is_dir { None } else { Some(metadata.len()) },
        });
    }
    entries.sort_by(|left, right| {
        (left.kind != "directory")
            .cmp(&(right.kind != "directory"))
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });
    let parent = target
        .parent()
        .filter(|parent| *parent != target)
        .map(desktop_display_path)
        .unwrap_or_default();
    Ok(DesktopFileBrowserSnapshot {
        cwd: desktop_display_path(&target),
        entries,
        parent,
        roots: desktop_file_browser_roots(project_root, app_root),
    })
}

fn desktop_browse_target(
    project_root: &Path,
    app_root: &Path,
    raw_path: Option<&str>,
) -> DesktopResult<PathBuf> {
    let trimmed = raw_path.unwrap_or("").trim();
    let mut target = if trimmed.is_empty() {
        app_root.to_path_buf()
    } else {
        expand_home_path(PathBuf::from(trimmed))
    };
    if !target.is_absolute() {
        target = project_root.join(target);
    }
    Ok(target.canonicalize().unwrap_or(target))
}

fn desktop_file_browser_roots(project_root: &Path, app_root: &Path) -> Vec<DesktopFileBrowserRoot> {
    let mut roots = Vec::new();
    let mut seen = Vec::new();
    push_desktop_file_browser_root(&mut roots, &mut seen, "Shinsekai", app_root.to_path_buf());
    let data_root = project_root.join("data");
    let _ = fs::create_dir_all(&data_root);
    push_desktop_file_browser_root(&mut roots, &mut seen, "Data", data_root);
    if let Some(downloads) = desktop_downloads_dir() {
        push_desktop_file_browser_root(&mut roots, &mut seen, "Downloads", downloads);
    }
    if let Some(home) = desktop_home_dir() {
        push_desktop_file_browser_root(&mut roots, &mut seen, "Home", home);
    }
    for root in [app_root, project_root] {
        if let Some(anchor) = root
            .canonicalize()
            .unwrap_or_else(|_| root.to_path_buf())
            .ancestors()
            .last()
            .map(Path::to_path_buf)
        {
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
    roots
}

fn push_desktop_file_browser_root(
    roots: &mut Vec<DesktopFileBrowserRoot>,
    seen: &mut Vec<String>,
    label: &str,
    path: PathBuf,
) {
    let resolved = path.canonicalize().unwrap_or(path);
    if !resolved.exists() {
        return;
    }
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

fn expand_home_path(path: PathBuf) -> PathBuf {
    let raw = path.as_os_str().to_string_lossy();
    if raw == "~" {
        return desktop_home_dir().unwrap_or(path);
    }
    if let Some(rest) = raw.strip_prefix("~/") {
        if let Some(home) = desktop_home_dir() {
            return home.join(rest);
        }
    }
    path
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
    let config_home = env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".config"));
    let contents = fs::read_to_string(config_home.join("user-dirs.dirs")).ok()?;
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
    if value.is_empty() {
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
    Some(if path.is_absolute() {
        path
    } else {
        home.join(path)
    })
}

fn desktop_home_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        env::var_os("USERPROFILE").map(PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        env::var_os("HOME").map(PathBuf::from)
    }
}

fn desktop_display_path(path: &Path) -> String {
    strip_windows_verbatim_prefix(&path.display().to_string())
}

fn strip_windows_verbatim_prefix(value: &str) -> String {
    if let Some(rest) = value.strip_prefix(r"\\?\UNC\") {
        return format!(r"\\{}", rest);
    }
    if let Some(rest) = value.strip_prefix(r"\\?\") {
        return rest.to_string();
    }
    if let Some(rest) = value.strip_prefix("//?/UNC/") {
        return format!("//{}", rest);
    }
    if let Some(rest) = value.strip_prefix("//?/") {
        return rest.to_string();
    }
    value.to_string()
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
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
    }
}
