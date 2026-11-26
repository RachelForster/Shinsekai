use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
};

#[cfg(windows)]
use std::ffi::OsString;
#[cfg(windows)]
use std::os::windows::ffi::{OsStrExt, OsStringExt};
#[cfg(windows)]
use std::os::windows::io::AsRawHandle;

#[cfg(unix)]
use std::os::fd::AsRawFd;

use super::ProjectRootCandidateSource;

#[cfg(windows)]
#[link(name = "kernel32")]
unsafe extern "system" {
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
const LOCKFILE_EXCLUSIVE_LOCK: u32 = 0x2;
#[cfg(windows)]
const HKEY_CURRENT_USER: *mut std::ffi::c_void = (-2_147_483_647_isize) as *mut std::ffi::c_void;
#[cfg(windows)]
const RRF_RT_REG_SZ_OR_EXPAND_SZ: u32 = 0x2 | 0x4;

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

#[cfg(unix)]
pub(super) fn lock_locator_file(file: &fs::File) -> std::io::Result<()> {
    let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) };
    if result == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(windows)]
pub(super) fn lock_locator_file(file: &fs::File) -> std::io::Result<()> {
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

pub(super) fn absolute_path(path: &Path) -> Result<PathBuf, String> {
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

pub(super) fn deduplicate_paths(paths: impl IntoIterator<Item = PathBuf>) -> Vec<PathBuf> {
    let mut seen = HashSet::new();
    paths
        .into_iter()
        .filter(|path| seen.insert(path_identity(path)))
        .collect()
}

pub(super) fn path_identity(path: &Path) -> String {
    let canonical = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
    let value = display_path(&canonical);
    #[cfg(windows)]
    {
        return value.to_lowercase();
    }
    #[cfg(not(windows))]
    value
}

pub(super) fn display_path(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}
