//! Publish a synced temporary file, including the replacement's metadata.
#[cfg(not(windows))]
use std::fs;
use std::{io, path::Path};

/// The caller must sync the temporary file before committing it in the same directory.
pub(crate) fn commit(source: &Path, destination: &Path) -> io::Result<()> {
    replace(source, destination)?;
    // Windows commits the move with MOVEFILE_WRITE_THROUGH. Unix also needs
    // the containing directory synced; propagating failures avoids false success.
    #[cfg(not(windows))]
    {
        let parent = destination
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        fs::File::open(parent)?.sync_all()?;
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace(source: &Path, destination: &Path) -> io::Result<()> {
    fs::rename(source, destination)
}

#[cfg(windows)]
fn replace(source: &Path, destination: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn MoveFileExW(source: *const u16, destination: *const u16, flags: u32) -> i32;
    }
    const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x8;
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
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn replacement_commits_new_data_and_failure_keeps_the_previous_file() {
        let dir = std::env::temp_dir().join(format!(
            "shinsekai-atomic-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&dir).unwrap();
        let target = dir.join("settings.json");
        let temp = dir.join("settings.tmp");
        for contents in ["first", "second"] {
            fs::write(&temp, contents).unwrap();
            fs::OpenOptions::new()
                .write(true)
                .open(&temp)
                .unwrap()
                .sync_all()
                .unwrap();
            commit(&temp, &target).unwrap();
            assert_eq!(fs::read_to_string(&target).unwrap(), contents);
            assert!(!temp.exists());
        }
        assert!(commit(&temp, &target).is_err());
        assert_eq!(fs::read_to_string(&target).unwrap(), "second");
        fs::remove_file(target).unwrap();
        fs::remove_dir(dir).unwrap();
    }
}
