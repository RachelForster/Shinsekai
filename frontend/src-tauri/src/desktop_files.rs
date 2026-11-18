use std::{
    env, fs,
    io::{self, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{
    ipc::{InvokeBody, Request},
    AppHandle, Manager,
};

use crate::DesktopResult;

const MAX_DESKTOP_FILE_BROWSER_ENTRIES: usize = 2000;

#[derive(Serialize)]
pub(crate) struct DesktopHistoryExport {
    path: String,
    name: String,
    opened: bool,
}

#[tauri::command(async)]
pub(crate) fn desktop_files_save_history_export(
    app: AppHandle,
    request: Request<'_>,
) -> Result<DesktopHistoryExport, String> {
    let InvokeBody::Raw(bytes) = request.body() else {
        return Err("expected binary image or video".into());
    };
    let downloads = app
        .path()
        .download_dir()
        .map_err(|error| error.to_string())?;
    let (path, name) = save_history_export(&downloads.join("Shinsekai"), bytes)
        .map_err(|error| error.to_string())?;
    Ok(DesktopHistoryExport {
        opened: open_history_export(&path),
        path: desktop_display_path(&path),
        name,
    })
}

fn save_history_export(directory: &Path, bytes: &[u8]) -> io::Result<(PathBuf, String)> {
    let extension = if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        "png"
    } else if bytes.starts_with(&[0xff, 0xd8, 0xff]) {
        "jpg"
    } else if bytes.len() >= 12 && &bytes[0..4] == b"RIFF" && &bytes[8..12] == b"WEBP" {
        "webp"
    } else if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        "gif"
    } else if bytes.get(4..8) == Some(b"ftyp") {
        "mp4"
    } else if bytes.starts_with(b"\x1a\x45\xdf\xa3") {
        "webm"
    } else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "unsupported history export",
        ));
    };
    write_unique_export(directory, "shinsekai", extension, bytes)
}

#[tauri::command(async)]
pub(crate) fn desktop_files_save_text_export(
    app: AppHandle,
    name: String,
    text: String,
) -> Result<DesktopHistoryExport, String> {
    let downloads = app
        .path()
        .download_dir()
        .map_err(|error| error.to_string())?;
    let (path, name) = save_text_export(&downloads.join("Shinsekai"), &name, &text)
        .map_err(|error| error.to_string())?;
    Ok(DesktopHistoryExport {
        opened: false,
        path: desktop_display_path(&path),
        name,
    })
}

fn sanitize_export_stem(name: &str) -> String {
    let cleaned: String = name
        .chars()
        .map(|ch| {
            if ch.is_control() || matches!(ch, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*')
            {
                '_'
            } else {
                ch
            }
        })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').trim();
    let stem: String = trimmed.chars().take(80).collect();
    if stem.is_empty() {
        "shinsekai".to_string()
    } else {
        stem
    }
}

fn save_text_export(directory: &Path, name: &str, text: &str) -> io::Result<(PathBuf, String)> {
    let stem = name.trim().strip_suffix(".txt").unwrap_or(name.trim());
    let stem = sanitize_export_stem(stem);
    // Prefix a UTF-8 BOM so legacy Windows editors detect the encoding correctly.
    let mut bytes = Vec::with_capacity(text.len() + 3);
    bytes.extend_from_slice(b"\xEF\xBB\xBF");
    bytes.extend_from_slice(text.as_bytes());
    write_unique_export(directory, &stem, "txt", &bytes)
}

fn write_unique_export(
    directory: &Path,
    stem: &str,
    extension: &str,
    bytes: &[u8],
) -> io::Result<(PathBuf, String)> {
    fs::create_dir_all(directory)?;
    let timestamp = chrono::Local::now().format("%Y%m%d-%H%M%S-%3f");
    for index in 0.. {
        let name = format!("{stem}-{timestamp}-{index}.{extension}");
        let path = directory.join(&name);
        let mut file = match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        };
        if let Err(error) = file.write_all(bytes) {
            drop(file);
            let _ = fs::remove_file(&path);
            return Err(error);
        }
        return Ok((path, name));
    }
    unreachable!()
}

#[cfg(windows)]
fn open_history_export(path: &Path) -> bool {
    use std::{ffi::c_void, os::windows::ffi::OsStrExt, ptr::null};
    #[link(name = "shell32")]
    unsafe extern "system" {
        fn ShellExecuteW(
            window: *const c_void,
            operation: *const u16,
            file: *const u16,
            parameters: *const u16,
            directory: *const u16,
            show: i32,
        ) -> isize;
    }
    let file: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    // SW_SHOWNORMAL opens the saved media using its default Windows association.
    unsafe { ShellExecuteW(null(), null(), file.as_ptr(), null(), null(), 1) > 32 }
}

#[cfg(not(windows))]
fn open_history_export(path: &Path) -> bool {
    let opener = if cfg!(target_os = "macos") {
        "open"
    } else {
        "xdg-open"
    };
    std::process::Command::new(opener).arg(path).spawn().is_ok()
}

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
    fn history_exports_keep_their_format_and_never_overwrite() {
        let directory = unique_temp_dir("history-export");
        for (bytes, extension) in [
            (b"\x89PNG\r\n\x1a\nimage".as_slice(), "png"),
            (b"\x00\x00\x00\x18ftypmp42".as_slice(), "mp4"),
            (b"\x1a\x45\xdf\xa3video".as_slice(), "webm"),
        ] {
            let (path, name) = save_history_export(&directory, bytes).unwrap();
            let (second, _) = save_history_export(&directory, bytes).unwrap();
            assert_ne!(path, second);
            assert_eq!(path, directory.join(name));
            assert_eq!(path.extension().unwrap(), extension);
            assert_eq!(fs::read(&path).unwrap(), bytes);
            fs::remove_file(path).unwrap();
            fs::remove_file(second).unwrap();
        }
        assert!(save_history_export(&directory, b"arbitrary file").is_err());
        fs::remove_dir(directory).unwrap();
    }

    #[test]
    fn text_exports_sanitize_names_and_write_utf8_with_bom() {
        let directory = unique_temp_dir("text-export");
        let (path, name) =
            save_text_export(&directory, "Mika/记忆:*.txt", "第一条\n第二条").unwrap();
        assert_eq!(path, directory.join(&name));
        assert!(name.starts_with("Mika_记忆__-"));
        assert_eq!(path.extension().unwrap(), "txt");
        let bytes = fs::read(&path).unwrap();
        assert_eq!(&bytes[..3], b"\xEF\xBB\xBF");
        assert_eq!(std::str::from_utf8(&bytes[3..]).unwrap(), "第一条\n第二条");
        let (fallback, fallback_name) = save_text_export(&directory, " .. ", "x").unwrap();
        assert!(fallback_name.starts_with("shinsekai-"));
        fs::remove_file(path).unwrap();
        fs::remove_file(fallback).unwrap();
        fs::remove_dir(directory).unwrap();
    }

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
