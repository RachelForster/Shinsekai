#[cfg(unix)]
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
#[cfg(windows)]
use std::os::windows::fs::MetadataExt;
#[cfg(windows)]
use std::os::windows::fs::OpenOptionsExt;
use std::{
    env,
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
};

#[cfg(windows)]
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
#[cfg(windows)]
const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;

pub(crate) fn path_text_is_portable(path: &Path) -> bool {
    let Some(text) = path.to_str() else {
        return false;
    };
    !text.is_empty()
        && text.trim() == text
        && !text
            .chars()
            .any(|character| character <= '\u{1f}' || character == '\u{7f}')
        && path_text_has_exact_components(text)
}

pub(crate) fn path_is_filesystem_root(path: &Path) -> bool {
    path.is_absolute() && path.parent().is_none()
}

pub(crate) fn path_has_no_link_components(path: &Path) -> bool {
    // ``Path::components`` normalizes away ``.`` and can carry ``..`` as a
    // traversal component.  Reject the raw spelling first so link inspection
    // and the later open never operate on a different lexical identity.
    if !path.is_absolute() || !path_text_is_portable(path) {
        return false;
    }
    let mut cursor = PathBuf::new();
    for component in path.components() {
        cursor.push(component.as_os_str());
        #[cfg(windows)]
        if matches!(component, std::path::Component::Prefix(_)) {
            // A bare `C:` is drive-relative and a bare UNC prefix is not a
            // filesystem object. Check the anchored root after RootDir arrives.
            continue;
        }
        match fs::symlink_metadata(&cursor) {
            Ok(metadata) if metadata_is_link(&metadata) => return false,
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return false,
        }
    }
    true
}

pub(crate) fn open_regular_file_without_links(path: &Path) -> std::io::Result<fs::File> {
    if !path_has_no_link_components(path) {
        return Err(std::io::Error::other(
            "path contains a symbolic link or reparse point",
        ));
    }
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW);
    #[cfg(windows)]
    options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    if metadata_is_link(&metadata)
        || !metadata.file_type().is_file()
        || !path_has_no_link_components(path)
    {
        return Err(std::io::Error::other(
            "path changed to a non-regular or linked file",
        ));
    }
    let verification_file = options.open(path)?;
    let verification_metadata = verification_file.metadata()?;
    if metadata_is_link(&verification_metadata)
        || !verification_metadata.file_type().is_file()
        || !files_have_same_identity(&file, &verification_file)?
    {
        return Err(std::io::Error::other(
            "path changed to a different regular file",
        ));
    }
    Ok(file)
}

pub(crate) fn open_directory_without_links(path: &Path) -> std::io::Result<fs::File> {
    if !path_has_no_link_components(path) {
        return Err(std::io::Error::other(
            "path contains a symbolic link or reparse point",
        ));
    }
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW);
    #[cfg(windows)]
    options.custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT);
    let directory = options.open(path)?;
    let metadata = directory.metadata()?;
    if metadata_is_link(&metadata)
        || !metadata.file_type().is_dir()
        || !path_has_no_link_components(path)
    {
        return Err(std::io::Error::other(
            "path changed to a non-directory or linked directory",
        ));
    }
    let verification = options.open(path)?;
    let verification_metadata = verification.metadata()?;
    if metadata_is_link(&verification_metadata)
        || !verification_metadata.file_type().is_dir()
        || !files_have_same_identity(&directory, &verification)?
    {
        return Err(std::io::Error::other(
            "path changed to a different directory",
        ));
    }
    Ok(directory)
}

pub(crate) fn canonicalize_regular_file_without_links(path: &Path) -> std::io::Result<PathBuf> {
    let file = open_regular_file_without_links(path)?;
    canonicalize_open_regular_file_without_links(path, &file)
}

pub(crate) fn canonicalize_regular_file_following_links_stably(
    path: &Path,
) -> std::io::Result<PathBuf> {
    if !path.is_absolute() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "regular file path must be absolute",
        ));
    }
    let canonical = path.canonicalize()?;
    let file = open_regular_file_without_links(&canonical)?;
    let verification_path = path.canonicalize()?;
    let verification = open_regular_file_without_links(&verification_path)?;
    if verification_path != canonical || !files_have_same_identity(&file, &verification)? {
        return Err(std::io::Error::other(
            "regular file alias changed while resolving its canonical path",
        ));
    }
    Ok(canonical)
}

fn canonicalize_open_regular_file_without_links(
    path: &Path,
    file: &fs::File,
) -> std::io::Result<PathBuf> {
    let canonical = path.canonicalize()?;
    let canonical_file = open_regular_file_without_links(&canonical)?;
    if !files_have_same_identity(file, &canonical_file)? {
        return Err(std::io::Error::other(
            "regular file changed while resolving its canonical path",
        ));
    }
    let verification = open_regular_file_without_links(path)?;
    if !files_have_same_identity(file, &verification)? {
        return Err(std::io::Error::other(
            "regular file path changed while resolving its canonical path",
        ));
    }
    Ok(canonical)
}

pub(crate) fn canonicalize_directory_without_links(path: &Path) -> std::io::Result<PathBuf> {
    let directory = open_directory_without_links(path)?;
    canonicalize_open_directory_without_links(path, &directory)
}

pub(crate) fn canonicalize_directory_following_links_stably(
    path: &Path,
) -> std::io::Result<PathBuf> {
    if !path.is_absolute() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "directory path must be absolute",
        ));
    }
    let canonical = path.canonicalize()?;
    let directory = open_directory_without_links(&canonical)?;
    let verification_path = path.canonicalize()?;
    let verification = open_directory_without_links(&verification_path)?;
    if verification_path != canonical || !files_have_same_identity(&directory, &verification)? {
        return Err(std::io::Error::other(
            "directory alias changed while resolving its canonical path",
        ));
    }
    Ok(canonical)
}

pub(crate) struct ExecutableSnapshot {
    path: PathBuf,
    identity: fs::File,
}

impl ExecutableSnapshot {
    pub(crate) fn capture(command: &str) -> std::io::Result<Self> {
        if command.is_empty()
            || command.trim() != command
            || command
                .chars()
                .any(|character| character <= '\u{1f}' || character == '\u{7f}')
        {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "command name contains non-portable characters",
            ));
        }
        let requested = Path::new(command);
        if requested.is_absolute() {
            return Self::capture_candidate(requested);
        }
        if requested.components().count() != 1 || !portable_path_component(command) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "command must be an absolute path or one portable PATH name",
            ));
        }
        let search_path = env::var_os("PATH").ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::NotFound, "PATH is not configured")
        })?;
        Self::capture_from_search_paths(command, env::split_paths(&search_path))
    }

    fn capture_from_search_paths<I>(command: &str, search_paths: I) -> std::io::Result<Self>
    where
        I: IntoIterator<Item = PathBuf>,
    {
        let mut last_error = None;
        for directory in search_paths {
            // Relative or empty PATH entries inherit the ambient cwd.  They
            // cannot participate in a deterministic desktop launch.
            if !directory.is_absolute() || !path_text_is_portable(&directory) {
                continue;
            }
            for name in executable_candidate_names(command) {
                let candidate = directory.join(name);
                match Self::capture_candidate(&candidate) {
                    Ok(snapshot) => return Ok(snapshot),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                        last_error = Some(error);
                    }
                    Err(error) => {
                        last_error = Some(error);
                    }
                }
            }
        }
        Err(last_error.unwrap_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("command was not found in deterministic PATH entries: {command}"),
            )
        }))
    }

    fn capture_candidate(candidate: &Path) -> std::io::Result<Self> {
        if !candidate.is_absolute() || !path_text_is_portable(candidate) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "executable candidate path is not a portable absolute path",
            ));
        }
        let parent = candidate.parent().ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "executable candidate has no parent directory",
            )
        })?;
        let parent_identity = open_directory_without_links(parent)?;
        // A POSIX virtual environment and several system tools expose the
        // final executable as a symlink.  Resolve only that leaf after the
        // containing path is pinned; the canonical target itself must be a
        // link-free regular executable.
        let canonical = candidate.canonicalize()?;
        let identity = open_regular_file_without_links(&canonical)?;
        require_executable_permissions(&identity)?;
        let verification_path = candidate.canonicalize()?;
        if verification_path != canonical {
            return Err(std::io::Error::other(
                "executable alias changed while it was captured",
            ));
        }
        let verification = open_regular_file_without_links(&canonical)?;
        if !files_have_same_identity(&identity, &verification)? {
            return Err(std::io::Error::other(
                "executable changed while it was captured",
            ));
        }
        let current_parent = open_directory_without_links(parent)?;
        if !files_have_same_identity(&parent_identity, &current_parent)? {
            return Err(std::io::Error::other(
                "executable parent changed while it was captured",
            ));
        }
        Ok(Self {
            path: canonical,
            identity,
        })
    }

    pub(crate) fn path(&self) -> &Path {
        &self.path
    }

    pub(crate) fn require_current(&self) -> std::io::Result<()> {
        let current = open_regular_file_without_links(&self.path)?;
        require_executable_permissions(&current)?;
        if !files_have_same_identity(&self.identity, &current)? {
            return Err(std::io::Error::other(
                "selected executable path changed identity",
            ));
        }
        Ok(())
    }
}

#[cfg(not(windows))]
fn executable_candidate_names(command: &str) -> Vec<OsString> {
    vec![OsString::from(command)]
}

#[cfg(windows)]
fn executable_candidate_names(command: &str) -> Vec<OsString> {
    if Path::new(command).extension().is_some() {
        return vec![OsString::from(command)];
    }
    let extensions = env::var_os("PATHEXT")
        .and_then(|value| value.into_string().ok())
        .unwrap_or_else(|| ".COM;.EXE;.BAT;.CMD".to_string());
    extensions
        .split(';')
        .filter_map(|extension| portable_windows_executable_candidate_name(command, extension))
        .collect()
}

#[cfg_attr(not(windows), allow(dead_code))]
fn portable_windows_executable_candidate_name(command: &str, extension: &str) -> Option<OsString> {
    if !portable_windows_path_extension(extension) {
        return None;
    }
    let candidate = format!("{command}{extension}");
    portable_path_component(&candidate).then(|| OsString::from(candidate))
}

#[cfg_attr(not(windows), allow(dead_code))]
fn portable_windows_path_extension(extension: &str) -> bool {
    extension.strip_prefix('.').is_some_and(|tail| {
        !tail.is_empty()
            && tail
                .chars()
                .all(|character| character.is_ascii_alphanumeric())
    })
}

#[cfg(unix)]
fn require_executable_permissions(file: &fs::File) -> std::io::Result<()> {
    if file.metadata()?.mode() & 0o111 == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "selected command file is not executable",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn require_executable_permissions(_file: &fs::File) -> std::io::Result<()> {
    Ok(())
}

fn canonicalize_open_directory_without_links(
    path: &Path,
    directory: &fs::File,
) -> std::io::Result<PathBuf> {
    let canonical = path.canonicalize()?;
    let canonical_directory = open_directory_without_links(&canonical)?;
    if !files_have_same_identity(directory, &canonical_directory)? {
        return Err(std::io::Error::other(
            "directory changed while resolving its canonical path",
        ));
    }
    let verification = open_directory_without_links(path)?;
    if !files_have_same_identity(directory, &verification)? {
        return Err(std::io::Error::other(
            "directory path changed while resolving its canonical path",
        ));
    }
    Ok(canonical)
}

#[cfg(unix)]
pub(crate) fn files_have_same_identity(left: &fs::File, right: &fs::File) -> std::io::Result<bool> {
    let left = left.metadata()?;
    let right = right.metadata()?;
    Ok(left.dev() == right.dev() && left.ino() == right.ino())
}

#[cfg(windows)]
pub(crate) fn files_have_same_identity(left: &fs::File, right: &fs::File) -> std::io::Result<bool> {
    use std::mem::MaybeUninit;
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };

    fn identity(file: &fs::File) -> std::io::Result<BY_HANDLE_FILE_INFORMATION> {
        let mut information = MaybeUninit::<BY_HANDLE_FILE_INFORMATION>::zeroed();
        let result =
            unsafe { GetFileInformationByHandle(file.as_raw_handle(), information.as_mut_ptr()) };
        if result == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(unsafe { information.assume_init() })
    }

    let left = identity(left)?;
    let right = identity(right)?;
    Ok(left.dwVolumeSerialNumber == right.dwVolumeSerialNumber
        && left.nFileIndexHigh == right.nFileIndexHigh
        && left.nFileIndexLow == right.nFileIndexLow)
}

#[cfg(not(windows))]
pub(crate) fn metadata_is_link(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

#[cfg(windows)]
pub(crate) fn metadata_is_link(metadata: &fs::Metadata) -> bool {
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
    metadata.file_type().is_symlink()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

pub(crate) fn path_text_has_exact_components(text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    #[cfg(not(windows))]
    if text.starts_with('/') && text.contains('\\') {
        // POSIX permits a literal backslash in a filename, while persisted
        // project paths and the Windows launcher interpret it as a separator.
        // Reject that split identity for native absolute paths.
        return false;
    }
    let portable = text.replace('\\', "/");
    if portable.starts_with("//./") || portable.starts_with("/??/") {
        return false;
    }
    if let Some(rest) = portable.strip_prefix("//?/") {
        #[cfg(not(windows))]
        {
            let _ = rest;
            return false;
        }
        #[cfg(windows)]
        {
            if windows_drive_absolute_path_text(rest) {
                let tail = &rest[3..];
                return tail.is_empty() || exact_slash_components(tail);
            }
            let Some(unc_tail) = strip_ascii_prefix(rest, "UNC/") else {
                return false;
            };
            return exact_windows_unc_tail(unc_tail);
        }
    }
    if portable == "/" {
        #[cfg(windows)]
        {
            return false;
        }
        #[cfg(not(windows))]
        return true;
    }
    if let Some(rest) = portable.strip_prefix("//") {
        #[cfg(not(windows))]
        {
            let _ = rest;
            return false;
        }
        #[cfg(windows)]
        {
            return exact_windows_unc_tail(rest);
        }
    }
    if windows_drive_prefixed_path_text(&portable) && !windows_drive_absolute_path_text(&portable) {
        return false;
    }
    if windows_drive_absolute_path_text(&portable) {
        #[cfg(not(windows))]
        {
            return false;
        }
        #[cfg(windows)]
        {
            let tail = &portable[3..];
            return tail.is_empty() || exact_slash_components(tail);
        }
    }
    if let Some(rest) = portable.strip_prefix('/') {
        #[cfg(windows)]
        {
            let _ = rest;
            // Rooted paths without a drive inherit ambient drive state.
            return false;
        }
        #[cfg(not(windows))]
        return exact_slash_components(rest);
    }
    let first_component = portable.split('/').next().unwrap_or_default();
    if first_component.starts_with('~') && first_component != "~" {
        return false;
    }
    exact_slash_components(&portable)
}

pub(crate) fn strip_windows_verbatim_prefix(value: &str) -> String {
    if let Some(rest) = value.strip_prefix(r"\\?\") {
        if let Some(unc_tail) = strip_ascii_prefix(rest, r"UNC\") {
            if windows_unc_tail_has_server_share(unc_tail) {
                return format!(r"\\{}", unc_tail);
            }
        }
        if windows_drive_absolute_path_text(rest) {
            return rest.to_string();
        }
    }
    if let Some(rest) = value.strip_prefix("//?/") {
        if let Some(unc_tail) = strip_ascii_prefix(rest, "UNC/") {
            if windows_unc_tail_has_server_share(unc_tail) {
                return format!("//{}", unc_tail);
            }
        }
        if windows_drive_absolute_path_text(rest) {
            return rest.to_string();
        }
    }
    value.to_string()
}

pub(crate) fn expand_home_path(path: PathBuf) -> PathBuf {
    let Some(raw) = path.to_str() else {
        return path;
    };
    if raw == "~" {
        return exact_home_dir().unwrap_or(path);
    }
    if let Some(rest) = raw.strip_prefix("~/") {
        if let Some(home) = exact_home_dir() {
            return home.join(rest);
        }
    }
    if let Some(rest) = raw.strip_prefix(r"~\") {
        if let Some(home) = exact_home_dir() {
            return home.join(rest);
        }
    }
    path
}

pub(crate) fn exact_home_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    let value = env::var_os("USERPROFILE");
    #[cfg(not(windows))]
    let value = env::var_os("HOME");

    value
        .map(PathBuf::from)
        .filter(|path| path.is_absolute() && path_text_is_portable(path))
}

fn exact_slash_components(value: &str) -> bool {
    value.split('/').all(portable_path_component)
}

#[cfg(windows)]
fn exact_windows_unc_tail(value: &str) -> bool {
    if !windows_unc_tail_has_server_share(value) {
        return false;
    }
    let parts: Vec<&str> = value.split(['/', '\\']).collect();
    if parts.len() == 3 && parts[2].is_empty() {
        return true;
    }
    parts
        .iter()
        .all(|component| portable_path_component(component))
}

fn windows_drive_absolute_path_text(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() >= 3
        && bytes[0].is_ascii_alphabetic()
        && bytes[1] == b':'
        && matches!(bytes[2], b'/' | b'\\')
}

fn windows_drive_prefixed_path_text(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':'
}

fn windows_unc_tail_has_server_share(value: &str) -> bool {
    let mut parts = value.split(['/', '\\']);
    matches!(parts.next(), Some(server) if portable_path_component(server))
        && matches!(parts.next(), Some(share) if portable_path_component(share))
}

fn portable_path_component(value: &str) -> bool {
    if value.is_empty()
        || matches!(value, "." | "..")
        || value.trim() != value
        || value.ends_with([' ', '.'])
        || value.len() > 255
        || value.chars().any(|character| {
            character <= '\u{1f}'
                || character == '\u{7f}'
                || matches!(
                    character,
                    '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'
                )
        })
    {
        return false;
    }
    let stem = value
        .split('.')
        .next()
        .unwrap_or_default()
        .to_ascii_uppercase();
    !matches!(
        stem.as_str(),
        "CON" | "PRN" | "AUX" | "NUL" | "CLOCK$" | "CONIN$" | "CONOUT$"
    ) && !["COM", "LPT"].iter().any(|prefix| {
        stem.strip_prefix(prefix).is_some_and(|suffix| {
            matches!(
                suffix,
                "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
            )
        })
    })
}

fn strip_ascii_prefix<'a>(value: &'a str, prefix: &str) -> Option<&'a str> {
    value
        .get(..prefix.len())
        .filter(|candidate| candidate.eq_ignore_ascii_case(prefix))
        .map(|_| &value[prefix.len()..])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_lexical_aliases_and_windows_device_namespaces() {
        for value in [
            "data/./item",
            "data//item",
            "data/../item",
            "~another-user/item",
            "C:relative",
            "C:",
            r"\\.\C:\device",
            r"\\?\GLOBALROOT\Device\HarddiskVolume1",
            r"\??\C:\device",
            "data/CON",
            "data/NUL.txt",
            "data/CLOCK$",
            "data/CONIN$.log",
            "data/COM¹",
            "data/LPT³.txt",
            "data/ leading",
            "data/name.",
            "data/name ",
            "data/name:stream",
            "C:/runtime/COM1.log",
            "//server/../asset",
        ] {
            assert!(!path_text_has_exact_components(value), "{value}");
        }
        assert!(path_text_has_exact_components("数据/模型 文件.bin"));
        assert!(portable_path_component(&"界".repeat(85)));
        assert!(!portable_path_component(&"界".repeat(86)));
        assert!(!portable_path_component(&"a".repeat(256)));

        let exact = env::temp_dir().join("shinsekai-path-contract").join("item");
        let aliased = env::temp_dir()
            .join("shinsekai-path-contract")
            .join("..")
            .join("item");
        assert!(path_has_no_link_components(&exact));
        assert!(!path_has_no_link_components(&aliased));
        assert!(!path_has_no_link_components(
            &env::temp_dir()
                .join("shinsekai-path-contract")
                .join("item.")
        ));
    }

    #[test]
    fn windows_path_extensions_are_single_portable_suffixes() {
        assert!(portable_windows_path_extension(".EXE"));
        for value in [".", "..EXE", ".EXE.", ".EX E", ".工具", " .EXE", ".EXE "] {
            assert!(!portable_windows_path_extension(value), "{value}");
        }
        assert_eq!(
            portable_windows_executable_candidate_name(&"a".repeat(251), ".EXE"),
            Some(OsString::from(format!("{}.EXE", "a".repeat(251))))
        );
        assert_eq!(
            portable_windows_executable_candidate_name(&"a".repeat(252), ".EXE"),
            None
        );
    }

    #[cfg(not(windows))]
    #[test]
    fn rejects_backslash_in_native_posix_absolute_paths() {
        assert!(!path_text_has_exact_components(r"/tmp/literal\child"));
        assert!(!path_text_has_exact_components(r"C:\project\data"));
        assert!(!path_text_has_exact_components("C:/project/data"));
        // Relative Windows separators remain valid for legacy persisted
        // project references; their caller must normalize the components.
        assert!(path_text_has_exact_components(r"data\cache\item.bin"));
    }

    #[cfg(windows)]
    #[test]
    fn rejects_current_drive_rooted_paths() {
        for value in [r"\rooted", "/rooted", "/"] {
            assert!(!path_text_has_exact_components(value), "{value}");
        }
    }

    #[test]
    fn strips_only_filesystem_shaped_windows_verbatim_prefixes() {
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\?\D:\Downloads"),
            r"D:\Downloads"
        );
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\?\UNC\server\share\asset.png"),
            r"\\server\share\asset.png"
        );
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\?\unc\server\share\asset.png"),
            r"\\server\share\asset.png"
        );
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\.\C:\device"),
            r"\\.\C:\device"
        );
        assert_eq!(
            strip_windows_verbatim_prefix(r"\\?\GLOBALROOT\Device"),
            r"\\?\GLOBALROOT\Device"
        );
    }

    #[cfg(unix)]
    #[test]
    fn strict_file_helpers_reject_linked_leaves_and_parents() {
        use std::os::unix::fs::symlink;
        use std::os::unix::fs::PermissionsExt;
        use std::time::{SystemTime, UNIX_EPOCH};

        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = env::temp_dir().join(format!(
            "shinsekai-path-contract-{}-{nonce}",
            std::process::id()
        ));
        let real = root.join("real");
        let file = real.join("asset.txt");
        fs::create_dir_all(&real).unwrap();
        fs::write(&file, "safe").unwrap();
        fs::set_permissions(&file, fs::Permissions::from_mode(0o755)).unwrap();
        let file_alias = root.join("asset-link.txt");
        let directory_alias = root.join("directory-link");
        symlink(&file, &file_alias).unwrap();
        symlink(&real, &directory_alias).unwrap();

        assert!(open_regular_file_without_links(&file).is_ok());
        assert_eq!(
            canonicalize_regular_file_without_links(&file).unwrap(),
            file.canonicalize().unwrap()
        );
        assert_eq!(
            canonicalize_directory_without_links(&real).unwrap(),
            real.canonicalize().unwrap()
        );
        assert!(open_regular_file_without_links(&file_alias).is_err());
        assert!(canonicalize_regular_file_without_links(&file_alias).is_err());
        assert_eq!(
            canonicalize_regular_file_following_links_stably(&file_alias).unwrap(),
            file.canonicalize().unwrap()
        );
        assert!(canonicalize_directory_without_links(&directory_alias).is_err());
        assert_eq!(
            canonicalize_directory_following_links_stably(&directory_alias).unwrap(),
            real.canonicalize().unwrap()
        );
        assert!(open_regular_file_without_links(&directory_alias.join("asset.txt")).is_err());

        let executable_alias = real.join("tool");
        symlink(&file, &executable_alias).unwrap();
        let executable = ExecutableSnapshot::capture(executable_alias.to_str().unwrap()).unwrap();
        assert_eq!(executable.path(), file.canonicalize().unwrap());
        executable.require_current().unwrap();

        let path_selected =
            ExecutableSnapshot::capture_from_search_paths("tool", vec![real.clone()]).unwrap();
        assert_eq!(path_selected.path(), file.canonicalize().unwrap());

        let moved_executable = real.join("moved-tool-target");
        fs::rename(&file, &moved_executable).unwrap();
        fs::write(&file, "replacement").unwrap();
        fs::set_permissions(&file, fs::Permissions::from_mode(0o755)).unwrap();
        assert!(executable.require_current().is_err());
        assert!(path_selected.require_current().is_err());

        let raced_file = real.join("raced.txt");
        let moved_file = real.join("moved-raced.txt");
        fs::write(&raced_file, "captured").unwrap();
        let captured_file = open_regular_file_without_links(&raced_file).unwrap();
        fs::rename(&raced_file, &moved_file).unwrap();
        symlink(&file, &raced_file).unwrap();
        assert!(canonicalize_open_regular_file_without_links(&raced_file, &captured_file).is_err());

        let raced_directory = root.join("raced-directory");
        let moved_directory = root.join("moved-raced-directory");
        let external_directory = root.join("external-directory");
        fs::create_dir_all(&raced_directory).unwrap();
        fs::create_dir_all(&external_directory).unwrap();
        let captured_directory = open_directory_without_links(&raced_directory).unwrap();
        fs::rename(&raced_directory, &moved_directory).unwrap();
        symlink(&external_directory, &raced_directory).unwrap();
        assert!(
            canonicalize_open_directory_without_links(&raced_directory, &captured_directory)
                .is_err()
        );

        let _ = fs::remove_dir_all(root);
    }
}
