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
        return Err(format!("path does not exist: {}", target.display()).into());
    }
    if !target.is_dir() {
        return Err(format!("path is not a directory: {}", target.display()).into());
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
            path: child.path().display().to_string(),
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
        .map(|parent| parent.display().to_string())
        .unwrap_or_default();
    Ok(DesktopFileBrowserSnapshot {
        cwd: target.display().to_string(),
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
    push_desktop_file_browser_root(&mut roots, &mut seen, "Data", app_root.join("data"));
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
    let value = resolved.display().to_string();
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
    #[cfg(windows)]
    {
        value.to_ascii_lowercase().replace('\\', "/")
    }
    #[cfg(not(windows))]
    {
        value.to_string()
    }
}

fn desktop_file_browser_root_label(label: &str, path: &str) -> String {
    if label == "Home" {
        return "Home".to_string();
    }
    if label == "Data" {
        return "Data".to_string();
    }
    if label == "Shinsekai" {
        return "Shinsekai".to_string();
    }
    if label.trim().is_empty() {
        path.to_string()
    } else {
        label.to_string()
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

        let snapshot = browse_desktop_files(&project_root, &app_root, Some("data"), true).unwrap();
        assert!(snapshot
            .entries
            .iter()
            .any(|entry| entry.name == ".hidden.txt"));

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
